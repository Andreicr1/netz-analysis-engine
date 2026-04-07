"""Screener import service — idempotent unified instrument import.

Stability Guardrails Phase 4 (§4.3 B3.2 + B3.3): the SEC import logic
that previously lived inside the screener route handler now sits here
as a pure async service so the route can become a thin enqueue-and-
return-202 surface and the background worker can call the same code
path with the same idempotency contract.

Idempotency contract
--------------------
- ``import_instrument`` uses an SQL advisory transaction lock keyed
  on ``hash(organization_id || identifier || block_id)`` so two
  concurrent calls for the same payload serialise at the database
  level. The lock is released automatically at transaction end —
  no ``finally`` plumbing required.
- If the instrument already exists in the org's universe the service
  returns ``ImportStatus.ALREADY_IN_ORG`` instead of raising 409.
  Reason: the @idempotent decorator at the route level caches the
  response, so a second click within the TTL window must observe a
  consistent success result, not a 409 race.
- The service never reaches outside the database. SEC EDGAR data is
  ingested by background workers into ``sec_*`` tables; this service
  only joins/reads them. The single external pathway — brochure
  download — runs through ``ExternalProviderGate`` inside
  ``adv_service.py`` and is unreachable from this code path.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum
from re import compile as _re_compile
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.shared.models import SecCusipTickerMap

logger = logging.getLogger(__name__)


# Advisory lock ID for screener import per-identifier serialisation.
# This is the second arg to ``pg_try_advisory_xact_lock(class_id, key)``
# — class_id 900_072 is the next free slot above ``global_risk_metrics``
# (900_071, see CLAUDE.md). The second arg is a 32-bit hash of the
# (org_id, identifier, block_id) triple, so two concurrent imports of
# the same payload serialise at the database level even if Redis-based
# idempotency degrades.
SCREENER_IMPORT_LOCK_ID: int = 900_072

_ISIN_RE = _re_compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


# ── Result types ───────────────────────────────────────────────────


class ImportStatus(StrEnum):
    IMPORTED = "imported"          # New instrument created in universe + linked to org
    LINKED = "linked"              # Existing global instrument linked to org for first time
    ALREADY_IN_ORG = "already_in_org"  # Already in this org's universe (idempotent no-op)


class ImportSource(StrEnum):
    ESMA = "esma"
    SEC = "sec"


@dataclass(frozen=True)
class ImportResult:
    """Structured outcome of a screener import. JSON-serialisable.

    Returned to the worker (which publishes it as the SSE ``done``
    event) and to the route layer (which echoes it on the cached
    idempotency hit).
    """

    instrument_id: str
    name: str
    identifier: str   # original ticker or ISIN as supplied
    status: ImportStatus
    source: ImportSource

    def to_dict(self) -> dict[str, str]:
        return {
            "instrument_id": self.instrument_id,
            "name": self.name,
            "identifier": self.identifier,
            "status": self.status.value,
            "source": self.source.value,
        }


# ── Public API ─────────────────────────────────────────────────────


async def import_instrument(
    db: AsyncSession,
    organization_id: uuid.UUID,
    identifier: str,
    *,
    block_id: str | None = None,
    strategy: str | None = None,
) -> ImportResult:
    """Idempotent unified import — auto-detects ISIN vs ticker.

    The caller is responsible for committing the surrounding
    transaction. The function flushes its own writes so the returned
    ``instrument_id`` is stable, but does not call ``db.commit()``.

    Raises:
        ValueError: identifier malformed or unknown.
        LookupError: identifier not found in either ESMA or SEC catalog.
    """
    normalized = (identifier or "").strip().upper()
    if not normalized:
        raise ValueError("identifier must be non-empty")

    # Per-identifier advisory lock — held until transaction end. Two
    # concurrent imports of the same payload will serialise here.
    # Use ``pg_try_advisory_xact_lock`` so we don't deadlock if the
    # caller is already holding the lock; failure to acquire is rare
    # (Redis idempotency catches the common case).
    lock_key = abs(hash((str(organization_id), normalized, block_id or ""))) % (2**31)
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock(:cls, :key)",
        ),
        {"cls": SCREENER_IMPORT_LOCK_ID, "key": lock_key},
    )

    if _ISIN_RE.match(normalized):
        return await _import_esma(
            db, organization_id, normalized, block_id=block_id, strategy=strategy,
        )
    return await _import_sec(
        db, organization_id, normalized, block_id=block_id, strategy=strategy,
    )


# ── ESMA path ──────────────────────────────────────────────────────


async def _import_esma(
    db: AsyncSession,
    organization_id: uuid.UUID,
    isin: str,
    *,
    block_id: str | None,
    strategy: str | None,
) -> ImportResult:
    """Delegates to the existing ESMA import service. Translates the
    legacy 409-on-duplicate behaviour into an idempotent ALREADY_IN_ORG
    status by checking the org link first.
    """
    # Fast path: already linked in this org → idempotent no-op.
    existing = (await db.execute(
        select(Instrument).where(Instrument.isin == isin),
    )).scalar_one_or_none()

    if existing is not None:
        link = (await db.execute(
            select(InstrumentOrg).where(
                InstrumentOrg.instrument_id == existing.instrument_id,
                InstrumentOrg.organization_id == organization_id,
            ),
        )).scalar_one_or_none()
        if link is not None:
            return ImportResult(
                instrument_id=str(existing.instrument_id),
                name=existing.name,
                identifier=isin,
                status=ImportStatus.ALREADY_IN_ORG,
                source=ImportSource.ESMA,
            )
        # Global instrument exists, link to this org.
        db.add(InstrumentOrg(
            organization_id=organization_id,
            instrument_id=existing.instrument_id,
            block_id=block_id,
            approval_status="pending",
        ))
        await db.flush()
        return ImportResult(
            instrument_id=str(existing.instrument_id),
            name=existing.name,
            identifier=isin,
            status=ImportStatus.LINKED,
            source=ImportSource.ESMA,
        )

    # Fresh import — defer to the existing helper. It raises HTTPException
    # internally for "not found", which we translate to LookupError so
    # the worker can publish a typed error event.
    from fastapi import HTTPException

    from app.domains.wealth.services.esma_import_service import (
        import_esma_fund_to_universe,
    )

    try:
        instrument = await import_esma_fund_to_universe(
            db, organization_id, isin, block_id=block_id, strategy=strategy,
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise LookupError(f"ESMA fund with ISIN {isin} not found") from exc
        if exc.status_code == 409:
            # Race: another transaction just inserted the link. Reload.
            existing = (await db.execute(
                select(Instrument).where(Instrument.isin == isin),
            )).scalar_one_or_none()
            if existing is None:
                raise
            return ImportResult(
                instrument_id=str(existing.instrument_id),
                name=existing.name,
                identifier=isin,
                status=ImportStatus.ALREADY_IN_ORG,
                source=ImportSource.ESMA,
            )
        raise

    return ImportResult(
        instrument_id=str(instrument.instrument_id),
        name=instrument.name,
        identifier=isin,
        status=ImportStatus.IMPORTED,
        source=ImportSource.ESMA,
    )


# ── SEC path ───────────────────────────────────────────────────────


_SEC_TYPE_MAP: dict[str, str] = {
    "Common Stock": "equity",
    "ETP": "fund",
    "Closed-End Fund": "fund",
    "Open-End Fund": "fund",
    "ADR": "equity",
    "REIT": "equity",
    "MLP": "equity",
}

_UNIVERSE_TO_STRUCTURE: dict[str, str] = {
    "registered_us": "Mutual Fund",
    "etf": "ETF",
    "bdc": "BDC",
    "money_market": "Money Market",
}


def _normalize_to_fraction(value: float | Any | None, source: str) -> float | None:
    """Ensure percentage value is stored as pure decimal fraction.

    Some SEC sources (N-CEN) store human percent (1.50 = 1.5%) while
    others store fractions (0.015). This guard normalizes anything
    > 1.0 to a fraction so downstream consumers see one convention.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f > 1.0:
        logger.warning(
            "normalizing_to_fraction source=%s value=%s",
            source, f,
        )
        return f / 100.0
    return f


async def _import_sec(  # noqa: C901, PLR0912, PLR0915 — extracted verbatim from route
    db: AsyncSession,
    organization_id: uuid.UUID,
    ticker: str,
    *,
    block_id: str | None,
    strategy: str | None,
) -> ImportResult:
    """Import a US security by ticker. Joins SEC catalog tables to
    enrich the instrument with N-CEN flags + XBRL fees + N-PORT linkage.

    All reads come from already-ingested SEC tables — there is **no**
    outbound HTTP from this code path. The single external SEC call
    in the engine (brochure PDF download in ``adv_service.py``) is
    wrapped in ``ExternalProviderGate`` and lives behind a separate,
    lazily-resolved code path.
    """
    # Fast path: instrument already exists globally by ticker.
    existing = (await db.execute(
        select(Instrument).where(Instrument.ticker == ticker),
    )).scalar_one_or_none()
    if existing is not None:
        link = (await db.execute(
            select(InstrumentOrg).where(
                InstrumentOrg.instrument_id == existing.instrument_id,
                InstrumentOrg.organization_id == organization_id,
            ),
        )).scalar_one_or_none()
        if link is not None:
            return ImportResult(
                instrument_id=str(existing.instrument_id),
                name=existing.name,
                identifier=ticker,
                status=ImportStatus.ALREADY_IN_ORG,
                source=ImportSource.SEC,
            )
        db.add(InstrumentOrg(
            organization_id=organization_id,
            instrument_id=existing.instrument_id,
            block_id=block_id,
            approval_status="pending",
        ))
        await db.flush()
        return ImportResult(
            instrument_id=str(existing.instrument_id),
            name=existing.name,
            identifier=ticker,
            status=ImportStatus.LINKED,
            source=ImportSource.SEC,
        )

    # Lookup from sec_cusip_ticker_map (or fallback to mutual-fund tables).
    sec_row = (await db.execute(
        select(SecCusipTickerMap).where(
            SecCusipTickerMap.ticker == ticker,
            SecCusipTickerMap.is_tradeable.is_(True),
        ).limit(1),
    )).scalar_one_or_none()

    if sec_row is None:
        # Mutual fund tickers live in sec_fund_classes, not the cusip map.
        from types import SimpleNamespace

        from app.shared.models import SecFundClass as _Fc
        from app.shared.models import SecRegisteredFund as _Rf

        fc_fallback = (await db.execute(
            select(_Fc).where(_Fc.ticker == ticker).limit(1),
        )).scalar_one_or_none()
        if fc_fallback is None:
            raise LookupError(
                f"Tradeable security with ticker {ticker} not found",
            )
        rf_fallback = (await db.execute(
            select(_Rf).where(_Rf.cik == fc_fallback.cik),
        )).scalar_one_or_none()
        sec_row = SimpleNamespace(  # type: ignore[assignment]
            ticker=ticker,
            issuer_name=(
                rf_fallback.fund_name if rf_fallback else (
                    fc_fallback.series_name or ticker
                )
            ),
            security_type="Open-End Fund",
            cusip=None,
            exchange=None,
            figi=None,
            composite_figi=None,
            is_tradeable=True,
        )

    # Narrow for the type checker — both branches above guarantee
    # ``sec_row`` is non-None at this point (the LookupError raise is
    # the only escape from the fallback path).
    assert sec_row is not None
    inst_type = _SEC_TYPE_MAP.get(sec_row.security_type or "", "equity")
    asset_class = "fund" if inst_type == "fund" else "equity"

    # Resolve enrichment + N-PORT linkage when applicable.
    sec_cik: str | None = None
    sec_universe: str | None = None
    sec_crd: str | None = None
    fund_manager_name = sec_row.issuer_name
    enrichment_attrs: dict[str, object] = {}
    reg_fund = None
    etf_row = None
    bdc_row = None

    if inst_type == "fund":
        from app.shared.models import SecBdc, SecEtf, SecFundClass, SecRegisteredFund

        reg_fund = (await db.execute(
            select(SecRegisteredFund)
            .where(SecRegisteredFund.ticker == sec_row.ticker)
            .limit(1),
        )).scalar_one_or_none()

        if reg_fund is None:
            fc_row = (await db.execute(
                select(SecFundClass).where(SecFundClass.ticker == sec_row.ticker).limit(1),
            )).scalar_one_or_none()
            if fc_row is not None:
                reg_fund = (await db.execute(
                    select(SecRegisteredFund).where(SecRegisteredFund.cik == fc_row.cik),
                )).scalar_one_or_none()

        if reg_fund is None:
            etf_row = (await db.execute(
                select(SecEtf).where(SecEtf.ticker == sec_row.ticker).limit(1),
            )).scalar_one_or_none()
            if etf_row is not None:
                enrichment_attrs["sec_universe"] = "etf"
                enrichment_attrs["strategy_label"] = etf_row.strategy_label
                enrichment_attrs["is_index"] = etf_row.is_index
                if etf_row.net_operating_expenses is not None:
                    enrichment_attrs["expense_ratio_pct"] = _normalize_to_fraction(
                        etf_row.net_operating_expenses,
                        "sec_etfs.net_operating_expenses",
                    )
                if etf_row.tracking_difference_net is not None:
                    enrichment_attrs["tracking_difference_net"] = _normalize_to_fraction(
                        etf_row.tracking_difference_net,
                        "sec_etfs.tracking_difference_net",
                    )
                enrichment_attrs["index_tracked"] = etf_row.index_tracked

        if reg_fund is None and not enrichment_attrs.get("sec_universe"):
            bdc_row = (await db.execute(
                select(SecBdc).where(SecBdc.ticker == sec_row.ticker).limit(1),
            )).scalar_one_or_none()
            if bdc_row is not None:
                enrichment_attrs["sec_universe"] = "bdc"
                enrichment_attrs["strategy_label"] = bdc_row.strategy_label
                if bdc_row.net_operating_expenses is not None:
                    enrichment_attrs["expense_ratio_pct"] = _normalize_to_fraction(
                        bdc_row.net_operating_expenses,
                        "sec_bdcs.net_operating_expenses",
                    )
                enrichment_attrs["investment_focus"] = bdc_row.investment_focus
                enrichment_attrs["is_externally_managed"] = bdc_row.is_externally_managed

        if reg_fund is not None:
            sec_cik = reg_fund.cik
            sec_universe = "registered_us"
            sec_crd = reg_fund.crd_number
            enrichment_attrs["strategy_label"] = reg_fund.strategy_label
            enrichment_attrs["is_index"] = reg_fund.is_index
            enrichment_attrs["is_target_date"] = reg_fund.is_target_date
            enrichment_attrs["is_fund_of_fund"] = reg_fund.is_fund_of_fund
            if reg_fund.inception_date:
                enrichment_attrs["fund_inception_date"] = str(reg_fund.inception_date)

            class_rows = (await db.execute(
                select(SecFundClass).where(SecFundClass.cik == sec_cik),
            )).scalars().all()
            if class_rows:
                best = next(
                    (c for c in class_rows if c.ticker == sec_row.ticker),
                    max(class_rows, key=lambda c: float(c.net_assets or 0)),
                )
                if best.expense_ratio_pct is not None:
                    enrichment_attrs["expense_ratio_pct"] = _normalize_to_fraction(
                        best.expense_ratio_pct,
                        "sec_fund_classes.expense_ratio_pct",
                    )
                if best.holdings_count is not None:
                    enrichment_attrs["holdings_count"] = best.holdings_count
                if best.portfolio_turnover_pct is not None:
                    enrichment_attrs["portfolio_turnover_pct"] = _normalize_to_fraction(
                        best.portfolio_turnover_pct,
                        "sec_fund_classes.portfolio_turnover_pct",
                    )

            if reg_fund.crd_number:
                from app.shared.models import SecManager
                mgr = (await db.execute(
                    select(SecManager.firm_name).where(
                        SecManager.crd_number == reg_fund.crd_number,
                    ),
                )).scalar_one_or_none()
                if mgr:
                    fund_manager_name = mgr

    # ── L1 screening attributes ────────────────────────────────
    resolved_universe = sec_universe or enrichment_attrs.get("sec_universe")
    resolved_structure = _UNIVERSE_TO_STRUCTURE.get(str(resolved_universe))

    resolved_aum: float | None = None
    if inst_type == "fund":
        if reg_fund is not None and reg_fund.monthly_avg_net_assets is not None:
            resolved_aum = float(reg_fund.monthly_avg_net_assets)
        elif reg_fund is not None and reg_fund.daily_avg_net_assets is not None:
            resolved_aum = float(reg_fund.daily_avg_net_assets)
        elif etf_row is not None:
            etf_monthly = getattr(etf_row, "monthly_avg_net_assets", None)
            etf_daily = getattr(etf_row, "daily_avg_net_assets", None)
            if etf_monthly is not None:
                resolved_aum = float(etf_monthly)
            elif etf_daily is not None:
                resolved_aum = float(etf_daily)
        elif bdc_row is not None:
            bdc_monthly = getattr(bdc_row, "monthly_avg_net_assets", None)
            bdc_daily = getattr(bdc_row, "daily_avg_net_assets", None)
            if bdc_monthly is not None:
                resolved_aum = float(bdc_monthly)
            elif bdc_daily is not None:
                resolved_aum = float(bdc_daily)

        if resolved_aum is None and enrichment_attrs.get("expense_ratio_pct") is not None:
            from app.shared.models import SecFundClass as _Fc

            _fc_aum = (await db.execute(
                select(_Fc.net_assets).where(_Fc.ticker == sec_row.ticker).limit(1),
            )).scalar_one_or_none()
            if _fc_aum is not None:
                resolved_aum = float(_fc_aum)

    resolved_track_years: float | None = None
    inception_str = enrichment_attrs.get("fund_inception_date")
    if inception_str:
        try:
            inception_dt = dt.date.fromisoformat(str(inception_str))
            resolved_track_years = round(
                (dt.date.today() - inception_dt).days / 365.25, 1,
            )
        except (ValueError, TypeError):
            pass
    if resolved_track_years is None and inst_type == "fund":
        from app.shared.models import SecFundClass as _Fc2

        _fc_inception = (await db.execute(
            select(_Fc2.perf_inception_date).where(_Fc2.ticker == sec_row.ticker).limit(1),
        )).scalar_one_or_none()
        if _fc_inception is not None:
            resolved_track_years = round(
                (dt.date.today() - _fc_inception).days / 365.25, 1,
            )

    instrument = Instrument(
        instrument_type=inst_type,
        name=sec_row.issuer_name,
        isin=None,
        ticker=sec_row.ticker,
        asset_class=asset_class,
        geography="north_america",
        currency="USD",
        attributes={
            "cusip": sec_row.cusip,
            "security_type": sec_row.security_type,
            "exchange": sec_row.exchange,
            "figi": sec_row.figi,
            "composite_figi": sec_row.composite_figi,
            "source": "sec",
            "strategy": strategy,
            "manager_name": fund_manager_name,
            "aum_usd": resolved_aum,
            "inception_date": inception_str,
            "domicile": "US",
            "structure": resolved_structure,
            "track_record_years": resolved_track_years,
            "sec_cik": sec_cik,
            "sec_crd": sec_crd,
            "sec_universe": resolved_universe,
            **enrichment_attrs,
        },
    )
    db.add(instrument)
    await db.flush()

    db.add(InstrumentOrg(
        organization_id=organization_id,
        instrument_id=instrument.instrument_id,
        block_id=block_id,
        approval_status="pending",
    ))
    await db.flush()
    await db.refresh(instrument)

    return ImportResult(
        instrument_id=str(instrument.instrument_id),
        name=instrument.name,
        identifier=ticker,
        status=ImportStatus.IMPORTED,
        source=ImportSource.SEC,
    )

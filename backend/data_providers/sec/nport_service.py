"""N-PORT Service — monthly mutual fund portfolio holdings via edgartools.

Parses N-PORT filings, persists holdings to ``sec_nport_holdings``.
N-PORT filings provide monthly portfolio holdings for ~15K+ US mutual funds,
expanding coverage beyond the ~5K 13F filers.

Sync service — dispatched via ``run_in_sec_thread()`` from async callers.
Rate limit: shared EDGAR rate limiter (8 req/s).
Lifecycle: Instantiate ONCE in FastAPI lifespan().
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any
from xml.etree.ElementTree import Element

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.shared.models import SecNportHolding as SecNportHoldingModel
from data_providers.sec.models import NportHolding
from data_providers.sec.shared import check_edgar_rate, run_in_sec_thread

logger = structlog.get_logger()

_CIK_RE = re.compile(r"^\d{1,10}$")

# N-PORT can have thousands of holdings per filing.
_MAX_HOLDINGS_PER_FILING = 20_000

# Upsert chunk size (asyncpg parameter limit).
_CHUNK_SIZE = 2000


def _validate_cik(cik: str) -> bool:
    """Validate CIK format: 1-10 digits."""
    return bool(_CIK_RE.match(cik))


def _safe_int(val: Any) -> int | None:
    """Convert a value to int, returning None on failure."""
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


def _safe_float(val: Any) -> float | None:
    """Convert a value to float, returning None on failure."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_nport_xml_holdings(
    root: Element,
    cik: str,
    report_date: str,
) -> list[NportHolding]:
    """Extract holdings from N-PORT XML ``<invstOrSec>`` elements.

    Uses iterative parsing to handle large filings without full DOM load.
    """
    holdings: list[NportHolding] = []

    # N-PORT XML namespace varies; search without namespace
    # Common structure: <edgarSubmission>...<invstOrSecs><invstOrSec>...
    def _text(elem: Element, tag: str) -> str | None:
        """Find child element text regardless of XML namespace."""
        for child in elem.iter():
            if child.tag.endswith(tag) and child.text:
                return child.text.strip()
        return None

    for elem in root.iter():
        if not elem.tag.endswith("invstOrSec"):
            continue

        cusip = _text(elem, "cusip")
        if not cusip:
            continue  # Skip holdings without CUSIP

        holding = NportHolding(
            cik=cik,
            report_date=report_date,
            cusip=cusip,
            isin=_text(elem, "isin"),
            issuer_name=_text(elem, "name"),
            asset_class=_text(elem, "assetCat"),
            sector=_text(elem, "issuerCat"),
            market_value=_safe_int(_text(elem, "valUSD")),
            quantity=_safe_float(_text(elem, "balance")),
            currency=_text(elem, "curCd"),
            pct_of_nav=_safe_float(_text(elem, "pctVal")),
            is_restricted=(_text(elem, "isRestrictedSec") or "").upper() == "Y",
            fair_value_level=_text(elem, "fairValLevel"),
        )
        holdings.append(holding)

        if len(holdings) >= _MAX_HOLDINGS_PER_FILING:
            logger.warning(
                "nport_holdings_truncated",
                cik=cik,
                max=_MAX_HOLDINGS_PER_FILING,
            )
            break

    return holdings


class NportService:
    """N-PORT holdings parser via edgartools.

    Sync service — dispatched via ``run_in_sec_thread()`` from async callers.
    Uses ``Company(cik).get_filings(form="NPORT-P")`` for filing access.
    Rate limit: shared EDGAR rate limiter (8 req/s).

    Lifecycle: Instantiate ONCE. Config injected as parameter.
    """

    def __init__(
        self,
        db_session_factory: Callable[..., Any],
        rate_check: Callable[[], None] | None = None,
    ) -> None:
        self._db_session_factory = db_session_factory
        self._rate_check = rate_check or check_edgar_rate

    # ── Public API ──────────────────────────────────────────────────

    async def fetch_holdings(
        self,
        cik: str,
        *,
        months: int = 12,
        force_refresh: bool = False,
        staleness_ttl_days: int = 45,
    ) -> list[NportHolding]:
        """Fetch monthly N-PORT holdings for a filer. Never raises.

        1. If ``force_refresh`` is False, check DB for recent data.
        2. If stale or missing, parse from EDGAR via edgartools.
        3. Upsert holdings to ``sec_nport_holdings``.
        4. Return frozen dataclasses.
        """
        if not _validate_cik(cik):
            logger.warning("nport_invalid_cik", cik=cik)
            return []

        try:
            # Check staleness
            if not force_refresh:
                cached = await self._read_holdings_from_db(cik, months)
                if cached and not self._is_stale(cached, staleness_ttl_days):
                    logger.debug("nport_cache_hit", cik=cik, count=len(cached))
                    return cached

            # Parse from EDGAR
            holdings = await run_in_sec_thread(
                self._parse_nport_filings, cik, months,
            )
            if not holdings:
                logger.info("nport_no_holdings", cik=cik)
                return []

            # Persist
            await self._upsert_holdings(holdings)

            # Re-read from DB
            holdings = await self._read_holdings_from_db(cik, months)

            logger.info(
                "nport_fetch_complete",
                cik=cik,
                holdings=len(holdings),
            )
            return holdings
        except Exception as exc:
            logger.error(
                "nport_fetch_failed",
                cik=cik,
                error=str(exc),
            )
            return []

    # ── Internal — EDGAR parsing (sync, rate-limited) ───────────────

    def _parse_nport_filings(
        self,
        cik: str,
        months: int,
    ) -> list[NportHolding]:
        """Parse N-PORT filings via edgartools. Runs in thread pool."""
        from edgartools import Company  # noqa: PLC0415

        self._rate_check()
        company = Company(cik)

        self._rate_check()
        filings = company.get_filings(form="NPORT-P")
        if not filings or len(filings) == 0:
            return []

        # Limit to recent filings based on months
        max_filings = min(months, 24)
        all_holdings: list[NportHolding] = []

        for i, filing in enumerate(filings):
            if i >= max_filings:
                break

            try:
                self._rate_check()
                # Get the XML content
                xml_content = filing.xml()
                if not xml_content:
                    continue

                import xml.etree.ElementTree as ET  # noqa: PLC0415

                root = ET.fromstring(xml_content)

                # Extract report date from filing header
                report_date_str = None
                for elem in root.iter():
                    if elem.tag.endswith("repPd") and elem.text:
                        report_date_str = elem.text.strip()[:10]
                        break

                if not report_date_str:
                    # Fallback to filing date
                    report_date_str = str(filing.filing_date)

                holdings = _parse_nport_xml_holdings(root, cik, report_date_str)
                all_holdings.extend(holdings)

            except Exception as exc:
                logger.warning(
                    "nport_filing_parse_failed",
                    cik=cik,
                    filing_index=i,
                    error=str(exc),
                )
                continue

        return all_holdings

    # ── Internal — DB operations ────────────────────────────────────

    async def _read_holdings_from_db(
        self,
        cik: str,
        months: int,
    ) -> list[NportHolding]:
        """Read holdings from sec_nport_holdings hypertable."""
        cutoff = date.today() - timedelta(days=months * 31)
        async with self._db_session_factory() as db:
            result = await db.execute(
                select(SecNportHoldingModel)
                .where(
                    SecNportHoldingModel.cik == cik,
                    SecNportHoldingModel.report_date >= cutoff,
                )
                .order_by(SecNportHoldingModel.report_date.desc()),
            )
            rows = result.scalars().all()
            return [
                NportHolding(
                    cik=r.cik,
                    report_date=r.report_date.isoformat(),
                    cusip=r.cusip,
                    isin=r.isin,
                    issuer_name=r.issuer_name,
                    asset_class=r.asset_class,
                    sector=r.sector,
                    market_value=r.market_value,
                    quantity=float(r.quantity) if r.quantity is not None else None,
                    currency=r.currency,
                    pct_of_nav=float(r.pct_of_nav) if r.pct_of_nav is not None else None,
                    is_restricted=r.is_restricted,
                    fair_value_level=r.fair_value_level,
                )
                for r in rows
            ]

    def _is_stale(
        self,
        holdings: list[NportHolding],
        ttl_days: int,
    ) -> bool:
        """Check if the most recent holding is older than TTL."""
        if not holdings:
            return True
        latest = max(holdings, key=lambda h: h.report_date)
        try:
            latest_date = date.fromisoformat(latest.report_date)
        except (ValueError, TypeError):
            return True
        return (date.today() - latest_date).days > ttl_days

    async def _upsert_holdings(self, holdings: list[NportHolding]) -> None:
        """Upsert holdings to sec_nport_holdings in chunks of 2000."""
        rows = [
            {
                "report_date": date.fromisoformat(h.report_date),
                "cik": h.cik,
                "cusip": h.cusip,
                "isin": h.isin,
                "issuer_name": h.issuer_name,
                "asset_class": h.asset_class,
                "sector": h.sector,
                "market_value": h.market_value,
                "quantity": h.quantity,
                "currency": h.currency,
                "pct_of_nav": h.pct_of_nav,
                "is_restricted": h.is_restricted,
                "fair_value_level": h.fair_value_level,
            }
            for h in holdings
        ]

        async with self._db_session_factory() as db:
            for i in range(0, len(rows), _CHUNK_SIZE):
                chunk = rows[i : i + _CHUNK_SIZE]
                stmt = pg_insert(SecNportHoldingModel).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["report_date", "cik", "cusip"],
                    set_={
                        "isin": stmt.excluded.isin,
                        "issuer_name": stmt.excluded.issuer_name,
                        "asset_class": stmt.excluded.asset_class,
                        "sector": stmt.excluded.sector,
                        "market_value": stmt.excluded.market_value,
                        "quantity": stmt.excluded.quantity,
                        "currency": stmt.excluded.currency,
                        "pct_of_nav": stmt.excluded.pct_of_nav,
                        "is_restricted": stmt.excluded.is_restricted,
                        "fair_value_level": stmt.excluded.fair_value_level,
                    },
                )
                await db.execute(stmt)
            await db.commit()

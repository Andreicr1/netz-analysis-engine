"""13F Service — quarterly institutional holdings via edgartools.

Parses 13F-HR filings, persists holdings to ``sec_13f_holdings``, computes
quarter-over-quarter diffs into ``sec_13f_diffs``, and exposes aggregation
helpers (sector, concentration).

Both sec_13f_holdings and sec_13f_diffs are TimescaleDB hypertables.
All queries MUST include a report_date / quarter_to filter for chunk pruning.

Sync service — dispatched via ``run_in_sec_thread()`` from async callers.
Rate limit: shared EDGAR rate limiter (8 req/s).
Lifecycle: Instantiate ONCE in FastAPI lifespan().
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.shared.models import Sec13fDiff as Sec13fDiffModel
from app.shared.models import Sec13fHolding as Sec13fHoldingModel
from data_providers.sec.models import ThirteenFDiff, ThirteenFHolding
from data_providers.sec.shared import check_edgar_rate, resolve_sector, run_in_sec_thread

logger = structlog.get_logger()

_CIK_RE = re.compile(r"^\d{1,10}$")

# Maximum holdings per filing to prevent memory issues (Vanguard has 24K+).
_MAX_HOLDINGS_PER_FILING = 15_000

# Upsert chunk size (asyncpg parameter limit).
_CHUNK_SIZE = 2000


def _validate_cik(cik: str) -> bool:
    """Validate CIK format: 1-10 digits."""
    return bool(_CIK_RE.match(cik))


def _quarter_end(d: date) -> date:
    """Snap a date to its quarter-end."""
    q = (d.month - 1) // 3
    ends = [date(d.year, 3, 31), date(d.year, 6, 30), date(d.year, 9, 30), date(d.year, 12, 31)]
    return ends[q]


class ThirteenFService:
    """13F-HR holdings parser via edgartools.

    Sync service — dispatched via ``run_in_sec_thread()`` from async callers.
    Uses ``Company(cik).get_filings(form="13F-HR")`` for filing access.
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

    # ── Public API (DB-only reads) ───────────────────────────────────

    async def read_holdings(
        self,
        cik: str,
        *,
        quarters: int = 8,
    ) -> list[ThirteenFHolding]:
        """Read holdings from DB only. Never calls EDGAR. Never raises.

        Use this in hot paths (DD report, routes) where latency matters.
        Data is populated by the ``sec_13f_ingestion`` background worker.
        """
        if not _validate_cik(cik):
            return []
        return await self._read_holdings_from_db(cik, quarters)

    async def read_holdings_for_date(
        self,
        cik: str,
        report_date: date,
    ) -> list[ThirteenFHolding]:
        """Read holdings for a specific quarter from DB only. Never raises."""
        if not _validate_cik(cik):
            return []
        return await self._read_holdings_for_date(cik, report_date)

    # ── Public API (may call EDGAR — workers only) ────────────────

    async def fetch_holdings(
        self,
        cik: str,
        *,
        quarters: int = 8,
        force_refresh: bool = False,
        staleness_ttl_days: int = 45,
    ) -> list[ThirteenFHolding]:
        """Fetch quarterly 13F holdings for a filer. Never raises.

        1. If ``force_refresh`` is False, check DB for recent data.
        2. If stale or missing, parse from EDGAR via edgartools.
        3. Upsert holdings to ``sec_13f_holdings``.
        4. Return frozen dataclasses.
        """
        if not _validate_cik(cik):
            logger.warning("thirteenf_invalid_cik", cik=cik)
            return []

        try:
            # Check staleness
            if not force_refresh:
                cached = await self._read_holdings_from_db(cik, quarters)
                if cached and not self._is_stale(cached, staleness_ttl_days):
                    logger.debug("thirteenf_cache_hit", cik=cik, count=len(cached))
                    return cached

            # Parse from EDGAR
            holdings = await run_in_sec_thread(
                self._parse_13f_filings, cik, quarters,
            )
            if not holdings:
                logger.info("thirteenf_no_holdings", cik=cik)
                return []

            # Persist
            await self._upsert_holdings(holdings)

            # Re-read from DB (includes any previously enriched sectors)
            holdings = await self._read_holdings_from_db(cik, quarters)

            # Enrich CUSIPs missing sector (best-effort, non-blocking)
            report_dates = {h.report_date for h in holdings if h.sector is None}
            if report_dates:
                for rd in report_dates:
                    try:
                        await self.enrich_holdings_with_sectors(
                            cik, date.fromisoformat(rd),
                        )
                    except Exception as exc:
                        logger.debug("thirteenf_enrich_after_fetch_failed", error=str(exc))
                # Re-read only if enrichment ran
                holdings = await self._read_holdings_from_db(cik, quarters)

            logger.info(
                "thirteenf_fetch_complete",
                cik=cik,
                holdings=len(holdings),
            )
            return holdings
        except Exception as exc:
            logger.error(
                "thirteenf_fetch_failed",
                cik=cik,
                error=str(exc),
            )
            return []

    async def compute_diffs(
        self,
        cik: str,
        quarter_from: date,
        quarter_to: date,
    ) -> list[ThirteenFDiff]:
        """Compute quarter-over-quarter diffs. Persists to ``sec_13f_diffs``.

        Reads holdings from DB for both quarters, computes deltas, upserts.
        Separate transaction from holdings upsert. Never raises.
        """
        if not _validate_cik(cik):
            logger.warning("thirteenf_diff_invalid_cik", cik=cik)
            return []

        try:
            from_holdings = await self._read_holdings_for_date(cik, quarter_from)
            to_holdings = await self._read_holdings_for_date(cik, quarter_to)

            if not to_holdings:
                logger.info(
                    "thirteenf_diff_no_target_quarter",
                    cik=cik,
                    quarter_to=quarter_to.isoformat(),
                )
                return []

            diffs = self._compute_diffs_internal(
                cik, from_holdings, to_holdings, quarter_from, quarter_to,
            )

            if diffs:
                await self._upsert_diffs(diffs)

            logger.info(
                "thirteenf_diffs_computed",
                cik=cik,
                quarter_from=quarter_from.isoformat(),
                quarter_to=quarter_to.isoformat(),
                diffs=len(diffs),
            )
            return diffs
        except Exception as exc:
            logger.error(
                "thirteenf_diff_failed",
                cik=cik,
                error=str(exc),
            )
            return []

    async def get_sector_aggregation(
        self,
        cik: str,
        report_date: date,
    ) -> dict[str, float]:
        """Aggregate holdings by industry sector. Returns ``{sector: weight}``.

        Only includes equity positions (excludes CALL/PUT options which are
        derivative overlays and distort sector composition).
        Sectors follow GICS classification where available.
        Never raises.
        """
        if not _validate_cik(cik):
            return {}

        try:
            holdings = await self._read_holdings_for_date(cik, report_date)
            if not holdings:
                return {}

            # Exclude options — only equity positions reflect sector exposure
            equity = [
                h for h in holdings
                if (h.asset_class or "").upper() not in ("CALL", "PUT")
            ]
            if not equity:
                return {}

            total_value = sum(h.market_value or 0 for h in equity)
            if total_value <= 0:
                return {}

            sector_totals: dict[str, int] = {}
            for h in equity:
                sector = h.sector or "Unknown"
                sector_totals[sector] = sector_totals.get(sector, 0) + (h.market_value or 0)

            return {
                sector: round(val / total_value, 6)
                for sector, val in sorted(sector_totals.items(), key=lambda x: -x[1])
            }
        except Exception as exc:
            logger.error("thirteenf_sector_agg_failed", cik=cik, error=str(exc))
            return {}

    async def get_concentration_metrics(
        self,
        cik: str,
        report_date: date,
    ) -> dict[str, float]:
        """HHI, top-10 concentration, position count. Never raises."""
        if not _validate_cik(cik):
            return {}

        try:
            holdings = await self._read_holdings_for_date(cik, report_date)
            if not holdings:
                return {}

            total_value = sum(h.market_value or 0 for h in holdings)
            if total_value <= 0:
                return {}

            weights = sorted(
                [(h.market_value or 0) / total_value for h in holdings],
                reverse=True,
            )

            hhi = sum(w * w for w in weights)
            top_10 = sum(weights[:10])

            return {
                "hhi": round(hhi, 6),
                "top_10_concentration": round(top_10, 6),
                "position_count": float(len(holdings)),
            }
        except Exception as exc:
            logger.error("thirteenf_concentration_failed", cik=cik, error=str(exc))
            return {}

    async def enrich_holdings_with_sectors(
        self,
        cik: str,
        report_date: date,
    ) -> int:
        """Backfill sector for holdings missing sector data.

        Resolves sector per unique CUSIP via ``resolve_sector()`` (3-tier:
        SIC mapping, OpenFIGI/keyword heuristic). Updates DB rows.
        Returns count of CUSIPs enriched. Never raises.
        """
        if not _validate_cik(cik):
            return 0

        try:
            holdings = await self._read_holdings_for_date(cik, report_date)
            # Collect unique CUSIPs missing sector
            to_resolve: dict[str, str] = {}  # cusip -> issuer_name
            for h in holdings:
                if h.sector is None and h.cusip not in to_resolve:
                    to_resolve[h.cusip] = h.issuer_name

            if not to_resolve:
                return 0

            # Resolve sectors (sync, rate-limited — run in thread pool)
            resolved: dict[str, str | None] = {}
            for cusip, issuer in to_resolve.items():
                sector = await run_in_sec_thread(resolve_sector, cusip, issuer)
                if sector:
                    resolved[cusip] = sector

            if not resolved:
                logger.debug(
                    "thirteenf_enrich_no_sectors_resolved",
                    cik=cik,
                    attempted=len(to_resolve),
                )
                return 0

            # Update DB rows
            async with self._db_session_factory() as session, session.begin():
                from sqlalchemy import update

                for cusip, sector in resolved.items():
                    stmt = (
                        update(Sec13fHoldingModel)
                        .where(
                            Sec13fHoldingModel.cik == cik,
                            Sec13fHoldingModel.report_date == report_date,
                            Sec13fHoldingModel.cusip == cusip,
                        )
                        .values(sector=sector)
                    )
                    await session.execute(stmt)

            logger.info(
                "thirteenf_sectors_enriched",
                cik=cik,
                report_date=report_date.isoformat(),
                enriched=len(resolved),
                attempted=len(to_resolve),
            )
            return len(resolved)
        except Exception as exc:
            logger.error(
                "thirteenf_enrich_failed",
                cik=cik,
                error=str(exc),
            )
            return 0

    # ── EDGAR Parsing (sync, runs in SEC thread pool) ───────────────

    def _parse_13f_filings(
        self,
        cik: str,
        quarters: int,
    ) -> list[ThirteenFHolding]:
        """Parse 13F-HR filings via edgartools. Sync — called via run_in_sec_thread."""
        from edgar import Company  # lazy import — edgartools uses nest-asyncio

        self._rate_check()

        try:
            company = Company(cik)
        except Exception as exc:
            logger.warning("thirteenf_company_lookup_failed", cik=cik, error=str(exc))
            return []

        try:
            filings = company.get_filings(form="13F-HR")
        except Exception as exc:
            logger.warning("thirteenf_filings_fetch_failed", cik=cik, error=str(exc))
            return []

        if not filings or len(filings) == 0:
            return []

        # Limit to requested quarters
        filings_list = filings.head(quarters)

        all_holdings: list[ThirteenFHolding] = []
        seen_periods: set[date] = set()

        for filing in filings_list:
            self._rate_check()

            try:
                report = filing.obj()
            except Exception as exc:
                logger.debug(
                    "thirteenf_filing_parse_failed",
                    cik=cik,
                    accession=getattr(filing, "accession_number", "?"),
                    error=str(exc),
                )
                continue

            # Check for info table (13F-NT filings have none)
            if not hasattr(report, "has_infotable") or not report.has_infotable():
                logger.debug(
                    "thirteenf_no_infotable",
                    cik=cik,
                    accession=getattr(filing, "accession_number", "?"),
                )
                continue

            # Determine report period
            report_period: date | None = None
            if hasattr(report, "report_period"):
                rp = report.report_period
                if isinstance(rp, date):
                    report_period = rp
                elif isinstance(rp, str):
                    try:
                        report_period = date.fromisoformat(rp)
                    except ValueError:
                        pass

            if report_period is None:
                report_period = _quarter_end(
                    getattr(filing, "filing_date", date.today()),
                )

            # Skip duplicate report periods (amendment handling — take first/latest)
            if report_period in seen_periods:
                logger.debug(
                    "thirteenf_duplicate_period_skipped",
                    cik=cik,
                    report_date=report_period.isoformat(),
                )
                continue
            seen_periods.add(report_period)

            filing_date_val = getattr(filing, "filing_date", date.today())
            if isinstance(filing_date_val, str):
                try:
                    filing_date_val = date.fromisoformat(filing_date_val)
                except ValueError:
                    filing_date_val = date.today()

            accession = getattr(filing, "accession_number", "") or getattr(filing, "accession_no", "") or ""

            # Parse holdings DataFrame
            try:
                holdings_df = report.holdings
            except Exception as exc:
                logger.debug(
                    "thirteenf_holdings_access_failed",
                    cik=cik,
                    error=str(exc),
                )
                continue

            if holdings_df is None or len(holdings_df) == 0:
                continue

            # Cap holdings to prevent memory issues
            if len(holdings_df) > _MAX_HOLDINGS_PER_FILING:
                logger.warning(
                    "thirteenf_holdings_capped",
                    cik=cik,
                    original=len(holdings_df),
                    capped=_MAX_HOLDINGS_PER_FILING,
                )
                holdings_df = holdings_df.head(_MAX_HOLDINGS_PER_FILING)

            now_iso = datetime.now(UTC).isoformat()

            for _, row in holdings_df.iterrows():
                cusip = str(row.get("Cusip", "") or "").strip()
                if not cusip:
                    continue

                # edgartools already converts Value from thousands to USD
                raw_value = row.get("Value")
                market_value: int | None = None
                if raw_value is not None:
                    try:
                        market_value = int(float(raw_value))
                    except (ValueError, TypeError):
                        pass

                shares_raw = row.get("SharesPrnAmount") or row.get("Shares")
                shares: int | None = None
                if shares_raw is not None:
                    try:
                        shares = int(float(shares_raw))
                    except (ValueError, TypeError):
                        pass

                all_holdings.append(ThirteenFHolding(
                    cik=cik,
                    report_date=report_period.isoformat(),
                    filing_date=filing_date_val.isoformat(),
                    accession_number=accession,
                    cusip=cusip,
                    issuer_name=str(row.get("Issuer", "") or "").strip() or cusip,
                    asset_class=str(row.get("Type", "") or "").strip() or None,
                    shares=shares,
                    market_value=market_value,
                    discretion=str(row.get("Discretion", "") or "").strip() or None,
                    voting_sole=_safe_int(row.get("Sole")),
                    voting_shared=_safe_int(row.get("Shared")),
                    voting_none=_safe_int(row.get("None_")),
                ))

        return all_holdings

    # ── Diff Computation ──────────────────────────────────────────────

    @staticmethod
    def _compute_diffs_internal(
        cik: str,
        from_holdings: list[ThirteenFHolding],
        to_holdings: list[ThirteenFHolding],
        quarter_from: date,
        quarter_to: date,
    ) -> list[ThirteenFDiff]:
        """Compute diffs between two quarters' holdings."""
        from_map: dict[str, ThirteenFHolding] = {h.cusip: h for h in from_holdings}
        to_map: dict[str, ThirteenFHolding] = {h.cusip: h for h in to_holdings}

        from_total = sum(h.market_value or 0 for h in from_holdings) or 1
        to_total = sum(h.market_value or 0 for h in to_holdings) or 1

        all_cusips = set(from_map.keys()) | set(to_map.keys())
        diffs: list[ThirteenFDiff] = []

        for cusip in all_cusips:
            h_from = from_map.get(cusip)
            h_to = to_map.get(cusip)

            shares_before = h_from.shares if h_from else None
            shares_after = h_to.shares if h_to else None
            value_before = h_from.market_value if h_from else None
            value_after = h_to.market_value if h_to else None

            # Determine action
            if h_from is None and h_to is not None:
                action = "NEW_POSITION"
            elif h_from is not None and h_to is None:
                action = "EXITED"
            elif shares_before is not None and shares_after is not None:
                if shares_after > shares_before:
                    action = "INCREASED"
                elif shares_after < shares_before:
                    action = "DECREASED"
                else:
                    action = "UNCHANGED"
            else:
                action = "UNCHANGED"

            shares_delta: int | None = None
            if shares_before is not None and shares_after is not None:
                shares_delta = shares_after - shares_before
            elif shares_after is not None:
                shares_delta = shares_after
            elif shares_before is not None:
                shares_delta = -shares_before

            weight_before = (value_before / from_total) if value_before else None
            weight_after = (value_after / to_total) if value_after else None

            issuer = (h_to.issuer_name if h_to else None) or (h_from.issuer_name if h_from else cusip)

            diffs.append(ThirteenFDiff(
                cik=cik,
                cusip=cusip,
                issuer_name=issuer,
                quarter_from=quarter_from.isoformat(),
                quarter_to=quarter_to.isoformat(),
                shares_before=shares_before,
                shares_after=shares_after,
                shares_delta=shares_delta,
                value_before=value_before,
                value_after=value_after,
                action=action,
                weight_before=round(weight_before, 6) if weight_before is not None else None,
                weight_after=round(weight_after, 6) if weight_after is not None else None,
            ))

        return diffs

    # ── DB Operations ─────────────────────────────────────────────────

    async def _read_holdings_from_db(
        self,
        cik: str,
        quarters: int,
    ) -> list[ThirteenFHolding]:
        """Read holdings from DB, returning up to `quarters` worth.

        Applies a time-bound filter for hypertable chunk pruning:
        quarters * 3 months lookback from today.
        """
        try:
            async with self._db_session_factory() as session:
                # Time-bound for hypertable chunk pruning
                lookback = date.today() - timedelta(days=quarters * 92)
                stmt = (
                    select(Sec13fHoldingModel)
                    .where(
                        Sec13fHoldingModel.cik == cik,
                        Sec13fHoldingModel.report_date >= lookback,
                    )
                    .order_by(Sec13fHoldingModel.report_date.desc())
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

                if not rows:
                    return []

                # Limit to requested quarters
                report_dates = sorted({r.report_date for r in rows}, reverse=True)[:quarters]
                date_set = set(report_dates)

                return [
                    ThirteenFHolding(
                        cik=r.cik,
                        report_date=r.report_date.isoformat(),
                        filing_date=r.filing_date.isoformat(),
                        accession_number=r.accession_number,
                        cusip=r.cusip,
                        issuer_name=r.issuer_name,
                        asset_class=r.asset_class,
                        shares=r.shares,
                        market_value=r.market_value,
                        discretion=r.discretion,
                        voting_sole=r.voting_sole,
                        voting_shared=r.voting_shared,
                        voting_none=r.voting_none,
                        sector=r.sector,
                    )
                    for r in rows
                    if r.report_date in date_set
                ]
        except Exception as exc:
            logger.error("thirteenf_db_read_failed", cik=cik, error=str(exc))
            return []

    async def _read_holdings_for_date(
        self,
        cik: str,
        report_date: date,
    ) -> list[ThirteenFHolding]:
        """Read holdings for a specific report date from DB."""
        try:
            async with self._db_session_factory() as session:
                stmt = (
                    select(Sec13fHoldingModel)
                    .where(
                        Sec13fHoldingModel.cik == cik,
                        Sec13fHoldingModel.report_date == report_date,
                    )
                )
                result = await session.execute(stmt)
                rows = result.scalars().all()

                return [
                    ThirteenFHolding(
                        cik=r.cik,
                        report_date=r.report_date.isoformat(),
                        filing_date=r.filing_date.isoformat(),
                        accession_number=r.accession_number,
                        cusip=r.cusip,
                        issuer_name=r.issuer_name,
                        asset_class=r.asset_class,
                        shares=r.shares,
                        market_value=r.market_value,
                        discretion=r.discretion,
                        voting_sole=r.voting_sole,
                        voting_shared=r.voting_shared,
                        voting_none=r.voting_none,
                        sector=r.sector,
                    )
                    for r in rows
                ]
        except Exception as exc:
            logger.error(
                "thirteenf_db_read_date_failed",
                cik=cik,
                report_date=report_date.isoformat(),
                error=str(exc),
            )
            return []

    async def _upsert_holdings(self, holdings: list[ThirteenFHolding]) -> None:
        """Bulk upsert holdings to sec_13f_holdings. Chunks at 2000."""
        now = datetime.now(UTC)
        rows = [
            {
                "cik": h.cik,
                "report_date": date.fromisoformat(h.report_date),
                "filing_date": date.fromisoformat(h.filing_date),
                "accession_number": h.accession_number,
                "cusip": h.cusip,
                "issuer_name": h.issuer_name,
                "asset_class": h.asset_class,
                "shares": h.shares,
                "market_value": h.market_value,
                "discretion": h.discretion,
                "voting_sole": h.voting_sole,
                "voting_shared": h.voting_shared,
                "voting_none": h.voting_none,
                "sector": h.sector,
                "data_fetched_at": now,
            }
            for h in holdings
        ]

        async with self._db_session_factory() as session, session.begin():
            for i in range(0, len(rows), _CHUNK_SIZE):
                chunk = rows[i : i + _CHUNK_SIZE]
                stmt = pg_insert(Sec13fHoldingModel).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["cik", "report_date", "cusip"],
                    set_={
                        "issuer_name": stmt.excluded.issuer_name,
                        "asset_class": stmt.excluded.asset_class,
                        "shares": stmt.excluded.shares,
                        "market_value": stmt.excluded.market_value,
                        "discretion": stmt.excluded.discretion,
                        "voting_sole": stmt.excluded.voting_sole,
                        "voting_shared": stmt.excluded.voting_shared,
                        "voting_none": stmt.excluded.voting_none,
                        # sector intentionally excluded: re-ingestion must not
                        # overwrite enriched sectors with NULL from parsed data.
                        # Sectors are backfilled by enrich_holdings_with_sectors().
                        "data_fetched_at": stmt.excluded.data_fetched_at,
                    },
                    where=(
                        Sec13fHoldingModel.data_fetched_at < stmt.excluded.data_fetched_at
                    ),
                )
                await session.execute(stmt)

    async def _upsert_diffs(self, diffs: list[ThirteenFDiff]) -> None:
        """Bulk upsert diffs to sec_13f_diffs. Separate transaction."""
        rows = [
            {
                "cik": d.cik,
                "cusip": d.cusip,
                "issuer_name": d.issuer_name,
                "quarter_from": date.fromisoformat(d.quarter_from),
                "quarter_to": date.fromisoformat(d.quarter_to),
                "shares_before": d.shares_before,
                "shares_after": d.shares_after,
                "shares_delta": d.shares_delta,
                "value_before": d.value_before,
                "value_after": d.value_after,
                "action": d.action,
                "weight_before": d.weight_before,
                "weight_after": d.weight_after,
            }
            for d in diffs
        ]

        async with self._db_session_factory() as session, session.begin():
            for i in range(0, len(rows), _CHUNK_SIZE):
                chunk = rows[i : i + _CHUNK_SIZE]
                stmt = pg_insert(Sec13fDiffModel).values(chunk)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["cik", "cusip", "quarter_from", "quarter_to"],
                    set_={
                        "issuer_name": stmt.excluded.issuer_name,
                        "shares_before": stmt.excluded.shares_before,
                        "shares_after": stmt.excluded.shares_after,
                        "shares_delta": stmt.excluded.shares_delta,
                        "value_before": stmt.excluded.value_before,
                        "value_after": stmt.excluded.value_after,
                        "action": stmt.excluded.action,
                        "weight_before": stmt.excluded.weight_before,
                        "weight_after": stmt.excluded.weight_after,
                    },
                )
                await session.execute(stmt)

    # ── Staleness ───────────────────────────────────────────────────

    @staticmethod
    def _is_stale(
        holdings: list[ThirteenFHolding],
        ttl_days: int,
    ) -> bool:
        """Check if cached holdings exceed the staleness TTL.

        Uses the most recent report_date as the reference point.
        13F filings are quarterly — 45 day TTL is appropriate default.
        """
        if not holdings:
            return True

        most_recent = max(h.report_date for h in holdings)
        try:
            latest = date.fromisoformat(most_recent)
        except (ValueError, TypeError):
            return True

        age_days = (date.today() - latest).days
        return age_days > ttl_days


def _safe_int(val: Any) -> int | None:
    """Parse integer, returning None on failure."""
    if val is None:
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None

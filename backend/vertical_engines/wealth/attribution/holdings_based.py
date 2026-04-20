"""Holdings-based attribution rail — reads `mv_nport_sector_attribution`.

PR-Q4 (G3 Fase 2) scope: fund-side sector weights + AUM coverage +
confidence score. Does NOT compute Brinson-Fachler allocation/selection/
interaction — that requires benchmark holdings and lands in PR-Q5.

The request uses ``fund_instrument_id`` (UUID on ``instruments_org``) but
N-PORT holdings key on ``cik``. The bridge is
``instruments_universe.attributes->>'sec_cik'`` (see CLAUDE.md).

Degradation cases:
    - No filing within ``max_age_months`` → ``no_filing`` / ``stale_filing``
    - AUM coverage < ``min_coverage`` → ``low_aum_coverage``
    - Matview older than ``max_matview_staleness_days`` → warning + best-effort

Returns ``None`` when the fund has no CIK at all (e.g. private/UCITS); the
dispatcher then falls through to the returns-based rail.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text

from vertical_engines.wealth.attribution.models import (
    AttributionRequest,
    HoldingsBasedResult,
    SectorWeight,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# Per PR-Q4 acceptance: N-PORT filings within 9 months of asof count as
# fresh. N-PORT is monthly-reported but filed quarterly with 60-day lag.
DEFAULT_MAX_FILING_AGE_MONTHS = 9
DEFAULT_MIN_COVERAGE = 0.80
# Matview is refreshed weekly by nport_ingestion. >10 days = warning only.
MATVIEW_STALENESS_WARNING_DAYS = 10
# Top 11 GICS sectors is the expected UI rendering cap. We keep more for
# the raw result (DD may want to show issuer_category detail too).
MAX_SECTOR_ROWS = 32


async def resolve_fund_cik(
    db: "AsyncSession", fund_instrument_id: Any,
) -> str | None:
    """Bridge fund_instrument_id → SEC CIK via instruments_universe attributes.

    `sec_nport_holdings.cik` stores 10-digit zero-padded CIKs (EDGAR's
    canonical form). `instruments_universe.attributes->>'sec_cik'` stores
    whatever the ingestion worker wrote — verified in dev DB to be a mix
    of 6-digit unpadded and 10-digit padded. We normalise to 10-digit to
    match the matview key.
    """
    row = (await db.execute(text("""
        SELECT attributes->>'sec_cik' AS cik
        FROM instruments_universe
        WHERE instrument_id = :fid
        LIMIT 1
    """), {"fid": fund_instrument_id})).first()
    if row is None:
        return None
    cik = row[0]
    if not cik:
        return None
    raw = str(cik).strip()
    if not raw.isdigit():
        return None
    return raw.zfill(10)


async def latest_period_for_cik(
    db: "AsyncSession", cik: str, not_before: date,
) -> date | None:
    """Return the latest matview period_of_report for this CIK, or None."""
    row = (await db.execute(text("""
        SELECT MAX(period_of_report)
        FROM mv_nport_sector_attribution
        WHERE filer_cik = :cik
          AND period_of_report >= :not_before
    """), {"cik": cik, "not_before": not_before})).first()
    if row is None:
        return None
    return row[0]


async def fetch_sector_weights(
    db: "AsyncSession", cik: str, period: date,
) -> tuple[list[SectorWeight], float]:
    """Read one matview period and return (sectors, aum_total)."""
    rows = (await db.execute(text("""
        SELECT issuer_category, industry_sector,
               aum_usd, weight, holdings_count
        FROM mv_nport_sector_attribution
        WHERE filer_cik = :cik
          AND period_of_report = :period
        ORDER BY weight DESC
        LIMIT :lim
    """), {"cik": cik, "period": period, "lim": MAX_SECTOR_ROWS})).mappings().all()

    sectors = [
        SectorWeight(
            sector=r["industry_sector"],
            issuer_category=r["issuer_category"],
            weight=float(r["weight"] or 0.0),
            aum_usd=float(r["aum_usd"] or 0.0),
            holdings_count=int(r["holdings_count"] or 0),
        )
        for r in rows
    ]
    aum_total = sum(s.aum_usd for s in sectors)
    return sectors, aum_total


def compute_aum_coverage(sectors: list[SectorWeight]) -> float:
    """Coverage = 1 - unclassified_weight. Bounded to [0, 1]."""
    if not sectors:
        return 0.0
    unclassified = sum(
        s.weight for s in sectors
        if s.sector.strip().lower() in {"unclassified", "unknown", "other"}
    )
    coverage = 1.0 - unclassified
    return max(0.0, min(1.0, coverage))


async def _check_matview_freshness(db: "AsyncSession") -> int | None:
    """Return age (days) of last matview REFRESH, or None if no stats yet."""
    row = (await db.execute(text("""
        SELECT MAX(last_updated_at)
        FROM mv_nport_sector_attribution
    """))).first()
    if row is None or row[0] is None:
        return None
    # last_updated_at is timestamptz; compute day-age vs now UTC.
    from datetime import datetime, timezone
    return (datetime.now(timezone.utc) - row[0]).days


async def run_holdings_rail(
    request: AttributionRequest,
    db: "AsyncSession",
    *,
    max_filing_age_months: int = DEFAULT_MAX_FILING_AGE_MONTHS,
    min_coverage: float = DEFAULT_MIN_COVERAGE,
    cik_resolver: Any = None,
) -> HoldingsBasedResult | None:
    """Execute the holdings rail. Returns ``None`` when the fund has no CIK.

    ``cik_resolver`` (test seam): async callable accepting ``(db, instrument_id)``
    and returning a cik-or-None; defaults to :func:`resolve_fund_cik`.
    """
    resolver = cik_resolver or resolve_fund_cik
    cik = await resolver(db, request.fund_instrument_id)
    if not cik:
        return None

    not_before = request.asof - timedelta(days=int(30.4375 * max_filing_age_months))
    period = await latest_period_for_cik(db, cik, not_before=not_before)

    if period is None:
        # Distinguish "has older filings" from "no filings at all" so the
        # dispatcher can log usefully. Cheap extra query.
        any_row = (await db.execute(text("""
            SELECT 1 FROM mv_nport_sector_attribution
            WHERE filer_cik = :cik LIMIT 1
        """), {"cik": cik})).first()
        reason = "stale_filing" if any_row else "no_filing"
        return HoldingsBasedResult(
            sectors=(),
            period_of_report=None,
            coverage_pct=0.0,
            confidence=0.0,
            holdings_count=0,
            degraded=True,
            degraded_reason=reason,
        )

    sectors, _aum_total = await fetch_sector_weights(db, cik, period)

    if not sectors:
        return HoldingsBasedResult(
            sectors=(),
            period_of_report=period,
            coverage_pct=0.0,
            confidence=0.0,
            holdings_count=0,
            degraded=True,
            degraded_reason="empty_matview_period",
        )

    coverage = compute_aum_coverage(sectors)
    holdings_count = sum(s.holdings_count for s in sectors)

    staleness_days = await _check_matview_freshness(db)
    if staleness_days is not None and staleness_days > MATVIEW_STALENESS_WARNING_DAYS:
        logger.warning(
            "holdings_rail_matview_stale",
            age_days=staleness_days,
            cik=cik,
        )

    if coverage < min_coverage:
        return HoldingsBasedResult(
            sectors=tuple(sectors),
            period_of_report=period,
            coverage_pct=coverage,
            confidence=coverage,
            holdings_count=holdings_count,
            degraded=True,
            degraded_reason="low_aum_coverage",
        )

    return HoldingsBasedResult(
        sectors=tuple(sectors),
        period_of_report=period,
        coverage_pct=coverage,
        confidence=coverage,
        holdings_count=holdings_count,
        degraded=False,
        degraded_reason=None,
    )

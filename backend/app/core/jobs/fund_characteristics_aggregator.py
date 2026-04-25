"""fund_characteristics_aggregator — fund-level Kelly-Pruitt-Su chars from N-PORT x company chars.

Advisory lock : 900_093 (distinct from 900_091 used by company_characteristics_compute)
Frequency     : daily (depends on company_characteristics_monthly being up-to-date)
Idempotent    : yes — ON CONFLICT (instrument_id, as_of) DO UPDATE
Scope         : global (no RLS) — equity_characteristics_monthly is shared

Layer 2 of Option B (issue #289). For each fund's N-PORT report_date,
aggregates the holdings' company-level characteristics using portfolio-
level formulas (numerator/denominator weighted by ownership_fraction =
nport.quantity / company.shares_outstanding).

Three sub-pipelines:

  1. ETF / open-end / closed-end / interval funds -> aggregate via N-PORT
  2. BDCs -> direct XBRL (reuses Q8A-v1 pattern — read fund's own CIK
     from sec_xbrl_facts; bypass N-PORT since BDC holdings are debt)
  3. Skip MMFs and private funds (no N-PORT, no equity exposure)

Momentum (mom_12_1) is computed directly from the fund's own NAV in
nav_timeseries — NOT aggregated from holdings.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import pandas as pd
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory
from app.domains.wealth.services.characteristics_derivation import (
    derive_momentum_12_1,
)

logger = structlog.get_logger()

LOCK_ID = 900_093

# N-PORT asset classes considered equity (for aggregation)
_EQUITY_ASSET_CLASSES = ("EC", "EP")


async def run_fund_characteristics_aggregator(
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Entry point. Acquires advisory lock, aggregates chars, upserts rows."""
    async with async_session_factory() as db:
        acquired = await db.scalar(
            text("SELECT pg_try_advisory_lock(:lock)"), {"lock": LOCK_ID}
        )
        if not acquired:
            logger.info("fund_characteristics_aggregator skip — lock held")
            return {"status": "skipped", "reason": "lock_held"}
        try:
            return await _run(db, limit=limit, dry_run=dry_run)
        finally:
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock)"), {"lock": LOCK_ID}
            )


async def _run(
    db: AsyncSession,
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    funds = await _load_universe(db, limit=limit)
    logger.info("fund_chars_universe_loaded", count=len(funds))

    if not funds:
        return {"status": "succeeded", "funds_processed": 0, "rows_written": 0}

    total_rows = 0
    funds_ok = 0
    funds_err = 0
    funds_skipped = 0

    for fund in funds:
        pipeline = _classify_fund(fund)
        if pipeline == "skip":
            funds_skipped += 1
            continue

        try:
            if pipeline == "bdc_direct":
                rows = await _compute_bdc_direct(db, fund)
            else:
                rows = await _compute_via_aggregation(db, fund)

            if rows and not dry_run:
                written = await _upsert_rows(db, rows)
                total_rows += written
            elif rows:
                total_rows += len(rows)
            funds_ok += 1
        except Exception:
            funds_err += 1
            await db.rollback()
            logger.warning(
                "fund_chars_fund_failed",
                instrument_id=str(fund["instrument_id"]),
                ticker=fund.get("ticker"),
                exc_info=True,
            )

    logger.info(
        "fund_characteristics_aggregator done",
        funds_ok=funds_ok,
        funds_err=funds_err,
        funds_skipped=funds_skipped,
        rows_written=total_rows,
    )
    return {
        "status": "succeeded",
        "funds_processed": funds_ok,
        "funds_skipped": funds_skipped,
        "funds_errors": funds_err,
        "rows_written": total_rows,
    }


async def _load_universe(
    db: AsyncSession, limit: int | None = None,
) -> list[dict[str, Any]]:
    """Load funds eligible for characteristics aggregation.

    Returns instruments that either:
    - Have N-PORT holdings (ETF, mutual fund, closed-end, interval)
    - Are BDCs (direct XBRL path, no N-PORT needed)
    """
    limit_clause = f" LIMIT {int(limit)}" if limit else ""
    result = await db.execute(text(f"""
        SELECT
            i.instrument_id,
            i.ticker,
            i.asset_class,
            i.attributes->>'sec_cik' AS sec_cik,
            CASE
                WHEN EXISTS (
                    SELECT 1 FROM sec_bdcs b
                    WHERE b.cik::text = i.attributes->>'sec_cik'
                ) THEN 'bdc'
                WHEN EXISTS (
                    SELECT 1 FROM sec_money_market_funds m
                    WHERE m.cik::text = i.attributes->>'sec_cik'
                ) THEN 'mmf'
                ELSE 'standard'
            END AS fund_category
        FROM instruments_universe i
        WHERE i.attributes->>'sec_cik' IS NOT NULL
          AND (
              EXISTS (
                  SELECT 1 FROM sec_nport_holdings n
                  WHERE n.cik = i.attributes->>'sec_cik'
              )
              OR EXISTS (
                  SELECT 1 FROM sec_bdcs b
                  WHERE b.cik::text = i.attributes->>'sec_cik'
              )
          )
        ORDER BY i.ticker NULLS LAST
        {limit_clause}
    """))
    return [
        {
            "instrument_id": r.instrument_id,
            "ticker": r.ticker,
            "asset_class": r.asset_class,
            "sec_cik": r.sec_cik,
            "fund_category": r.fund_category,
        }
        for r in result.all()
    ]


def _classify_fund(fund: dict[str, Any]) -> str:
    """Returns 'aggregate', 'bdc_direct', or 'skip'."""
    cat = fund.get("fund_category", "standard")
    if cat == "mmf":
        return "skip"
    if cat == "bdc":
        return "bdc_direct"
    return "aggregate"


async def _compute_via_aggregation(
    db: AsyncSession, fund: dict[str, Any],
) -> list[dict[str, Any]]:
    """Aggregate company chars over N-PORT equity holdings for one fund."""
    sec_cik = fund["sec_cik"]
    instrument_id = fund["instrument_id"]
    ticker = fund.get("ticker") or ""

    # Get all distinct N-PORT report dates for this fund
    report_dates_result = await db.execute(text("""
        SELECT DISTINCT report_date
        FROM sec_nport_holdings
        WHERE cik = :cik
        ORDER BY report_date
    """), {"cik": sec_cik})
    report_dates = [r.report_date for r in report_dates_result.all()]

    if not report_dates:
        return []

    # Load fund's NAV series for momentum calculation
    nav_series = await _load_nav_series(db, instrument_id)

    rows: list[dict[str, Any]] = []

    for report_date in report_dates:
        row = await _aggregate_one_date(
            db, instrument_id, ticker, sec_cik, report_date, nav_series,
        )
        if row is not None:
            rows.append(row)

    return rows


async def _aggregate_one_date(
    db: AsyncSession,
    instrument_id: Any,
    ticker: str,
    fund_cik: str,
    report_date: date,
    nav_series: pd.Series,
) -> dict[str, Any] | None:
    """Aggregate holdings for one (fund, report_date) into fund-level chars.

    Join chain: sec_nport_holdings -> sec_cusip_ticker_map -> company_characteristics_monthly.
    Uses portfolio-level ratios (sum numerator / sum denominator), not weighted mean of ratios.
    """
    # Fetch resolved holdings: N-PORT equity holdings with company chars
    result = await db.execute(text("""
        SELECT
            n.cusip,
            n.market_value,
            n.quantity,
            c.book_equity,
            c.total_assets,
            c.net_income_ttm,
            c.revenue,
            c.gross_profit,
            c.capex_ttm,
            c.ppe_prior,
            c.shares_outstanding,
            c.source_filing_date
        FROM sec_nport_holdings n
        JOIN sec_cusip_ticker_map m ON m.cusip = n.cusip
        JOIN LATERAL (
            SELECT book_equity, total_assets, net_income_ttm, revenue,
                   gross_profit, capex_ttm, ppe_prior, shares_outstanding,
                   source_filing_date
            FROM company_characteristics_monthly
            WHERE cik = m.issuer_cik::bigint
              AND period_end <= :report_date
            ORDER BY period_end DESC
            LIMIT 1
        ) c ON true
        WHERE n.cik = :fund_cik
          AND n.report_date = :report_date
          AND n.asset_class IN ('EC', 'EP')
          AND m.issuer_cik IS NOT NULL
          AND n.market_value IS NOT NULL
          AND n.market_value > 0
    """), {
        "fund_cik": fund_cik,
        "report_date": report_date,
    })
    holdings = result.all()

    if not holdings:
        return None

    # Accumulate portfolio-level numerators and denominators
    sum_market_value = 0.0
    sum_book_equity = 0.0
    sum_total_assets = 0.0
    sum_net_income_ttm = 0.0
    sum_revenue = 0.0
    sum_gross_profit = 0.0
    sum_capex_ttm = 0.0
    sum_ppe_prior = 0.0
    resolved_count = 0
    latest_filing_date = None

    for h in holdings:
        mv = float(h.market_value)
        quantity = float(h.quantity) if h.quantity is not None else None
        shares_out = float(h.shares_outstanding) if h.shares_outstanding is not None else None

        # Compute ownership fraction
        if quantity is not None and shares_out is not None and shares_out > 0:
            ownership_frac = quantity / shares_out
        else:
            # Fallback: skip this holding from ratio aggregation but still
            # count its market_value for size_log_mkt_cap
            sum_market_value += mv
            continue

        sum_market_value += mv

        # Scale company-level values by ownership fraction
        if h.book_equity is not None:
            sum_book_equity += float(h.book_equity) * ownership_frac
        if h.total_assets is not None:
            sum_total_assets += float(h.total_assets) * ownership_frac
        if h.net_income_ttm is not None:
            sum_net_income_ttm += float(h.net_income_ttm) * ownership_frac
        if h.revenue is not None:
            sum_revenue += float(h.revenue) * ownership_frac
        if h.gross_profit is not None:
            sum_gross_profit += float(h.gross_profit) * ownership_frac
        if h.capex_ttm is not None:
            sum_capex_ttm += float(h.capex_ttm) * ownership_frac
        if h.ppe_prior is not None:
            sum_ppe_prior += float(h.ppe_prior) * ownership_frac

        resolved_count += 1

        if h.source_filing_date is not None:
            if latest_filing_date is None or h.source_filing_date > latest_filing_date:
                latest_filing_date = h.source_filing_date

    if resolved_count == 0:
        return None

    # Compute fund-level characteristics
    size_log_mkt_cap = math.log(sum_market_value) if sum_market_value > 0 else None

    book_to_market = (
        sum_book_equity / sum_market_value
        if sum_market_value > 0
        else None
    )

    quality_roa = (
        sum_net_income_ttm / sum_total_assets
        if sum_total_assets > 0
        else None
    )

    investment_growth = (
        sum_capex_ttm / sum_ppe_prior
        if sum_ppe_prior > 0
        else None
    )

    profitability_gross = (
        sum_gross_profit / sum_revenue
        if sum_revenue > 0
        else None
    )

    # Momentum from fund's own NAV (not aggregated from holdings)
    mom_12_1 = derive_momentum_12_1(nav_series, report_date)

    # Clamp ratios to catch data quality issues
    book_to_market = _clamp(book_to_market, 50.0)
    quality_roa = _clamp(quality_roa, 10.0)
    investment_growth = _clamp(investment_growth, 100.0)
    profitability_gross = _clamp(profitability_gross, 10.0)

    return {
        "instrument_id": instrument_id,
        "ticker": ticker,
        "as_of": report_date,
        "size_log_mkt_cap": _round4(size_log_mkt_cap),
        "book_to_market": _round4(book_to_market),
        "mom_12_1": _round4(mom_12_1),
        "quality_roa": _round4(quality_roa),
        "investment_growth": _round4(investment_growth),
        "profitability_gross": _round4(profitability_gross),
        "source_filing_date": latest_filing_date,
    }


async def _compute_bdc_direct(
    db: AsyncSession, fund: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compute characteristics for a BDC using its own XBRL filings.

    BDCs file 10-K/10-Q with standard us-gaap concepts. Their N-PORT
    holdings are debt instruments, not equity — so we read the BDC's
    own financial statements directly from company_characteristics_monthly
    (if populated by the Layer 1 worker for this CIK).
    """
    sec_cik = fund["sec_cik"]
    instrument_id = fund["instrument_id"]
    ticker = fund.get("ticker") or ""

    # Try to cast sec_cik to bigint for company_characteristics_monthly lookup
    try:
        cik_int = int(sec_cik)
    except (ValueError, TypeError):
        return []

    result = await db.execute(text("""
        SELECT period_end, book_equity, total_assets, net_income_ttm,
               revenue, gross_profit, capex_ttm, ppe_prior,
               quality_roa, investment_growth, profitability_gross,
               source_filing_date
        FROM company_characteristics_monthly
        WHERE cik = :cik
        ORDER BY period_end
    """), {"cik": cik_int})
    company_rows = result.all()

    if not company_rows:
        return []

    # Load fund's NAV series for momentum
    nav_series = await _load_nav_series(db, instrument_id)

    rows: list[dict[str, Any]] = []
    for cr in company_rows:
        mom_12_1 = derive_momentum_12_1(nav_series, cr.period_end)

        # For BDCs, size_log_mkt_cap is not directly available from XBRL.
        # We approximate from total_assets (BDCs report at fair value).
        size_log = (
            math.log(float(cr.total_assets))
            if cr.total_assets is not None and float(cr.total_assets) > 0
            else None
        )
        book_to_market = (
            float(cr.book_equity) / float(cr.total_assets)
            if cr.book_equity is not None
            and cr.total_assets is not None
            and float(cr.total_assets) > 0
            else None
        )

        rows.append({
            "instrument_id": instrument_id,
            "ticker": ticker,
            "as_of": cr.period_end,
            "size_log_mkt_cap": _round4(size_log),
            "book_to_market": _round4(_clamp(book_to_market, 50.0)),
            "mom_12_1": _round4(mom_12_1),
            "quality_roa": _round4(_clamp(
                float(cr.quality_roa) if cr.quality_roa is not None else None, 10.0
            )),
            "investment_growth": _round4(_clamp(
                float(cr.investment_growth) if cr.investment_growth is not None else None, 100.0
            )),
            "profitability_gross": _round4(_clamp(
                float(cr.profitability_gross) if cr.profitability_gross is not None else None, 10.0
            )),
            "source_filing_date": cr.source_filing_date,
        })

    return rows


async def _load_nav_series(
    db: AsyncSession, instrument_id: Any,
) -> pd.Series:
    """Load NAV time-series for an instrument as a DatetimeIndex pandas Series."""
    result = await db.execute(text("""
        SELECT nav_date, nav
        FROM nav_timeseries
        WHERE instrument_id = :iid
          AND nav IS NOT NULL
        ORDER BY nav_date
    """), {"iid": instrument_id})
    rows = result.all()

    if not rows:
        return pd.Series(dtype=float)

    dates = [r.nav_date for r in rows]
    values = [float(r.nav) for r in rows]
    return pd.Series(values, index=pd.DatetimeIndex(dates))


def _clamp(val: float | None, bound: float) -> float | None:
    """Clamp to [-bound, +bound]. Returns None for absurd values."""
    if val is None:
        return None
    if val > bound or val < -bound:
        return None
    return val


def _round4(val: float | None) -> float | None:
    """Round to 4 decimal places for NUMERIC(10,4) columns."""
    if val is None:
        return None
    return round(val, 4)


_UPSERT_SQL = """
    INSERT INTO equity_characteristics_monthly (
        instrument_id, ticker, as_of,
        size_log_mkt_cap, book_to_market, mom_12_1,
        quality_roa, investment_growth, profitability_gross,
        source_filing_date, computed_at
    ) VALUES (
        :instrument_id, :ticker, :as_of,
        :size_log_mkt_cap, :book_to_market, :mom_12_1,
        :quality_roa, :investment_growth, :profitability_gross,
        :source_filing_date, now()
    )
    ON CONFLICT (instrument_id, as_of) DO UPDATE SET
        ticker = EXCLUDED.ticker,
        size_log_mkt_cap = EXCLUDED.size_log_mkt_cap,
        book_to_market = EXCLUDED.book_to_market,
        mom_12_1 = EXCLUDED.mom_12_1,
        quality_roa = EXCLUDED.quality_roa,
        investment_growth = EXCLUDED.investment_growth,
        profitability_gross = EXCLUDED.profitability_gross,
        source_filing_date = EXCLUDED.source_filing_date,
        computed_at = now()
"""


async def _upsert_rows(db: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Batch upsert rows. Returns count written."""
    if not rows:
        return 0
    stmt = text(_UPSERT_SQL)
    for row in rows:
        await db.execute(stmt, row)
    await db.commit()
    return len(rows)

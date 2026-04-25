"""equity_characteristics_compute — 6 Kelly-Pruitt-Su chars from XBRL × nav.

Advisory lock : 900_091
Frequency     : daily — market_cap depends on end-of-month NAV (daily
                refresh keeps the latest month fresh), fundamentals come
                from quarterly XBRL filings so non-market-cap chars only
                change monthly at most.
Idempotent    : yes — ON CONFLICT (instrument_id, as_of) DO UPDATE.
Scope         : global (no RLS) — equity_characteristics_monthly is a
                shared analytical table.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

import pandas as pd
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory
from app.domains.wealth.services.characteristics_derivation import (
    derive_book_to_market,
    derive_investment_growth,
    derive_momentum_12_1,
    derive_profitability_gross,
    derive_quality_roa,
    derive_size,
)

logger = structlog.get_logger()

LOCK_ID = 900_091

# XBRL concepts needed from sec_xbrl_facts (us-gaap taxonomy, USD unit)
_USGAAP_CONCEPTS = [
    "StockholdersEquity",
    "Assets",
    "NetIncomeLoss",
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "CostOfRevenue",
    "CostOfGoodsAndServicesSold",
    "GrossProfit",
]

# dei taxonomy, shares unit
_DEI_CONCEPT = "EntityCommonStockSharesOutstanding"


async def run_equity_characteristics_compute(
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Entry point. Acquires advisory lock, computes chars, upserts rows."""
    async with async_session_factory() as db:
        acquired = await db.scalar(
            text("SELECT pg_try_advisory_lock(:lock)"), {"lock": LOCK_ID}
        )
        if not acquired:
            logger.info("equity_characteristics_compute skip — lock held")
            return {"status": "skipped", "reason": "lock_held"}
        try:
            universe = await _load_universe(db, limit=limit)
            logger.info(
                "equity_chars_universe_loaded", count=len(universe)
            )
            if not universe:
                return {"status": "succeeded", "instruments_processed": 0, "rows_written": 0}

            total_rows = 0
            instruments_ok = 0
            instruments_err = 0

            for instrument_id, cik, ticker in universe:
                try:
                    rows = await _compute_instrument(db, instrument_id, cik, ticker)
                    if rows and not dry_run:
                        written = await _upsert_rows(db, rows)
                        total_rows += written
                    elif rows:
                        total_rows += len(rows)
                    instruments_ok += 1
                except Exception:
                    instruments_err += 1
                    await db.rollback()
                    logger.warning(
                        "equity_chars_instrument_failed",
                        instrument_id=str(instrument_id),
                        cik=cik,
                        exc_info=True,
                    )

            logger.info(
                "equity_characteristics_compute done",
                instruments_ok=instruments_ok,
                instruments_err=instruments_err,
                rows_written=total_rows,
            )
            return {
                "status": "succeeded",
                "instruments_processed": instruments_ok,
                "instruments_errors": instruments_err,
                "rows_written": total_rows,
            }
        finally:
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock)"), {"lock": LOCK_ID}
            )


async def _load_universe(
    db: AsyncSession, limit: int | None = None
) -> list[tuple[UUID, int, str]]:
    """Return (instrument_id, cik, ticker) for eligible instruments."""
    sql = """
        SELECT i.instrument_id,
               (i.attributes->>'sec_cik')::BIGINT AS cik,
               i.ticker
        FROM instruments_universe i
        WHERE i.attributes->>'sec_cik' IS NOT NULL
          AND i.ticker IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM nav_timeseries n
              WHERE n.instrument_id = i.instrument_id
          )
        ORDER BY i.ticker
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    result = await db.execute(text(sql))
    return [(r.instrument_id, r.cik, r.ticker) for r in result.all()]


async def _fetch_fundamentals(
    db: AsyncSession, cik: int
) -> dict[date, dict[str, Any]]:
    """Fetch deduped XBRL fundamentals for one CIK. Latest filing wins."""
    # Concepts are safe constants — inline them to avoid expanding-bindparam
    # issues with asyncpg.
    concepts_sql = ", ".join(f"'{c}'" for c in _USGAAP_CONCEPTS)
    sql = f"""
        SELECT DISTINCT ON (cik, concept, period_end)
               concept, period_end, val, filed
        FROM sec_xbrl_facts
        WHERE cik = :cik
          AND taxonomy = 'us-gaap'
          AND unit = 'USD'
          AND concept IN ({concepts_sql})
          AND val IS NOT NULL
        ORDER BY cik, concept, period_end, filed DESC
    """
    result = await db.execute(text(sql), {"cik": cik})
    rows = result.all()

    # Group by period_end → {concept: val}
    by_period: dict[date, dict[str, Any]] = {}
    for r in rows:
        period_end = r.period_end
        if period_end not in by_period:
            by_period[period_end] = {"filed": r.filed}
        entry = by_period[period_end]
        entry[r.concept] = float(r.val)
        # Track latest filed across all concepts for audit
        if r.filed and (entry["filed"] is None or r.filed > entry["filed"]):
            entry["filed"] = r.filed

    # Apply revenue/cost fallbacks per period
    for entry in by_period.values():
        if "Revenues" not in entry and "RevenueFromContractWithCustomerExcludingAssessedTax" in entry:
            entry["Revenues"] = entry["RevenueFromContractWithCustomerExcludingAssessedTax"]
        if "CostOfRevenue" not in entry and "CostOfGoodsAndServicesSold" in entry:
            entry["CostOfRevenue"] = entry["CostOfGoodsAndServicesSold"]

    return by_period


async def _fetch_shares_outstanding(
    db: AsyncSession, cik: int
) -> dict[date, float]:
    """Monthly shares outstanding from dei.EntityCommonStockSharesOutstanding."""
    sql = """
        SELECT DISTINCT ON (cik, period_end)
               period_end, val
        FROM sec_xbrl_facts
        WHERE cik = :cik
          AND taxonomy = 'dei'
          AND concept = :concept
          AND unit = 'shares'
          AND val IS NOT NULL
          AND val > 0
        ORDER BY cik, period_end, filed DESC
    """
    result = await db.execute(text(sql), {"cik": cik, "concept": _DEI_CONCEPT})
    return {r.period_end: float(r.val) for r in result.all()}


async def _fetch_nav_monthly(
    db: AsyncSession, instrument_id: UUID
) -> pd.Series:
    """Month-end NAV series for one instrument. Index=date, values=nav."""
    sql = """
        SELECT DISTINCT ON (date_trunc('month', nav_date))
               nav_date::date AS nav_date, nav
        FROM nav_timeseries
        WHERE instrument_id = :iid
          AND nav IS NOT NULL
        ORDER BY date_trunc('month', nav_date), nav_date DESC
    """
    result = await db.execute(text(sql), {"iid": instrument_id})
    rows = result.all()
    if not rows:
        return pd.Series(dtype=float)
    dates = [r.nav_date for r in rows]
    vals = [float(r.nav) for r in rows]
    return pd.Series(vals, index=pd.DatetimeIndex(dates)).sort_index()


async def _compute_instrument(
    db: AsyncSession,
    instrument_id: UUID,
    cik: int,
    ticker: str,
) -> list[dict[str, Any]]:
    """Compute all characteristics for one instrument across all available months."""
    fundamentals = await _fetch_fundamentals(db, cik)
    shares = await _fetch_shares_outstanding(db, cik)
    nav_series = await _fetch_nav_monthly(db, instrument_id)

    if not fundamentals or nav_series.empty:
        return []

    # Build month-end dates from fundamentals (quarterly XBRL → monthly characteristics)
    # We iterate over months where we have NAV data (the more frequent source)
    # and look up the most recent fundamental data as of that month.
    sorted_fund_dates = sorted(fundamentals.keys())
    rows: list[dict[str, Any]] = []

    for nav_date in nav_series.index:
        as_of = nav_date.date() if hasattr(nav_date, "date") else nav_date

        # Find the most recent fundamental data as-of this month
        fund_data = _latest_as_of(sorted_fund_dates, fundamentals, as_of)
        if fund_data is None:
            continue

        # Market cap: shares × price (month-end NAV)
        price = float(nav_series.loc[nav_date])
        shares_eom = _latest_shares(shares, as_of)
        market_cap = price * shares_eom if shares_eom else None

        # Total assets for investment growth (need current and YoY)
        total_assets_now = fund_data.get("Assets")
        total_assets_yoy = _yoy_value(sorted_fund_dates, fundamentals, as_of, "Assets")

        row = {
            "instrument_id": instrument_id,
            "ticker": ticker,
            "as_of": as_of,
            "size_log_mkt_cap": derive_size(market_cap),
            "book_to_market": derive_book_to_market(
                fund_data.get("StockholdersEquity"), market_cap
            ),
            "mom_12_1": derive_momentum_12_1(nav_series, as_of),
            "quality_roa": derive_quality_roa(
                fund_data.get("NetIncomeLoss"), total_assets_now
            ),
            "investment_growth": derive_investment_growth(
                total_assets_now, total_assets_yoy
            ),
            "profitability_gross": derive_profitability_gross(
                fund_data.get("GrossProfit"),
                fund_data.get("Revenues"),
                fund_data.get("CostOfRevenue"),
            ),
            "source_filing_date": fund_data.get("filed"),
        }
        rows.append(row)

    return rows


def _latest_as_of(
    sorted_dates: list[date],
    data: dict[date, dict],
    as_of: date,
) -> dict | None:
    """Find the most recent fundamental entry on or before as_of."""
    best = None
    for d in sorted_dates:
        if d <= as_of:
            best = d
        else:
            break
    return data.get(best) if best else None


def _latest_shares(shares: dict[date, float], as_of: date) -> float | None:
    """Find the most recent shares outstanding on or before as_of."""
    best_val = None
    for d in sorted(shares.keys()):
        if d <= as_of:
            best_val = shares[d]
        else:
            break
    return best_val


def _yoy_value(
    sorted_dates: list[date],
    data: dict[date, dict],
    as_of: date,
    concept: str,
) -> float | None:
    """Find the value of `concept` from ~12 months ago (year-over-year)."""
    from dateutil.relativedelta import relativedelta

    target = as_of - relativedelta(years=1)
    best = None
    for d in sorted_dates:
        if d <= target:
            best = d
        else:
            break
    if best and concept in data[best]:
        return data[best][concept]
    return None


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

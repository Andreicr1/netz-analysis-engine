"""company_characteristics_compute — stock-level fundamentals chars from XBRL.

Advisory lock : 900_091
Frequency     : daily
Idempotent    : yes — ON CONFLICT (cik, period_end) DO UPDATE
Scope         : global (no RLS)

Layer 1 of the 2-layer Option B pipeline (issue #289). Computes 3
fundamentals-only Kelly-Pruitt-Su characteristics + 8 raw components
per CIK per fiscal period. Layer 2 (PR-Q8A-v3) aggregates these via
N-PORT holdings to produce fund-level chars.

Price-dependent chars (size_log_mkt_cap, book_to_market, mom_12_1)
are NOT computed here — they are computed at the fund layer using
N-PORT.value_usd as the market weight + the fund's own NAV series.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory
from app.domains.wealth.services.characteristics_derivation import (
    derive_investment_growth,
    derive_profitability_gross,
    derive_quality_roa,
)

logger = structlog.get_logger()

LOCK_ID = 900_091

# XBRL concepts needed from sec_xbrl_facts
_USGAAP_CONCEPTS = [
    "StockholdersEquity",
    "Assets",
    "NetIncomeLoss",
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "CostOfRevenue",
    "CostOfGoodsAndServicesSold",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "PropertyPlantAndEquipmentNet",
]

_DEI_CONCEPT = "EntityCommonStockSharesOutstanding"

# Quarterly fiscal periods for TTM aggregation
_QUARTERLY_FPS = {"Q1", "Q2", "Q3", "Q4"}


async def run_company_characteristics_compute(
    limit: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Entry point. Acquires advisory lock, computes chars, upserts rows."""
    async with async_session_factory() as db:
        acquired = await db.scalar(
            text("SELECT pg_try_advisory_lock(:lock)"), {"lock": LOCK_ID}
        )
        if not acquired:
            logger.info("company_characteristics_compute skip — lock held")
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
    # Get distinct CIKs that have us-gaap filings
    limit_clause = f" LIMIT {int(limit)}" if limit else ""
    result = await db.execute(text(
        "SELECT DISTINCT cik FROM sec_xbrl_facts "
        f"WHERE taxonomy = 'us-gaap'{limit_clause}"
    ))
    ciks = [r.cik for r in result.all()]
    logger.info("company_chars_ciks_loaded", count=len(ciks))

    if not ciks:
        return {"status": "succeeded", "ciks_processed": 0, "rows_written": 0}

    total_rows = 0
    ciks_ok = 0
    ciks_err = 0

    for cik in ciks:
        try:
            rows = await _compute_cik(db, cik)
            if rows and not dry_run:
                written = await _upsert_rows(db, rows)
                total_rows += written
            elif rows:
                total_rows += len(rows)
            ciks_ok += 1
        except Exception:
            ciks_err += 1
            await db.rollback()
            logger.warning(
                "company_chars_cik_failed",
                cik=cik,
                exc_info=True,
            )

    logger.info(
        "company_characteristics_compute done",
        ciks_ok=ciks_ok,
        ciks_err=ciks_err,
        rows_written=total_rows,
    )
    return {
        "status": "succeeded",
        "ciks_processed": ciks_ok,
        "ciks_errors": ciks_err,
        "rows_written": total_rows,
    }


async def _compute_cik(
    db: AsyncSession,
    cik: int,
) -> list[dict[str, Any]]:
    """Compute all characteristics for one CIK across all available periods."""
    fundamentals = await _fetch_fundamentals(db, cik)
    shares = await _fetch_shares_outstanding(db, cik)

    if not fundamentals:
        return []

    sorted_dates = sorted(fundamentals.keys())
    rows: list[dict[str, Any]] = []

    for period_end in sorted_dates:
        entry = fundamentals[period_end]

        # Revenue fallback
        revenue = entry.get("Revenues") or entry.get(
            "RevenueFromContractWithCustomerExcludingAssessedTax"
        )
        # Cost of revenue fallback
        cost_of_rev = entry.get("CostOfRevenue") or entry.get(
            "CostOfGoodsAndServicesSold"
        )
        gross_profit = (revenue - cost_of_rev) if (revenue is not None and cost_of_rev is not None) else None

        total_assets = entry.get("Assets")
        book_equity = entry.get("StockholdersEquity")
        shares_eom = _latest_value_as_of(shares, period_end)

        # TTM: net_income
        net_income_ttm = _compute_ttm(
            sorted_dates, fundamentals, period_end, "NetIncomeLoss"
        )
        # TTM: capex
        capex_ttm = _compute_ttm(
            sorted_dates, fundamentals, period_end,
            "PaymentsToAcquirePropertyPlantAndEquipment",
        )
        # PPE prior (year-ago)
        ppe_prior = _yoy_value(
            sorted_dates, fundamentals, period_end,
            "PropertyPlantAndEquipmentNet",
        )

        # YoY total assets for investment_growth
        total_assets_yoy = _yoy_value(
            sorted_dates, fundamentals, period_end, "Assets"
        )

        # Derived chars (clamped — XBRL data quality issues can produce absurd ratios)
        quality_roa = _clamp_ratio(derive_quality_roa(net_income_ttm, total_assets))
        investment_growth = _clamp_ratio(derive_investment_growth(total_assets, total_assets_yoy))
        profitability_gross = _clamp_ratio(derive_profitability_gross(gross_profit, revenue, cost_of_rev))

        rows.append({
            "cik": cik,
            "period_end": period_end,
            "fp": entry.get("fp"),
            "book_equity": book_equity,
            "total_assets": total_assets,
            "net_income_ttm": net_income_ttm,
            "revenue": revenue,
            "cost_of_revenue": cost_of_rev,
            "gross_profit": gross_profit,
            "capex_ttm": capex_ttm,
            "ppe_prior": ppe_prior,
            "shares_outstanding": shares_eom,
            "quality_roa": quality_roa,
            "investment_growth": investment_growth,
            "profitability_gross": profitability_gross,
            "source_filing_date": entry.get("filed"),
            "source_accn": entry.get("accn"),
        })

    return rows


async def _fetch_fundamentals(
    db: AsyncSession, cik: int
) -> dict[date, dict[str, Any]]:
    """Fetch deduped XBRL fundamentals for one CIK. Latest filing wins."""
    concepts_sql = ", ".join(f"'{c}'" for c in _USGAAP_CONCEPTS)
    sql = f"""
        SELECT DISTINCT ON (cik, concept, period_end)
               concept, period_end, val, fp, filed, accn
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

    by_period: dict[date, dict[str, Any]] = {}
    for r in rows:
        pe = r.period_end
        if pe not in by_period:
            by_period[pe] = {"filed": r.filed, "accn": r.accn, "fp": r.fp, "_fps": {}}
        entry = by_period[pe]
        entry[r.concept] = float(r.val)
        # Store fp per concept (needed for TTM — XBRL quarterly vals are YTD, not incremental)
        if r.fp:
            entry["_fps"][r.concept] = r.fp
        # Track latest filed + accn for audit
        if r.filed and (entry["filed"] is None or r.filed > entry["filed"]):
            entry["filed"] = r.filed
            entry["accn"] = r.accn
        # Keep fp from the most common observation
        if r.fp:
            entry["fp"] = r.fp

    return by_period


async def _fetch_shares_outstanding(
    db: AsyncSession, cik: int
) -> dict[date, float]:
    """Shares outstanding from dei.EntityCommonStockSharesOutstanding."""
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


def _clamp_ratio(val: float | None, bound: float = 100.0) -> float | None:
    """Clamp derived ratio to [-bound, +bound]. Absurd values indicate XBRL data quality issues."""
    if val is None:
        return None
    if val > bound or val < -bound:
        return None
    return val


def _compute_ttm(
    sorted_dates: list[date],
    data: dict[date, dict],
    as_of: date,
    concept: str,
) -> float | None:
    """Compute trailing-twelve-months value for a flow concept.

    Uses the most recent FY/CY value on or before as_of. XBRL quarterly
    values (Q1/Q2/Q3) are cumulative YTD, NOT incremental — summing them
    would double/triple count. The FY value is the authoritative annual
    figure.
    """
    # Look for the most recent FY/CY value on or before as_of
    # Use concept-level fp (stored in _fps dict) — the period-level fp
    # may come from a different concept and mislead.
    best = None
    for d in sorted_dates:
        if d <= as_of:
            e = data[d]
            concept_fp = e.get("_fps", {}).get(concept)
            if concept_fp in ("FY", "CY") and concept in e:
                best = e[concept]
        else:
            break
    return best


def _yoy_value(
    sorted_dates: list[date],
    data: dict[date, dict],
    as_of: date,
    concept: str,
) -> float | None:
    """Find the value of `concept` from ~12 months ago (year-over-year)."""
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


def _latest_value_as_of(mapping: dict[date, float], as_of: date) -> float | None:
    """Find the most recent value on or before as_of."""
    best_val = None
    for d in sorted(mapping.keys()):
        if d <= as_of:
            best_val = mapping[d]
        else:
            break
    return best_val


_UPSERT_SQL = """
    INSERT INTO company_characteristics_monthly (
        cik, period_end, fp,
        book_equity, total_assets, net_income_ttm, revenue,
        cost_of_revenue, gross_profit, capex_ttm, ppe_prior,
        shares_outstanding,
        quality_roa, investment_growth, profitability_gross,
        source_filing_date, source_accn, computed_at
    ) VALUES (
        :cik, :period_end, :fp,
        :book_equity, :total_assets, :net_income_ttm, :revenue,
        :cost_of_revenue, :gross_profit, :capex_ttm, :ppe_prior,
        :shares_outstanding,
        :quality_roa, :investment_growth, :profitability_gross,
        :source_filing_date, :source_accn, now()
    )
    ON CONFLICT (cik, period_end) DO UPDATE SET
        fp = EXCLUDED.fp,
        book_equity = EXCLUDED.book_equity,
        total_assets = EXCLUDED.total_assets,
        net_income_ttm = EXCLUDED.net_income_ttm,
        revenue = EXCLUDED.revenue,
        cost_of_revenue = EXCLUDED.cost_of_revenue,
        gross_profit = EXCLUDED.gross_profit,
        capex_ttm = EXCLUDED.capex_ttm,
        ppe_prior = EXCLUDED.ppe_prior,
        shares_outstanding = EXCLUDED.shares_outstanding,
        quality_roa = EXCLUDED.quality_roa,
        investment_growth = EXCLUDED.investment_growth,
        profitability_gross = EXCLUDED.profitability_gross,
        source_filing_date = EXCLUDED.source_filing_date,
        source_accn = EXCLUDED.source_accn,
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

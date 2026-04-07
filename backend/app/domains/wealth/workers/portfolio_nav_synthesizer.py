"""Portfolio NAV Synthesizer — daily synthetic NAV for model portfolios.

Reads the current fund_selection_schema (optimized weights) from each
ModelPortfolio, fetches component fund returns from nav_timeseries, and
computes the weighted portfolio NAV series.

Algorithm:
    NAV_0 = inception_nav (default 1000.0)
    R_t   = Σ(w_i × r_i_t)  for each fund i with weight w_i
    NAV_t = NAV_{t-1} × (1 + R_t)

Usage:
    python -m app.domains.wealth.workers.portfolio_nav_synthesizer

Lock ID: 900_030
"""

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.core.tenancy.middleware import set_rls_context
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav
from app.domains.wealth.models.nav import NavTimeseries

logger = structlog.get_logger()

NAV_SYNTH_LOCK_ID = 900_030
# Maximum lookback for historical reconstruction (5 years)
MAX_LOOKBACK_DAYS = 1260


def _extract_weights(fund_selection: dict[str, Any]) -> dict[uuid.UUID, float]:
    """Extract {instrument_id: weight} from fund_selection_schema."""
    funds = fund_selection.get("funds", [])
    return {
        uuid.UUID(f["instrument_id"]): f["weight"]
        for f in funds
        if f.get("instrument_id") and f.get("weight")
    }


async def _get_last_nav(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
) -> tuple[date | None, float | None]:
    """Get the most recent NAV date and value for a portfolio."""
    stmt = (
        select(ModelPortfolioNav.nav_date, ModelPortfolioNav.nav)
        .where(ModelPortfolioNav.portfolio_id == portfolio_id)
        .order_by(ModelPortfolioNav.nav_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.one_or_none()
    if row is None:
        return None, None
    return row.nav_date, float(row.nav)


async def _fetch_fund_returns(
    db: AsyncSession,
    fund_ids: list[uuid.UUID],
    start_date: date,
    end_date: date,
) -> dict[date, dict[uuid.UUID, float]]:
    """Fetch daily returns for funds, organized by date.

    Returns: {date: {instrument_id: return_1d}}
    """
    if not fund_ids:
        return {}

    stmt = (
        select(
            NavTimeseries.nav_date,
            NavTimeseries.instrument_id,
            NavTimeseries.return_1d,
        )
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= end_date,
            NavTimeseries.return_1d.is_not(None),
        )
        .order_by(NavTimeseries.nav_date)
    )
    result = await db.execute(stmt)

    by_date: dict[date, dict[uuid.UUID, float]] = {}
    for row in result.all():
        by_date.setdefault(row.nav_date, {})[row.instrument_id] = float(row.return_1d)

    return by_date


async def synthesize_portfolio_nav(
    db: AsyncSession,
    portfolio: ModelPortfolio,
) -> dict[str, Any]:
    """Synthesize NAV series for a single model portfolio.

    Returns summary dict with dates_computed and final_nav.
    """
    portfolio_id = portfolio.id
    org_id = portfolio.organization_id

    if not portfolio.fund_selection_schema:
        return {"portfolio_id": str(portfolio_id), "status": "no_selection", "dates_computed": 0}

    weights = _extract_weights(portfolio.fund_selection_schema)
    if not weights:
        return {"portfolio_id": str(portfolio_id), "status": "no_weights", "dates_computed": 0}

    fund_ids = list(weights.keys())
    inception_nav = float(portfolio.inception_nav) if portfolio.inception_nav else 1000.0

    # Determine start point
    last_date, last_nav = await _get_last_nav(db, portfolio_id)

    if last_date is not None and last_nav is not None:
        start_date = last_date + timedelta(days=1)
        current_nav = last_nav
    else:
        # Full reconstruction from inception or backtest_start
        resolved_start = portfolio.backtest_start_date or portfolio.inception_date
        start_date = resolved_start if resolved_start is not None else (date.today() - timedelta(days=MAX_LOOKBACK_DAYS))
        current_nav = inception_nav

    end_date = date.today()
    if start_date > end_date:
        return {"portfolio_id": str(portfolio_id), "status": "up_to_date", "dates_computed": 0}

    # Fetch all fund returns in date range
    returns_by_date = await _fetch_fund_returns(db, fund_ids, start_date, end_date)

    if not returns_by_date:
        return {"portfolio_id": str(portfolio_id), "status": "no_fund_data", "dates_computed": 0}

    sorted_dates = sorted(returns_by_date.keys())

    # If this is the first synthesis, insert day-0 row (inception NAV, no return)
    if last_date is None and sorted_dates:
        day0 = sorted_dates[0] - timedelta(days=1)
        day0_stmt = pg_insert(ModelPortfolioNav).values(
            portfolio_id=portfolio_id,
            nav_date=day0,
            nav=Decimal(str(round(inception_nav, 6))),
            daily_return=None,
            organization_id=org_id,
        )
        day0_stmt = day0_stmt.on_conflict_do_nothing(
            index_elements=["portfolio_id", "nav_date"],
        )
        await db.execute(day0_stmt)

    # Compute daily NAV
    rows_to_upsert: list[dict[str, Any]] = []
    weight_sum = sum(weights.values())

    for d in sorted_dates:
        day_returns = returns_by_date[d]

        # Weighted return: Σ(w_i × r_i) / Σ(w_i) — normalize for missing funds
        portfolio_return = 0.0
        active_weight = 0.0
        for fid, w in weights.items():
            r = day_returns.get(fid)
            if r is not None:
                portfolio_return += w * r
                active_weight += w

        # Renormalize if some funds are missing for this day
        if active_weight > 0 and active_weight < weight_sum * 0.999:
            portfolio_return = portfolio_return * (weight_sum / active_weight)

        current_nav = current_nav * (1.0 + portfolio_return)

        rows_to_upsert.append({
            "portfolio_id": portfolio_id,
            "nav_date": d,
            "nav": Decimal(str(round(current_nav, 6))),
            "daily_return": Decimal(str(round(portfolio_return, 8))),
            "organization_id": org_id,
        })

    # Batch upsert — 500 rows at a time
    batch_size = 500
    for i in range(0, len(rows_to_upsert), batch_size):
        batch = rows_to_upsert[i : i + batch_size]
        stmt = pg_insert(ModelPortfolioNav).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["portfolio_id", "nav_date"],
            set_={
                "nav": stmt.excluded.nav,
                "daily_return": stmt.excluded.daily_return,
            },
        )
        await db.execute(stmt)

    await db.commit()

    logger.info(
        "portfolio_nav_synthesized",
        portfolio_id=str(portfolio_id),
        dates_computed=len(rows_to_upsert),
        final_nav=round(current_nav, 4),
        start=str(sorted_dates[0]) if sorted_dates else None,
        end=str(sorted_dates[-1]) if sorted_dates else None,
    )

    return {
        "portfolio_id": str(portfolio_id),
        "status": "ok",
        "dates_computed": len(rows_to_upsert),
        "final_nav": round(current_nav, 4),
    }


async def run_portfolio_nav_synthesizer(org_id: uuid.UUID) -> dict[str, Any]:
    """Synthesize NAV for all constructed model portfolios in an org."""
    logger.info("Starting portfolio NAV synthesis", org_id=str(org_id))

    async with async_session() as db:
        await set_rls_context(db, org_id)

        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({NAV_SYNTH_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.info("worker_skipped", reason="another instance running")
            return {"status": "skipped", "reason": "NAV synthesis already running"}

        try:
            # Fetch all portfolios with fund_selection_schema
            stmt = (
                select(ModelPortfolio)
                .where(
                    ModelPortfolio.fund_selection_schema.isnot(None),
                    ModelPortfolio.status.in_(["backtesting", "active", "live"]),
                )
            )
            result = await db.execute(stmt)
            portfolios = result.scalars().all()

            logger.info("Portfolios to synthesize", count=len(portfolios))

            results: dict[str, Any] = {}
            for portfolio in portfolios:
                try:
                    summary = await synthesize_portfolio_nav(db, portfolio)
                    results[str(portfolio.id)] = summary
                    # Re-set RLS context after commit inside synthesize_portfolio_nav
                    await set_rls_context(db, org_id)
                except Exception:
                    logger.exception(
                        "portfolio_nav_synthesis_failed",
                        portfolio_id=str(portfolio.id),
                    )
                    await db.rollback()
                    await set_rls_context(db, org_id)
                    results[str(portfolio.id)] = {"status": "error"}

            total_dates = sum(
                r.get("dates_computed", 0) for r in results.values()
            )
            logger.info(
                "Portfolio NAV synthesis complete",
                portfolios_processed=len(results),
                total_dates_computed=total_dates,
            )
            return {"status": "ok", "portfolios": results}

        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({NAV_SYNTH_LOCK_ID})"),
                )
            except Exception:
                pass


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m backend.app.domains.wealth.workers.portfolio_nav_synthesizer <org_id>")
        sys.exit(1)

    _org_id = uuid.UUID(sys.argv[1])
    asyncio.run(run_portfolio_nav_synthesizer(_org_id))

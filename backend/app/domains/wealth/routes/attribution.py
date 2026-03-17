"""Attribution API routes — policy benchmark attribution analysis.

GET /analytics/attribution/{profile}  — compute attribution for a profile
"""

from __future__ import annotations

import asyncio
import calendar
from datetime import date
from typing import Any
from uuid import UUID

import numpy as np
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.benchmark_nav import BenchmarkNav
from app.domains.wealth.models.block import AllocationBlock
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.schemas.attribution import AttributionRead, SectorAttributionRead

logger = structlog.get_logger()

router = APIRouter(prefix="/analytics/attribution", tags=["attribution"])


def _add_months(d: date, months: int) -> date:
    """Add months to a date without python-dateutil dependency."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _generate_period_boundaries(
    start_date: date,
    end_date: date,
    granularity: str,
) -> list[tuple[date, date]]:
    """Generate period boundaries for monthly or quarterly attribution."""
    periods: list[tuple[date, date]] = []
    current = start_date
    step = 3 if granularity == "quarterly" else 1
    while current < end_date:
        next_date = _add_months(current, step)
        period_end = min(next_date, end_date)
        periods.append((current, period_end))
        current = next_date
    return periods


@router.get(
    "/{profile}",
    response_model=AttributionRead,
    summary="Compute policy benchmark attribution for a profile",
)
async def get_attribution(
    profile: str,
    start_date: date | None = Query(None, description="Start date (default: 12 months ago)"),
    end_date: date | None = Query(None, description="End date (default: today)"),
    granularity: str = Query("monthly", pattern="^(monthly|quarterly)$"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> AttributionRead:
    effective_end = end_date or date.today()
    effective_start = start_date or _add_months(effective_end, -12)

    # 1. Load strategic allocations for profile
    sa_stmt = select(StrategicAllocation).where(
        StrategicAllocation.profile == profile,
        StrategicAllocation.effective_from <= effective_end,
    )
    sa_result = await db.execute(sa_stmt)
    allocations = sa_result.scalars().all()

    if not allocations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No strategic allocations found for profile '{profile}'",
        )

    # Extract to plain dicts before crossing thread boundary
    sa_dicts = [
        {"block_id": a.block_id, "target_weight": float(a.target_weight)}
        for a in allocations
    ]
    block_ids = [a.block_id for a in allocations]

    # 2. Load block labels
    block_stmt = select(AllocationBlock.block_id, AllocationBlock.display_name).where(
        AllocationBlock.block_id.in_(block_ids)
    )
    block_result = await db.execute(block_stmt)
    block_labels: dict[str, str] = {
        row.block_id: row.display_name for row in block_result.all()
    }

    # 3. Load live model portfolio for fund selection
    mp_stmt = select(ModelPortfolio).where(
        ModelPortfolio.profile == profile,
        ModelPortfolio.status == "live",
    )
    mp_result = await db.execute(mp_stmt)
    live_portfolio = mp_result.scalar()

    # 4. Generate period boundaries
    periods = _generate_period_boundaries(effective_start, effective_end, granularity)

    # 5. Load benchmark returns per block per period
    bench_stmt = (
        select(BenchmarkNav)
        .where(
            BenchmarkNav.block_id.in_(block_ids),
            BenchmarkNav.nav_date >= effective_start,
            BenchmarkNav.nav_date <= effective_end,
        )
        .order_by(BenchmarkNav.block_id, BenchmarkNav.nav_date)
    )
    bench_result = await db.execute(bench_stmt)
    benchmark_rows = bench_result.scalars().all()

    # Group by block_id -> list of (date, return_1d)
    bench_by_block: dict[str, list[dict[str, Any]]] = {}
    for row in benchmark_rows:
        bench_by_block.setdefault(row.block_id, []).append({
            "nav_date": row.nav_date,
            "return_1d": float(row.return_1d) if row.return_1d is not None else 0.0,
        })

    # 6. Load NavTimeseries for fund returns
    fund_selection = live_portfolio.fund_selection_schema if live_portfolio else None
    instruments_by_block: dict[str, list[str]] = {}
    if fund_selection:
        for block_id, funds in fund_selection.items():
            if isinstance(funds, list):
                instruments_by_block[block_id] = [
                    f["instrument_id"] if isinstance(f, dict) else str(f)
                    for f in funds
                ]
            elif isinstance(funds, dict) and "instrument_id" in funds:
                instruments_by_block[block_id] = [funds["instrument_id"]]

    all_instrument_ids: list[str] = []
    for ids in instruments_by_block.values():
        all_instrument_ids.extend(ids)

    nav_returns: dict[str, list[dict[str, Any]]] = {}
    if all_instrument_ids:
        nav_stmt = (
            select(NavTimeseries)
            .where(
                NavTimeseries.instrument_id.in_([UUID(iid) for iid in all_instrument_ids]),
                NavTimeseries.nav_date >= effective_start,
                NavTimeseries.nav_date <= effective_end,
                NavTimeseries.return_1d.isnot(None),
            )
            .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
        )
        nav_result = await db.execute(nav_stmt)
        for row in nav_result.scalars().all():
            key = str(row.instrument_id)
            nav_returns.setdefault(key, []).append({
                "nav_date": row.nav_date,
                "return_1d": float(row.return_1d),
            })

    # 7. Compute attribution in thread
    from vertical_engines.wealth.attribution.service import AttributionService

    # Compute per-period
    period_results = []
    portfolio_period_returns: list[float] = []
    benchmark_period_returns: list[float] = []

    for period_start, period_end in periods:
        # Benchmark returns per block for this period
        benchmark_returns_period: dict[str, float] = {}
        for bid in block_ids:
            block_data = bench_by_block.get(bid, [])
            period_data = [
                d for d in block_data if period_start <= d["nav_date"] <= period_end
            ]
            if period_data:
                compound = float(
                    np.prod([1 + d["return_1d"] for d in period_data]) - 1
                )
                benchmark_returns_period[bid] = compound

        # Fund returns per block for this period
        fund_returns_period: dict[str, float] = {}
        for bid, inst_ids in instruments_by_block.items():
            block_returns: list[float] = []
            for iid in inst_ids:
                inst_data = nav_returns.get(iid, [])
                period_data = [
                    d for d in inst_data if period_start <= d["nav_date"] <= period_end
                ]
                if period_data:
                    compound = float(
                        np.prod([1 + d["return_1d"] for d in period_data]) - 1
                    )
                    block_returns.append(compound)
            if block_returns:
                fund_returns_period[bid] = float(np.mean(block_returns))

        svc = AttributionService()
        result = await asyncio.to_thread(
            svc.compute_portfolio_attribution,
            strategic_allocations=sa_dicts,
            fund_returns_by_block=fund_returns_period,
            benchmark_returns_by_block=benchmark_returns_period,
            block_labels=block_labels,
        )
        period_results.append(result)

        # Period-level returns for Carino linking
        p_ret = sum(
            float(sa["target_weight"]) * fund_returns_period.get(sa["block_id"], 0.0)
            for sa in sa_dicts
        )
        b_ret = sum(
            float(sa["target_weight"]) * benchmark_returns_period.get(sa["block_id"], 0.0)
            for sa in sa_dicts
        )
        portfolio_period_returns.append(p_ret)
        benchmark_period_returns.append(b_ret)

    # Multi-period linking
    if len(period_results) > 1:
        svc_final = AttributionService()
        final_result = await asyncio.to_thread(
            svc_final.compute_multi_period,
            period_results=period_results,
            portfolio_period_returns=portfolio_period_returns,
            benchmark_period_returns=benchmark_period_returns,
        )
    elif period_results:
        final_result = period_results[0]
    else:
        final_result = None

    if final_result is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No data available for attribution computation",
        )

    # Build response
    sectors = [
        SectorAttributionRead(
            sector=s.sector,
            block_id=s.sector,  # sector label is block display_name or block_id
            allocation_effect=s.allocation_effect,
            selection_effect=s.selection_effect,
            interaction_effect=s.interaction_effect,
            total_effect=s.total_effect,
        )
        for s in final_result.sectors
    ]

    return AttributionRead(
        profile=profile,
        start_date=effective_start,
        end_date=effective_end,
        granularity=granularity,
        total_portfolio_return=final_result.total_portfolio_return,
        total_benchmark_return=final_result.total_benchmark_return,
        total_excess_return=final_result.total_excess_return,
        allocation_total=final_result.allocation_total,
        selection_total=final_result.selection_total,
        interaction_total=final_result.interaction_total,
        total_allocation_combined=final_result.allocation_total + final_result.interaction_total,
        sectors=sectors,
        n_periods=final_result.n_periods,
        benchmark_available=final_result.benchmark_available,
    )

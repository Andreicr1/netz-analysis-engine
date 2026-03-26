"""Benchmark Resolver — I/O layer for composite benchmark NAV.

Resolves the benchmark_ticker for each AllocationBlock in a model portfolio's
strategic allocation and fetches benchmark_nav hypertable data (global table,
no RLS). Pairs with quant_engine.benchmark_composite_service for the math.

Usage:
    block_weights, benchmark_navs = await fetch_benchmark_nav_series(db, portfolio_id)
    composite = compute_composite_nav(block_weights, benchmark_navs)
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.benchmark_nav import BenchmarkNav
from app.domains.wealth.models.block import AllocationBlock
from app.domains.wealth.models.model_portfolio import ModelPortfolio

logger = structlog.get_logger()


async def fetch_benchmark_nav_series(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[dict[str, float], dict[str, list[dict[str, Any]]]]:
    """Resolve block benchmark tickers and fetch NAV data.

    Returns
    -------
    tuple[dict[str, float], dict[str, list[dict]]]
        (block_weights, benchmark_navs) where:
        - block_weights: block_id → target weight from strategic allocation
        - benchmark_navs: block_id → [{nav_date, return_1d}] from benchmark_nav
    """
    # 1. Load portfolio to get profile
    result = await db.execute(
        select(ModelPortfolio.profile).where(ModelPortfolio.id == portfolio_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return {}, {}

    # 2. Load strategic allocation for this profile
    today = date.today()
    stmt = (
        select(
            StrategicAllocation.block_id,
            StrategicAllocation.target_weight,
        )
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= today)
        )
    )
    alloc_result = await db.execute(stmt)
    allocations = alloc_result.all()

    if not allocations:
        return {}, {}

    block_weights: dict[str, float] = {}
    block_ids: list[str] = []
    for row in allocations:
        block_weights[row[0]] = float(row[1])
        block_ids.append(row[0])

    # 3. Resolve benchmark_ticker for each block (AllocationBlock is global)
    block_tickers_stmt = select(
        AllocationBlock.block_id,
        AllocationBlock.benchmark_ticker,
    ).where(
        AllocationBlock.block_id.in_(block_ids),
        AllocationBlock.benchmark_ticker.isnot(None),
    )
    ticker_result = await db.execute(block_tickers_stmt)
    block_ticker_map = {row[0]: row[1] for row in ticker_result.all()}

    if not block_ticker_map:
        return block_weights, {}

    # 4. Fetch benchmark_nav for each block
    start = start_date or (today - timedelta(days=1260))
    end = end_date or today

    benchmark_navs: dict[str, list[dict[str, Any]]] = {}

    for block_id in block_ticker_map:
        nav_stmt = (
            select(BenchmarkNav.nav_date, BenchmarkNav.return_1d)
            .where(
                BenchmarkNav.block_id == block_id,
                BenchmarkNav.nav_date >= start,
                BenchmarkNav.nav_date <= end,
                BenchmarkNav.return_1d.isnot(None),
            )
            .order_by(BenchmarkNav.nav_date)
        )
        nav_result = await db.execute(nav_stmt)
        rows = [
            {"nav_date": r[0], "return_1d": float(r[1])}
            for r in nav_result.all()
        ]
        if rows:
            benchmark_navs[block_id] = rows

    return block_weights, benchmark_navs


def fetch_benchmark_nav_series_sync(
    db: Session,
    portfolio_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[dict[str, float], dict[str, list[dict[str, Any]]]]:
    """Sync version for to_thread contexts."""
    result = db.execute(
        select(ModelPortfolio.profile).where(ModelPortfolio.id == portfolio_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return {}, {}

    today = date.today()
    stmt = (
        select(
            StrategicAllocation.block_id,
            StrategicAllocation.target_weight,
        )
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= today)
        )
    )
    alloc_result = db.execute(stmt)
    allocations = alloc_result.all()

    if not allocations:
        return {}, {}

    block_weights: dict[str, float] = {}
    block_ids: list[str] = []
    for row in allocations:
        block_weights[row[0]] = float(row[1])
        block_ids.append(row[0])

    block_tickers_stmt = select(
        AllocationBlock.block_id,
        AllocationBlock.benchmark_ticker,
    ).where(
        AllocationBlock.block_id.in_(block_ids),
        AllocationBlock.benchmark_ticker.isnot(None),
    )
    ticker_result = db.execute(block_tickers_stmt)
    block_ticker_map = {row[0]: row[1] for row in ticker_result.all()}

    if not block_ticker_map:
        return block_weights, {}

    start = start_date or (today - timedelta(days=1260))
    end = end_date or today

    benchmark_navs: dict[str, list[dict[str, Any]]] = {}

    for block_id in block_ticker_map:
        nav_stmt = (
            select(BenchmarkNav.nav_date, BenchmarkNav.return_1d)
            .where(
                BenchmarkNav.block_id == block_id,
                BenchmarkNav.nav_date >= start,
                BenchmarkNav.nav_date <= end,
                BenchmarkNav.return_1d.isnot(None),
            )
            .order_by(BenchmarkNav.nav_date)
        )
        nav_result = db.execute(nav_stmt)
        rows = [
            {"nav_date": r[0], "return_1d": float(r[1])}
            for r in nav_result.all()
        ]
        if rows:
            benchmark_navs[block_id] = rows

    return block_weights, benchmark_navs

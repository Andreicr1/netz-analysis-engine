"""Service layer for blended benchmarks.

All functions are async, receive AsyncSession, and follow never-raises
pattern for read operations. Write operations raise HTTPException on
validation failures.
"""

from __future__ import annotations

import logging
import math
import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.wealth.models.benchmark_nav import BenchmarkNav
from app.domains.wealth.models.blended_benchmark import (
    BlendedBenchmark,
    BlendedBenchmarkComponent,
)
from app.domains.wealth.models.block import AllocationBlock
from app.domains.wealth.schemas.blended_benchmark import (
    BlendedBenchmarkComponentRead,
    BlendedBenchmarkCreate,
    BlendedBenchmarkNAV,
    BlendedBenchmarkRead,
    BlockRead,
)

logger = logging.getLogger(__name__)


async def list_available_blocks(db: AsyncSession) -> list[BlockRead]:
    """List active allocation blocks that have a benchmark ticker."""
    stmt = (
        select(AllocationBlock)
        .where(
            AllocationBlock.is_active.is_(True),
            AllocationBlock.benchmark_ticker.isnot(None),
        )
        .order_by(AllocationBlock.geography, AllocationBlock.asset_class)
    )
    result = await db.execute(stmt)
    return [BlockRead.model_validate(row) for row in result.scalars().all()]


async def get_active_benchmark(
    db: AsyncSession, profile: str
) -> BlendedBenchmarkRead | None:
    """Get the currently active blended benchmark for a profile."""
    stmt = (
        select(BlendedBenchmark)
        .options(selectinload(BlendedBenchmark.components))
        .where(
            BlendedBenchmark.portfolio_profile == profile,
            BlendedBenchmark.is_active.is_(True),
        )
        .order_by(BlendedBenchmark.updated_at.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    benchmark = result.scalar_one_or_none()
    if benchmark is None:
        return None

    # Enrich components with block display_name and benchmark_ticker
    block_ids = [c.block_id for c in benchmark.components]
    blocks_stmt = select(AllocationBlock).where(AllocationBlock.block_id.in_(block_ids))
    blocks_result = await db.execute(blocks_stmt)
    block_map = {b.block_id: b for b in blocks_result.scalars().all()}

    components = []
    for c in benchmark.components:
        block = block_map.get(c.block_id)
        components.append(
            BlendedBenchmarkComponentRead(
                id=c.id,
                block_id=c.block_id,
                weight=c.weight,
                display_name=block.display_name if block else None,
                benchmark_ticker=block.benchmark_ticker if block else None,
            )
        )

    return BlendedBenchmarkRead(
        id=benchmark.id,
        portfolio_profile=benchmark.portfolio_profile,
        name=benchmark.name,
        is_active=benchmark.is_active,
        created_at=benchmark.created_at,
        updated_at=benchmark.updated_at,
        components=components,
    )


async def create_blended_benchmark(
    db: AsyncSession, profile: str, payload: BlendedBenchmarkCreate
) -> BlendedBenchmarkRead:
    """Create or replace the active blended benchmark for a profile.

    Validates:
    - sum(weights) == 1.0 (tolerance 0.0001)
    - all block_ids exist and have benchmark_ticker
    Deactivates any previous active benchmark for the same profile.
    """
    # Validate block_ids exist
    block_ids = [c.block_id for c in payload.components]
    blocks_stmt = select(AllocationBlock).where(AllocationBlock.block_id.in_(block_ids))
    blocks_result = await db.execute(blocks_stmt)
    block_map = {b.block_id: b for b in blocks_result.scalars().all()}

    missing = [bid for bid in block_ids if bid not in block_map]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown block_ids: {missing}",
        )

    no_ticker = [bid for bid in block_ids if not block_map[bid].benchmark_ticker]
    if no_ticker:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Blocks without benchmark_ticker: {no_ticker}",
        )

    # Deactivate previous active benchmarks for this profile
    prev_stmt = select(BlendedBenchmark).where(
        BlendedBenchmark.portfolio_profile == profile,
        BlendedBenchmark.is_active.is_(True),
    )
    prev_result = await db.execute(prev_stmt)
    for prev in prev_result.scalars().all():
        prev.is_active = False

    # Create new benchmark
    benchmark = BlendedBenchmark(
        portfolio_profile=profile,
        name=payload.name,
        is_active=True,
    )
    db.add(benchmark)
    await db.flush()

    # Create components
    components = []
    for c in payload.components:
        comp = BlendedBenchmarkComponent(
            benchmark_id=benchmark.id,
            block_id=c.block_id,
            weight=float(c.weight),
        )
        db.add(comp)
        components.append(comp)

    await db.flush()

    # Build response
    comp_reads = []
    for comp in components:
        block = block_map.get(comp.block_id)
        comp_reads.append(
            BlendedBenchmarkComponentRead(
                id=comp.id,
                block_id=comp.block_id,
                weight=Decimal(str(comp.weight)),
                display_name=block.display_name if block else None,
                benchmark_ticker=block.benchmark_ticker if block else None,
            )
        )

    return BlendedBenchmarkRead(
        id=benchmark.id,
        portfolio_profile=benchmark.portfolio_profile,
        name=benchmark.name,
        is_active=benchmark.is_active,
        created_at=benchmark.created_at,
        updated_at=benchmark.updated_at,
        components=comp_reads,
    )


async def deactivate_benchmark(db: AsyncSession, benchmark_id: uuid.UUID) -> bool:
    """Deactivate a blended benchmark by ID. Returns True if found."""
    stmt = select(BlendedBenchmark).where(BlendedBenchmark.id == benchmark_id)
    result = await db.execute(stmt)
    benchmark = result.scalar_one_or_none()
    if benchmark is None:
        return False
    benchmark.is_active = False
    await db.flush()
    return True


async def compute_blended_nav(
    db: AsyncSession, benchmark_id: uuid.UUID, lookback_days: int = 365
) -> list[BlendedBenchmarkNAV]:
    """Compute blended NAV series from weighted constituent returns.

    1. Fetch benchmark_nav for all component block_ids within lookback window
    2. Compute weighted sum of log returns per date (inner join)
    3. Accumulate to reconstruct NAV indexed to 100
    """
    import datetime as dt

    # Load benchmark with components
    stmt = (
        select(BlendedBenchmark)
        .options(selectinload(BlendedBenchmark.components))
        .where(BlendedBenchmark.id == benchmark_id)
    )
    result = await db.execute(stmt)
    benchmark = result.scalar_one_or_none()
    if benchmark is None:
        return []

    if not benchmark.components:
        return []

    # Build weight map
    weight_map: dict[str, float] = {
        c.block_id: float(c.weight) for c in benchmark.components
    }
    block_ids = list(weight_map.keys())

    # Fetch returns within lookback window
    cutoff = dt.date.today() - dt.timedelta(days=lookback_days)
    nav_stmt = (
        select(BenchmarkNav.block_id, BenchmarkNav.nav_date, BenchmarkNav.return_1d)
        .where(
            BenchmarkNav.block_id.in_(block_ids),
            BenchmarkNav.nav_date >= cutoff,
            BenchmarkNav.return_1d.isnot(None),
        )
        .order_by(BenchmarkNav.nav_date)
    )
    nav_result = await db.execute(nav_stmt)
    rows = nav_result.all()

    if not rows:
        return []

    # Group returns by date
    returns_by_date: dict[dt.date, dict[str, float]] = {}
    for block_id, nav_date, return_1d in rows:
        if nav_date not in returns_by_date:
            returns_by_date[nav_date] = {}
        returns_by_date[nav_date][block_id] = float(return_1d)

    # Inner join: only dates with ALL components present
    dates = sorted(returns_by_date.keys())
    nav_series: list[BlendedBenchmarkNAV] = []
    cumulative_log_return = 0.0

    for d in dates:
        date_returns = returns_by_date[d]
        if len(date_returns) < len(block_ids):
            continue  # Skip incomplete dates

        # Weighted sum of log returns
        blended_return = sum(
            weight_map[bid] * date_returns[bid] for bid in block_ids
        )
        cumulative_log_return += blended_return
        nav_value = 100.0 * math.exp(cumulative_log_return)

        nav_series.append(
            BlendedBenchmarkNAV(
                date=d,
                nav=round(nav_value, 4),
                return_1d=round(blended_return, 8),
            )
        )

    return nav_series

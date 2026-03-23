"""Routes for blended benchmark management.

Global tables — no RLS. GET /blocks is public (no auth required for typeahead).
POST and DELETE require IC member role.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user, require_ic_member
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.blended_benchmark import (
    BlendedBenchmarkCreate,
    BlendedBenchmarkNAV,
    BlendedBenchmarkRead,
    BlockRead,
)
from app.domains.wealth.services import blended_benchmark_service as svc

router = APIRouter(prefix="/blended-benchmarks", tags=["wealth", "blended-benchmarks"])


@router.get(
    "/blocks",
    response_model=list[BlockRead],
    summary="List available allocation blocks for benchmark composition",
)
async def list_blocks(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[BlockRead]:
    return await svc.list_available_blocks(db)


@router.get(
    "/{profile}",
    response_model=BlendedBenchmarkRead | None,
    summary="Get active blended benchmark for a profile",
)
async def get_benchmark(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> BlendedBenchmarkRead | None:
    return await svc.get_active_benchmark(db, profile)


@router.post(
    "/{profile}",
    response_model=BlendedBenchmarkRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create or replace blended benchmark for a profile",
)
async def create_benchmark(
    profile: str,
    body: BlendedBenchmarkCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(require_ic_member),
) -> BlendedBenchmarkRead:
    return await svc.create_blended_benchmark(db, profile, body)


@router.get(
    "/{benchmark_id}/nav",
    response_model=list[BlendedBenchmarkNAV],
    summary="Computed NAV time series for a blended benchmark",
)
async def get_benchmark_nav(
    benchmark_id: uuid.UUID,
    lookback_days: int = Query(default=365, ge=30, le=3650),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[BlendedBenchmarkNAV]:
    return await svc.compute_blended_nav(db, benchmark_id, lookback_days)


@router.delete(
    "/{benchmark_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a blended benchmark",
)
async def delete_benchmark(
    benchmark_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(require_ic_member),
) -> None:
    found = await svc.deactivate_benchmark(db, benchmark_id)
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Benchmark not found",
        )

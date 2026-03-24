"""Exposure Monitor routes — geographic and sector allocation heatmaps.

GET /wealth/exposure/matrix   — weighted exposure from real portfolio snapshots
GET /wealth/exposure/metadata — snapshot freshness for the tenant
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.exposure import ExposureMatrixRead, ExposureMetadataRead
from app.domains.wealth.services import exposure_service

router = APIRouter(prefix="/wealth/exposure", tags=["exposure"])


@router.get(
    "/matrix",
    response_model=ExposureMatrixRead,
    summary="Geographic or sector exposure heatmap",
)
async def get_exposure_matrix(
    dimension: Literal["geographic", "sector"] = Query(
        "geographic",
        description="Breakdown dimension: geographic | sector",
    ),
    aggregation: Literal["portfolio", "manager"] = Query(
        "portfolio",
        description="Row grouping: portfolio profiles | fund managers",
    ),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ExposureMatrixRead:
    return await exposure_service.get_exposure_matrix(
        db=db,
        organization_id=actor.organization_id,
        dimension=dimension,
        aggregation=aggregation,
    )


@router.get(
    "/metadata",
    response_model=ExposureMetadataRead,
    summary="Exposure data freshness",
)
async def get_exposure_metadata(
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ExposureMetadataRead:
    return await exposure_service.get_exposure_metadata(
        db=db,
        organization_id=actor.organization_id,
    )

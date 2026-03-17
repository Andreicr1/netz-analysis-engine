"""Exposure Monitor routes — geographic and sector allocation heatmaps.

GET /exposure/matrix   — returns weighted exposure matrix (geographic or sector)
GET /exposure/metadata — returns data freshness per fund and leading indicator stubs
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.exposure import (
    ExposureMatrixRead,
    ExposureMetadataRead,
    FundFreshness,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/exposure", tags=["exposure"])


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
        description="Aggregation unit: portfolio | manager",
    ),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> ExposureMatrixRead:
    """Return a weighted exposure matrix for the requested dimension and aggregation.

    Data is currently sourced from placeholder values; real aggregation from
    instruments_universe.attributes will be wired in the instruments data pipeline.
    """
    logger.debug(
        "exposure_matrix_requested",
        dimension=dimension,
        aggregation=aggregation,
    )

    if dimension == "geographic":
        if aggregation == "portfolio":
            rows = ["Conservador", "Moderado", "Growth"]
            columns = ["Brasil", "EUA", "Europa", "Ásia", "Global"]
            data = [
                [0.45, 0.20, 0.15, 0.10, 0.10],
                [0.35, 0.25, 0.18, 0.12, 0.10],
                [0.25, 0.30, 0.20, 0.15, 0.10],
            ]
        else:
            rows = ["Bradesco Asset", "BTG Gestora", "XP Investimentos"]
            columns = ["Brasil", "EUA", "Europa", "Ásia", "Global"]
            data = [
                [0.60, 0.15, 0.12, 0.08, 0.05],
                [0.40, 0.28, 0.18, 0.10, 0.04],
                [0.30, 0.32, 0.22, 0.10, 0.06],
            ]
    else:
        # sector
        if aggregation == "portfolio":
            rows = ["Conservador", "Moderado", "Growth"]
            columns = ["Renda Fixa", "Multimercado", "Ações", "FII", "Infra", "Exterior"]
            data = [
                [0.50, 0.25, 0.10, 0.08, 0.05, 0.02],
                [0.35, 0.28, 0.18, 0.10, 0.05, 0.04],
                [0.20, 0.25, 0.28, 0.12, 0.08, 0.07],
            ]
        else:
            rows = ["Bradesco Asset", "BTG Gestora", "XP Investimentos"]
            columns = ["Renda Fixa", "Multimercado", "Ações", "FII", "Infra", "Exterior"]
            data = [
                [0.55, 0.22, 0.12, 0.06, 0.04, 0.01],
                [0.38, 0.30, 0.18, 0.08, 0.04, 0.02],
                [0.25, 0.28, 0.26, 0.10, 0.06, 0.05],
            ]

    return ExposureMatrixRead.model_validate(
        {
            "dimension": dimension,
            "aggregation": aggregation,
            "rows": rows,
            "columns": columns,
            "data": data,
        }
    )


@router.get(
    "/metadata",
    response_model=ExposureMetadataRead,
    summary="Exposure data freshness per fund",
)
async def get_exposure_metadata(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> ExposureMetadataRead:
    """Return data freshness indicators per fund and leading indicator stubs.

    Freshness is currently stubbed; real values will be derived from
    instruments_universe.updated_at once the pipeline populates that field.
    """
    freshness = [
        FundFreshness(fund_name="Fundo Conservador A", last_updated_days=12),
        FundFreshness(fund_name="Fundo Moderado B", last_updated_days=35),
        FundFreshness(fund_name="Fundo Growth C", last_updated_days=7),
        FundFreshness(fund_name="Fundo Balanceado D", last_updated_days=68),
    ]

    return ExposureMetadataRead.model_validate({"freshness": freshness})

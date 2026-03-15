"""Macro intelligence API routes — regional scores + snapshot access.

Phase 1: two read-only endpoints for macro scoring data.
Phase 2 will add committee workflow routes (generate, approve, reject).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.macro import (
    DataFreshnessRead,
    DimensionScoreRead,
    GlobalIndicatorsRead,
    MacroScoresResponse,
    MacroSnapshotResponse,
    RegionalScoreRead,
)
from app.shared.models import MacroRegionalSnapshot

router = APIRouter(prefix="/macro")


@router.get(
    "/scores",
    response_model=MacroScoresResponse,
    summary="Latest regional macro scores + global indicators",
    tags=["macro"],
)
async def get_macro_scores(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> MacroScoresResponse:
    """Return the most recent regional macro scores and global indicators.

    Scores are percentile-ranked (0-100, 50 = historical median).
    Higher = better conditions (except inverted indicators like VIX).
    """
    stmt = (
        select(MacroRegionalSnapshot)
        .order_by(MacroRegionalSnapshot.as_of_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No macro snapshot available. Run macro ingestion worker first.",
        )

    data = snapshot.data_json

    # Parse regions
    regions: dict[str, RegionalScoreRead] = {}
    for region_key, region_data in data.get("regions", {}).items():
        dimensions = {
            dim: DimensionScoreRead(**dim_data)
            for dim, dim_data in region_data.get("dimensions", {}).items()
        }
        freshness = {
            sid: DataFreshnessRead(**f_data)
            for sid, f_data in region_data.get("data_freshness", {}).items()
        }
        regions[region_key] = RegionalScoreRead(
            composite_score=region_data["composite_score"],
            coverage=region_data["coverage"],
            dimensions=dimensions,
            data_freshness=freshness,
        )

    # Parse global indicators
    gi_data = data.get("global_indicators", {})
    global_indicators = GlobalIndicatorsRead(
        geopolitical_risk_score=gi_data.get("geopolitical_risk_score", 50.0),
        energy_stress=gi_data.get("energy_stress", 50.0),
        commodity_stress=gi_data.get("commodity_stress", 50.0),
        usd_strength=gi_data.get("usd_strength", 50.0),
    )

    return MacroScoresResponse(
        as_of_date=snapshot.as_of_date,
        regions=regions,
        global_indicators=global_indicators,
    )


@router.get(
    "/snapshot",
    response_model=MacroSnapshotResponse,
    summary="Latest full macro snapshot (raw JSONB)",
    tags=["macro"],
)
async def get_macro_snapshot(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> MacroSnapshotResponse:
    """Return the latest raw macro regional snapshot.

    The data_json field contains the full snapshot including per-indicator
    percentile scores, staleness metadata, and dimension breakdowns.
    """
    stmt = (
        select(MacroRegionalSnapshot)
        .order_by(MacroRegionalSnapshot.as_of_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No macro snapshot available. Run macro ingestion worker first.",
        )

    return MacroSnapshotResponse.model_validate(snapshot)

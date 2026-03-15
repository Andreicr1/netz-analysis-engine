"""Macro intelligence API routes — regional scores, snapshot, regime, committee.

Phase 1: GET /scores, GET /snapshot
Phase 2: GET /regime, GET /reviews, POST /reviews/generate,
         PATCH /reviews/{id}/approve, PATCH /reviews/{id}/reject
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user, require_role
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.macro_committee import MacroReview
from app.domains.wealth.schemas.macro import (
    DataFreshnessRead,
    DimensionScoreRead,
    GlobalIndicatorsRead,
    MacroReviewApprove,
    MacroReviewRead,
    MacroReviewReject,
    MacroScoresResponse,
    MacroSnapshotResponse,
    RegimeHierarchyRead,
    RegionalScoreRead,
)
from app.shared.enums import Role
from app.shared.models import MacroRegionalSnapshot
from quant_engine.regime_service import (
    REGIONAL_REGIME_SIGNALS,
    classify_regional_regime,
    compose_global_regime,
    get_latest_macro_values,
    resolve_regional_regime_config,
)
from vertical_engines.wealth.macro_committee_engine import (
    build_report_json,
    generate_weekly_report,
)

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


# ---------------------------------------------------------------------------
#  Phase 2: Regime Hierarchy + Committee Workflow
# ---------------------------------------------------------------------------


@router.get(
    "/regime",
    response_model=RegimeHierarchyRead,
    summary="Hierarchical regime: global + per-region",
    tags=["macro"],
)
async def get_hierarchical_regime(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RegimeHierarchyRead:
    """Return hierarchical regime classification: global + 4 regions.

    Uses ICE BofA credit spreads for regional signals and GDP-weighted
    composition with pessimistic override for global regime.
    """
    macro = await get_latest_macro_values(db)
    config = resolve_regional_regime_config(None)

    vix_val = macro.get("VIXCLS", (None, None))[0]
    cpi_val = macro.get("CPI_YOY", (None, None))[0]

    regional_results: dict[str, str] = {}
    for region, signal_ids in REGIONAL_REGIME_SIGNALS.items():
        signal_values = {
            sid: macro.get(sid, (None, None))[0] for sid in signal_ids
        }
        result = classify_regional_regime(
            region, signal_values,
            vix=vix_val if region == "US" else None,
            cpi_yoy=cpi_val,
            config=config,
        )
        regional_results[region] = result.regime

    global_regime, composition_reasons = compose_global_regime(
        regional_results, config=config,
    )

    as_of = None
    for _, obs_date in macro.values():
        if obs_date is not None and (as_of is None or obs_date > as_of):
            as_of = obs_date

    return RegimeHierarchyRead(
        global_regime=global_regime,
        regional_regimes=regional_results,
        composition_reasons=composition_reasons,
        as_of_date=as_of,
    )


@router.get(
    "/reviews",
    response_model=list[MacroReviewRead],
    summary="List macro committee reviews",
    tags=["macro"],
)
async def list_reviews(
    limit: int = Query(default=20, le=100),
    status_filter: str | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[MacroReviewRead]:
    """List macro committee reviews for the current organization."""
    stmt = select(MacroReview).order_by(MacroReview.created_at.desc()).limit(limit)
    if status_filter:
        stmt = stmt.where(MacroReview.status == status_filter)
    result = await db.execute(stmt)
    reviews = result.scalars().all()
    return [MacroReviewRead.model_validate(r) for r in reviews]


@router.post(
    "/reviews/generate",
    response_model=MacroReviewRead,
    status_code=status.HTTP_201_CREATED,
    summary="Generate macro committee report",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.INVESTMENT_TEAM))],
)
async def generate_review(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: UUID | None = Depends(get_org_id),
) -> MacroReviewRead:
    """Generate a new macro committee review from current + previous snapshots."""
    # Get current and previous snapshots
    stmt = (
        select(MacroRegionalSnapshot)
        .order_by(MacroRegionalSnapshot.as_of_date.desc())
        .limit(2)
    )
    result = await db.execute(stmt)
    snapshots = result.scalars().all()

    if not snapshots:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No macro snapshot available. Run macro ingestion worker first.",
        )

    current = snapshots[0]
    previous = snapshots[1] if len(snapshots) > 1 else None

    report = generate_weekly_report(
        current.data_json,
        previous.data_json if previous else None,
    )

    review = MacroReview(
        organization_id=org_id,
        status="pending",
        is_emergency=False,
        as_of_date=current.as_of_date,
        snapshot_id=current.id,
        report_json=build_report_json(report),
        created_by=user.actor_id,
    )
    db.add(review)
    await db.flush()

    return MacroReviewRead.model_validate(review)


@router.patch(
    "/reviews/{review_id}/approve",
    response_model=MacroReviewRead,
    summary="CIO approval of macro review",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.DIRECTOR, Role.ADMIN))],
)
async def approve_review(
    review_id: UUID,
    body: MacroReviewApprove,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> MacroReviewRead:
    """Approve a pending macro review."""
    stmt = (
        select(MacroReview)
        .where(MacroReview.id == review_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found.",
        )
    if review.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Review is already {review.status}.",
        )

    review.status = "approved"
    review.approved_by = user.actor_id
    review.approved_at = datetime.now(timezone.utc)
    review.decision_rationale = body.decision_rationale

    await db.flush()
    return MacroReviewRead.model_validate(review)


@router.patch(
    "/reviews/{review_id}/reject",
    response_model=MacroReviewRead,
    summary="CIO rejection of macro review",
    tags=["macro"],
    dependencies=[Depends(require_role(Role.DIRECTOR, Role.ADMIN))],
)
async def reject_review(
    review_id: UUID,
    body: MacroReviewReject,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> MacroReviewRead:
    """Reject a pending macro review with rationale."""
    stmt = (
        select(MacroReview)
        .where(MacroReview.id == review_id)
        .with_for_update()
    )
    result = await db.execute(stmt)
    review = result.scalar_one_or_none()

    if review is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Review not found.",
        )
    if review.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Review is already {review.status}.",
        )

    review.status = "rejected"
    review.approved_by = user.actor_id  # Record who rejected for audit trail
    review.decision_rationale = body.decision_rationale

    await db.flush()
    return MacroReviewRead.model_validate(review)

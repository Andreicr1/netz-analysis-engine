import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user, require_ic_member
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from app.domains.wealth.models.rebalance import RebalanceEvent
from app.domains.wealth.schemas.portfolio import (
    PortfolioSnapshotRead,
    PortfolioSummary,
    RebalanceApproveRequest,
    RebalanceEventRead,
    RebalanceRequest,
)
from app.routers.common import VALID_PROFILES, get_latest_snapshot
from app.routers.common import validate_profile as _validate_profile

router = APIRouter(prefix="/portfolios")


def _snapshot_to_summary(profile: str, snap: PortfolioSnapshot | None) -> PortfolioSummary:
    return PortfolioSummary(
        profile=profile,
        snapshot_date=snap.snapshot_date if snap else None,
        cvar_current=snap.cvar_current if snap else None,
        cvar_limit=snap.cvar_limit if snap else None,
        cvar_utilized_pct=snap.cvar_utilized_pct if snap else None,
        trigger_status=snap.trigger_status if snap else None,
        regime=snap.regime if snap else None,
        core_weight=snap.core_weight if snap else None,
        satellite_weight=snap.satellite_weight if snap else None,
    )


@router.get(
    "",
    response_model=list[PortfolioSummary],
    summary="All profiles summary",
    description="Returns the latest snapshot summary for all 3 model portfolios.",
)
async def list_portfolios(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[PortfolioSummary]:
    summaries: list[PortfolioSummary] = []
    for profile in sorted(VALID_PROFILES):
        snap = await get_latest_snapshot(db, profile)
        summaries.append(_snapshot_to_summary(profile, snap))
    return summaries


@router.get(
    "/{profile}",
    response_model=PortfolioSummary,
    summary="Profile detail",
    description="Returns the latest snapshot summary for a specific profile.",
)
async def get_portfolio(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> PortfolioSummary:
    _validate_profile(profile)
    snap = await get_latest_snapshot(db, profile)
    return _snapshot_to_summary(profile, snap)


@router.get(
    "/{profile}/snapshot",
    response_model=PortfolioSnapshotRead | None,
    summary="Latest snapshot",
    description="Returns the full latest snapshot including weights and fund selection.",
)
async def get_snapshot(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> PortfolioSnapshotRead | None:
    _validate_profile(profile)
    snap = await get_latest_snapshot(db, profile)
    if snap is None:
        return None
    return PortfolioSnapshotRead.model_validate(snap)


@router.get(
    "/{profile}/history",
    response_model=list[PortfolioSnapshotRead],
    summary="Snapshot history",
    description="Returns snapshot history for a profile within a date range.",
)
async def get_history(
    profile: str,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[PortfolioSnapshotRead]:
    _validate_profile(profile)
    stmt = select(PortfolioSnapshot).where(PortfolioSnapshot.profile == profile)
    if from_date is not None:
        stmt = stmt.where(PortfolioSnapshot.snapshot_date >= from_date)
    if to_date is not None:
        stmt = stmt.where(PortfolioSnapshot.snapshot_date <= to_date)
    stmt = stmt.order_by(PortfolioSnapshot.snapshot_date).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [PortfolioSnapshotRead.model_validate(row) for row in result.scalars().all()]


@router.post(
    "/{profile}/rebalance",
    response_model=RebalanceEventRead,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger rebalance proposal",
    description="Creates a pending rebalance event for IC review.",
)
async def trigger_rebalance(
    profile: str,
    body: RebalanceRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RebalanceEventRead:
    _validate_profile(profile)
    snap = await get_latest_snapshot(db, profile)

    event = RebalanceEvent(
        profile=profile,
        event_date=date.today(),
        event_type="manual",
        trigger_reason=body.trigger_reason,
        weights_before=snap.weights if snap else None,
        cvar_before=snap.cvar_current if snap else None,
        status="pending",
        actor_source="human",
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return RebalanceEventRead.model_validate(event)


@router.get(
    "/{profile}/rebalance",
    response_model=list[RebalanceEventRead],
    summary="List rebalance events",
    description="Returns rebalance events for a profile, ordered by date descending.",
)
async def list_rebalance_events(
    profile: str,
    event_status: str | None = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[RebalanceEventRead]:
    _validate_profile(profile)
    stmt = select(RebalanceEvent).where(RebalanceEvent.profile == profile)
    if event_status is not None:
        stmt = stmt.where(RebalanceEvent.status == event_status)
    stmt = stmt.order_by(RebalanceEvent.event_date.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [RebalanceEventRead.model_validate(row) for row in result.scalars().all()]


@router.get(
    "/{profile}/rebalance/{event_id}",
    response_model=RebalanceEventRead,
    summary="Rebalance event detail",
    description="Returns details of a specific rebalance event.",
)
async def get_rebalance_event(
    profile: str,
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RebalanceEventRead:
    _validate_profile(profile)
    stmt = select(RebalanceEvent).where(
        RebalanceEvent.event_id == event_id,
        RebalanceEvent.profile == profile,
    )
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rebalance event not found"
        )
    return RebalanceEventRead.model_validate(event)


@router.post(
    "/{profile}/rebalance/{event_id}/approve",
    response_model=RebalanceEventRead,
    summary="Approve rebalance",
    description="IC member approves a pending rebalance event.",
)
async def approve_rebalance(
    profile: str,
    event_id: uuid.UUID,
    body: RebalanceApproveRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(require_ic_member),
) -> RebalanceEventRead:
    _validate_profile(profile)
    # SELECT FOR UPDATE to prevent concurrent approval race condition
    stmt = (
        select(RebalanceEvent)
        .where(
            RebalanceEvent.event_id == event_id,
            RebalanceEvent.profile == profile,
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rebalance event not found"
        )
    from quant_engine.rebalance_service import validate_status_transition

    if not validate_status_transition(event.status, "approved"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot transition from '{event.status}' to 'approved'",
        )
    event.status = "approved"
    event.approved_by = user.name
    event.notes = body.notes
    await db.flush()
    await db.refresh(event)
    return RebalanceEventRead.model_validate(event)


@router.post(
    "/{profile}/rebalance/{event_id}/execute",
    response_model=RebalanceEventRead,
    summary="Execute approved rebalance",
    description="Executes an approved rebalance: re-runs optimizer, applies fund selection, creates new snapshot.",
)
async def execute_rebalance(
    profile: str,
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(require_ic_member),
) -> RebalanceEventRead:
    """Execute a previously approved rebalance event.

    Steps:
    1. Validate event is in 'approved' status
    2. Create new PortfolioSnapshot with current weights
    3. Transition event to 'executed'
    4. Publish SSE alert
    """
    _validate_profile(profile)

    from quant_engine.rebalance_service import validate_status_transition

    stmt = (
        select(RebalanceEvent)
        .where(
            RebalanceEvent.event_id == event_id,
            RebalanceEvent.profile == profile,
        )
        .with_for_update()
    )
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Rebalance event not found"
        )

    if not validate_status_transition(event.status, "executed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot execute rebalance in '{event.status}' status (must be 'approved')",
        )

    # Get current snapshot as basis for new weights
    current_snap = await get_latest_snapshot(db, profile)

    # Create new snapshot with the event's proposed weights
    new_snap = PortfolioSnapshot(
        profile=profile,
        snapshot_date=date.today(),
        weights=event.weights_after or (current_snap.weights if current_snap else None),
        fund_selection=current_snap.fund_selection if current_snap else None,
        cvar_current=current_snap.cvar_current if current_snap else None,
        cvar_limit=current_snap.cvar_limit if current_snap else None,
        cvar_utilized_pct=current_snap.cvar_utilized_pct if current_snap else None,
        trigger_status=current_snap.trigger_status if current_snap else "ok",
        regime=current_snap.regime if current_snap else None,
        core_weight=current_snap.core_weight if current_snap else None,
        satellite_weight=current_snap.satellite_weight if current_snap else None,
    )
    db.add(new_snap)

    # Transition event to executed
    event.status = "executed"
    event.weights_after = new_snap.weights

    await db.flush()
    await db.refresh(event)

    # Publish SSE event (best-effort, don't fail on SSE error)
    try:
        from app.core.jobs.tracker import publish_event as sse_publish

        await sse_publish(
            f"rebalance:{profile}",
            "rebalance_executed",
            {
                "event_id": str(event_id),
                "profile": profile,
                "snapshot_date": str(new_snap.snapshot_date),
            },
        )
    except Exception:
        pass  # SSE failure is non-critical

    return RebalanceEventRead.model_validate(event)

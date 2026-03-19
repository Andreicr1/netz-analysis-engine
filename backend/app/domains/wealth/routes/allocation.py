import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user, require_ic_member
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.allocation import StrategicAllocation, TacticalPosition
from app.domains.wealth.schemas.allocation import (
    AllocationProposal,
    EffectiveAllocationRead,
    SimulationResult,
    StrategicAllocationRead,
    StrategicAllocationUpdate,
    TacticalPositionRead,
    TacticalPositionUpdate,
)
from app.domains.wealth.routes.common import get_latest_snapshot, validate_profile as _validate_profile

router = APIRouter(prefix="/allocation")


@router.get(
    "/{profile}/strategic",
    response_model=list[StrategicAllocationRead],
    summary="Current strategic weights",
    description="Returns the currently effective IC-approved strategic allocation for a profile.",
)
async def get_strategic(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[StrategicAllocationRead]:
    _validate_profile(profile)
    today = date.today()
    stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= today),
        )
        .order_by(StrategicAllocation.block_id)
    )
    result = await db.execute(stmt)
    return [StrategicAllocationRead.model_validate(row) for row in result.scalars().all()]


@router.put(
    "/{profile}/strategic",
    response_model=list[StrategicAllocationRead],
    summary="IC update strategic weights",
    description="Replaces the strategic allocation for a profile. Requires IC member role.",
)
async def update_strategic(
    profile: str,
    body: StrategicAllocationUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(require_ic_member),
) -> list[StrategicAllocationRead]:
    _validate_profile(profile)
    today = date.today()

    # Expire current allocations
    current_stmt = select(StrategicAllocation).where(
        StrategicAllocation.profile == profile,
        StrategicAllocation.effective_from <= today,
        (StrategicAllocation.effective_to.is_(None))
        | (StrategicAllocation.effective_to >= today),
    )
    current_result = await db.execute(current_stmt)
    for row in current_result.scalars().all():
        row.effective_to = today

    # Create new allocations
    new_rows: list[StrategicAllocation] = []
    for item in body.allocations:
        row = StrategicAllocation(
            profile=profile,
            block_id=item.block_id,
            target_weight=item.target_weight,
            min_weight=item.min_weight,
            max_weight=item.max_weight,
            risk_budget=item.risk_budget,
            rationale=item.rationale,
            approved_by=user.name,
            effective_from=today,
        )
        db.add(row)
        new_rows.append(row)

    await db.flush()
    for row in new_rows:
        await db.refresh(row)
    return [StrategicAllocationRead.model_validate(row) for row in new_rows]


@router.get(
    "/{profile}/tactical",
    response_model=list[TacticalPositionRead],
    summary="Current tactical positions",
    description="Returns active tactical overweight positions for a profile.",
)
async def get_tactical(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[TacticalPositionRead]:
    _validate_profile(profile)
    today = date.today()
    stmt = (
        select(TacticalPosition)
        .where(
            TacticalPosition.profile == profile,
            TacticalPosition.valid_from <= today,
            (TacticalPosition.valid_to.is_(None)) | (TacticalPosition.valid_to >= today),
        )
        .order_by(TacticalPosition.block_id)
    )
    result = await db.execute(stmt)
    return [TacticalPositionRead.model_validate(row) for row in result.scalars().all()]


@router.put(
    "/{profile}/tactical",
    response_model=list[TacticalPositionRead],
    summary="Update tactical positions",
    description="Replaces tactical overweight positions for a profile.",
)
async def update_tactical(
    profile: str,
    body: TacticalPositionUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(require_ic_member),
) -> list[TacticalPositionRead]:
    _validate_profile(profile)
    today = date.today()

    # Expire current positions
    current_stmt = select(TacticalPosition).where(
        TacticalPosition.profile == profile,
        TacticalPosition.valid_from <= today,
        (TacticalPosition.valid_to.is_(None)) | (TacticalPosition.valid_to >= today),
    )
    current_result = await db.execute(current_stmt)
    for row in current_result.scalars().all():
        row.valid_to = today

    # Create new positions
    new_rows: list[TacticalPosition] = []
    for item in body.positions:
        row = TacticalPosition(
            profile=profile,
            block_id=item.block_id,
            overweight=item.overweight,
            conviction_score=item.conviction_score,
            signal_source=item.signal_source,
            rationale=item.rationale,
            valid_from=today,
        )
        db.add(row)
        new_rows.append(row)

    await db.flush()
    for row in new_rows:
        await db.refresh(row)
    return [TacticalPositionRead.model_validate(row) for row in new_rows]


@router.get(
    "/{profile}/effective",
    response_model=list[EffectiveAllocationRead],
    summary="Effective allocation",
    description="Computed effective allocation: strategic target + tactical overweight.",
)
async def get_effective(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[EffectiveAllocationRead]:
    _validate_profile(profile)
    today = date.today()

    # Get strategic allocations
    strategic_stmt = select(StrategicAllocation).where(
        StrategicAllocation.profile == profile,
        StrategicAllocation.effective_from <= today,
        (StrategicAllocation.effective_to.is_(None))
        | (StrategicAllocation.effective_to >= today),
    )
    strategic_result = await db.execute(strategic_stmt)
    strategic_map: dict[str, StrategicAllocation] = {
        row.block_id: row for row in strategic_result.scalars().all()
    }

    # Get tactical positions
    tactical_stmt = select(TacticalPosition).where(
        TacticalPosition.profile == profile,
        TacticalPosition.valid_from <= today,
        (TacticalPosition.valid_to.is_(None)) | (TacticalPosition.valid_to >= today),
    )
    tactical_result = await db.execute(tactical_stmt)
    tactical_map: dict[str, TacticalPosition] = {
        row.block_id: row for row in tactical_result.scalars().all()
    }

    all_blocks = set(strategic_map.keys()) | set(tactical_map.keys())
    effective: list[EffectiveAllocationRead] = []
    for block_id in sorted(all_blocks):
        s = strategic_map.get(block_id)
        t = tactical_map.get(block_id)
        s_weight = s.target_weight if s else Decimal("0")
        t_weight = t.overweight if t else Decimal("0")
        effective.append(
            EffectiveAllocationRead(
                profile=profile,
                block_id=block_id,
                strategic_weight=s.target_weight if s else None,
                tactical_overweight=t.overweight if t else None,
                effective_weight=s_weight + t_weight,
                min_weight=s.min_weight if s else None,
                max_weight=s.max_weight if s else None,
            )
        )
    return effective


@router.post(
    "/{profile}/simulate",
    response_model=SimulationResult,
    summary="Simulate allocation change",
    description=(
        "Accepts a proposed weight map and returns projected CVaR impact "
        "against the profile's risk limit. Synchronous — no background jobs."
    ),
)
async def simulate_allocation(
    profile: str,
    body: AllocationProposal,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> SimulationResult:
    _validate_profile(profile)

    # --- validate weights sum ≈ 1.0 ---
    weights_sum = sum(body.weights.values())
    if abs(weights_sum - Decimal("1")) > Decimal("0.001"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"weights must sum to ~1.0 (tolerance 0.001), got {weights_sum}",
        )

    # --- fetch current snapshot for CVaR limit + current level ---
    snap = await get_latest_snapshot(db, profile)
    cvar_limit = snap.cvar_limit if snap else None
    cvar_current = snap.cvar_current if snap else None

    warnings: list[str] = []

    # --- attempt proposed CVaR computation ---
    proposed_cvar_95_3m: Decimal | None = None
    cvar_delta_vs_current: Decimal | None = None
    cvar_utilization_pct: Decimal | None = None
    tracking_error_expected: Decimal | None = None  # TODO: requires full quant pipeline

    try:
        import numpy as np

        from app.domains.wealth.models.instrument import Instrument
        from app.domains.wealth.services.quant_queries import fetch_returns_matrix
        from quant_engine.cvar_service import compute_cvar_from_returns

        # --- map instrument_ids → block_ids via Instrument table ---
        instrument_ids = list(body.weights.keys())
        inst_stmt = (
            select(Instrument.instrument_id, Instrument.block_id)
            .where(Instrument.instrument_id.in_([uuid.UUID(iid) for iid in instrument_ids]))
        )
        inst_result = await db.execute(inst_stmt)
        inst_to_block: dict[str, str | None] = {
            str(row.instrument_id): row.block_id for row in inst_result.all()
        }

        # Build ordered block_ids and corresponding weights vector
        block_ids: list[str] = []
        weights_vector: list[float] = []
        unmapped: list[str] = []

        for iid in instrument_ids:
            bid = inst_to_block.get(iid)
            if bid is None:
                unmapped.append(iid)
            else:
                block_ids.append(bid)
                weights_vector.append(float(body.weights[iid]))

        if unmapped:
            warnings.append(
                f"Could not map {len(unmapped)} instrument(s) to blocks: "
                f"{', '.join(unmapped[:5])}. They are excluded from CVaR calculation."
            )

        if len(block_ids) < 2:
            warnings.append(
                "Need at least 2 instruments mapped to blocks for CVaR calculation; "
                f"only {len(block_ids)} mapped."
            )
        else:
            # Fetch aligned daily returns matrix
            returns_matrix, _fund_ids, _eq_w = await fetch_returns_matrix(db, block_ids)

            # Compute portfolio daily returns from weights
            portfolio_returns = returns_matrix @ np.array(weights_vector)

            # Compute CVaR (returns negative loss values)
            cvar_val, _var_val = compute_cvar_from_returns(portfolio_returns, confidence=0.95)

            # Store as positive risk number (absolute value of loss)
            proposed_cvar_95_3m = Decimal(str(round(abs(cvar_val), 6)))

    except Exception as exc:
        warnings.append(f"Could not compute proposed CVaR: {exc}")

    # --- compute delta if both values are available ---
    if proposed_cvar_95_3m is not None and cvar_current is not None:
        cvar_delta_vs_current = proposed_cvar_95_3m - cvar_current

    # --- compute utilization if limit is known ---
    if proposed_cvar_95_3m is not None and cvar_limit is not None and cvar_limit != 0:
        cvar_utilization_pct = (proposed_cvar_95_3m / cvar_limit) * Decimal("100")

    # --- determine within_limit ---
    if proposed_cvar_95_3m is not None and cvar_limit is not None:
        within_limit = abs(proposed_cvar_95_3m) <= abs(cvar_limit)
    elif cvar_limit is None:
        within_limit = True
        warnings.append("No CVaR limit configured for this profile; cannot validate constraint.")
    else:
        # proposed CVaR unavailable — optimistic default with warning
        within_limit = True
        warnings.append("Proposed CVaR could not be computed; within_limit is assumed true.")

    return SimulationResult(
        profile=profile,
        proposed_cvar_95_3m=proposed_cvar_95_3m,
        cvar_limit=cvar_limit,
        cvar_utilization_pct=cvar_utilization_pct,
        cvar_delta_vs_current=cvar_delta_vs_current,
        tracking_error_expected=tracking_error_expected,
        within_limit=within_limit,
        warnings=warnings,
        computed_at=datetime.now(timezone.utc),
    )

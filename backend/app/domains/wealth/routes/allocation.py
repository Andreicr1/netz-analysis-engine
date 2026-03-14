from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user, require_ic_member
from app.database import get_db
from app.domains.wealth.models.allocation import StrategicAllocation, TacticalPosition
from app.domains.wealth.schemas.allocation import (
    EffectiveAllocationRead,
    StrategicAllocationRead,
    StrategicAllocationUpdate,
    TacticalPositionRead,
    TacticalPositionUpdate,
)
from app.routers.common import validate_profile as _validate_profile

router = APIRouter(prefix="/allocation")


@router.get(
    "/{profile}/strategic",
    response_model=list[StrategicAllocationRead],
    summary="Current strategic weights",
    description="Returns the currently effective IC-approved strategic allocation for a profile.",
)
async def get_strategic(
    profile: str,
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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
    db: AsyncSession = Depends(get_db),
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

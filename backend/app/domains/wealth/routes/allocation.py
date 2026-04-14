import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import CurrentUser, get_current_user, require_ic_member
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.allocation import (
    MacroRegimeSnapshot,
    StrategicAllocation,
    TaaRegimeState,
    TacticalPosition,
)
from app.domains.wealth.models.benchmark_nav import BenchmarkNav
from app.domains.wealth.models.block import AllocationBlock
from app.domains.wealth.routes.common import get_latest_snapshot
from app.domains.wealth.routes.common import validate_profile as _validate_profile
from app.domains.wealth.schemas.allocation import (
    AllocationProposal,
    EffectiveAllocationRead,
    EffectiveAllocationWithRegimeRead,
    EffectiveBandRead,
    GlobalRegimeRead,
    RegimeBandRange,
    RegimeBandsRead,
    RegimeOverlayRead,
    SimulationResult,
    StrategicAllocationRead,
    StrategicAllocationUpdate,
    TaaHistoryRead,
    TaaHistoryRow,
    TacticalPositionRead,
    TacticalPositionUpdate,
)

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
            | (StrategicAllocation.effective_to > today),
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
        | (StrategicAllocation.effective_to > today),
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
            source=getattr(item, "source", None) or "ic_manual",
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
        | (StrategicAllocation.effective_to > today),
    )
    strategic_result = await db.execute(strategic_stmt)
    strategic_map: dict[str, StrategicAllocation] = {
        row.block_id: row for row in strategic_result.scalars().all()
    }

    # Get tactical positions — ic_manual overrides regime_auto for same block.
    # If an ic_manual position is expired (valid_to < today), regime_auto resumes.
    tactical_stmt = select(TacticalPosition).where(
        TacticalPosition.profile == profile,
        TacticalPosition.valid_from <= today,
        (TacticalPosition.valid_to.is_(None)) | (TacticalPosition.valid_to >= today),
    )
    tactical_result = await db.execute(tactical_stmt)
    tactical_map: dict[str, TacticalPosition] = {}
    for row in tactical_result.scalars().all():
        existing = tactical_map.get(row.block_id)
        if existing is None:
            tactical_map[row.block_id] = row
        else:
            # ic_manual always wins over regime_auto / model_signal
            row_source = row.source or "ic_manual"
            existing_source = existing.source or "ic_manual"
            if row_source == "ic_manual" and existing_source != "ic_manual":
                tactical_map[row.block_id] = row
            elif existing_source == "ic_manual":
                pass  # keep ic_manual
            elif row.created_at > existing.created_at:
                tactical_map[row.block_id] = row  # latest non-manual wins

    all_blocks = set(strategic_map.keys()) | set(tactical_map.keys())
    effective: list[EffectiveAllocationRead] = []
    for block_id in sorted(all_blocks):
        s = strategic_map.get(block_id)
        t = tactical_map.get(block_id)
        s_weight = s.target_weight if s else Decimal(0)
        t_weight = t.overweight if t else Decimal(0)
        effective.append(
            EffectiveAllocationRead(
                profile=profile,
                block_id=block_id,
                strategic_weight=s.target_weight if s else None,
                tactical_overweight=t.overweight if t else None,
                effective_weight=s_weight + t_weight,
                min_weight=s.min_weight if s else None,
                max_weight=s.max_weight if s else None,
            ),
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
    if abs(weights_sum - Decimal(1)) > Decimal("0.001"):
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

        from app.domains.wealth.models.instrument_org import InstrumentOrg
        from app.domains.wealth.services.quant_queries import fetch_returns_matrix
        from quant_engine.cvar_service import compute_cvar_from_returns

        # --- map instrument_ids → block_ids via InstrumentOrg table ---
        instrument_ids = list(body.weights.keys())
        inst_stmt = (
            select(InstrumentOrg.instrument_id, InstrumentOrg.block_id)
            .where(InstrumentOrg.instrument_id.in_([uuid.UUID(iid) for iid in instrument_ids]))
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
                f"{', '.join(unmapped[:5])}. They are excluded from CVaR calculation.",
            )

        if len(block_ids) < 2:
            warnings.append(
                "Need at least 2 instruments mapped to blocks for CVaR calculation; "
                f"only {len(block_ids)} mapped.",
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
        cvar_utilization_pct = (proposed_cvar_95_3m / cvar_limit) * Decimal(100)

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
        computed_at=datetime.now(UTC),
    )


@router.get(
    "/regime",
    response_model=GlobalRegimeRead,
    summary="Current global market regime",
    description="Returns the latest global regime snapshot. No org context needed — "
    "market conditions are the same for all tenants.",
)
async def get_global_regime(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> GlobalRegimeRead:
    stmt = (
        select(MacroRegimeSnapshot)
        .order_by(MacroRegimeSnapshot.as_of_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    snapshot = result.scalar_one_or_none()

    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No regime snapshot available. The regime_detection worker may not have run yet.",
        )

    return GlobalRegimeRead(
        as_of_date=snapshot.as_of_date,
        raw_regime=snapshot.raw_regime,
        stress_score=snapshot.stress_score,
        signal_details=snapshot.signal_details,
        signal_breakdown=snapshot.signal_breakdown or [],
    )


_PERIOD_DAYS: dict[str, int] = {
    "1Y": 365,
    "2Y": 730,
    "3Y": 1095,
    "5Y": 1825,
}


@router.get(
    "/regime-overlay",
    response_model=RegimeOverlayRead,
    summary="Regime history overlay for charting",
    description=(
        "Returns S&P500 NAV + collapsed regime bands for a given period. "
        "Global data (no org context) — used for the Builder REGIME tab chart."
    ),
)
async def get_regime_overlay(
    period: Literal["1Y", "2Y", "3Y", "5Y"] = Query(default="3Y"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RegimeOverlayRead:
    start_date = date.today() - timedelta(days=_PERIOD_DAYS[period])

    # Resolve SPY block_id dynamically
    spy_block_stmt = (
        select(AllocationBlock.block_id)
        .where(AllocationBlock.benchmark_ticker == "SPY")
        .limit(1)
    )
    spy_block_result = await db.execute(spy_block_stmt)
    spy_block_id = spy_block_result.scalar_one_or_none()

    # Fetch SPY NAV
    dates: list[date] = []
    spy_values: list[float] = []
    if spy_block_id is not None:
        nav_stmt = (
            select(BenchmarkNav.nav_date, BenchmarkNav.nav)
            .where(
                BenchmarkNav.block_id == spy_block_id,
                BenchmarkNav.nav_date >= start_date,
            )
            .order_by(BenchmarkNav.nav_date.asc())
        )
        nav_result = await db.execute(nav_stmt)
        for row in nav_result.all():
            dates.append(row.nav_date)
            spy_values.append(float(row.nav))

    # Fetch regime history
    regime_stmt = (
        select(MacroRegimeSnapshot.as_of_date, MacroRegimeSnapshot.raw_regime)
        .where(MacroRegimeSnapshot.as_of_date >= start_date)
        .order_by(MacroRegimeSnapshot.as_of_date.asc())
    )
    regime_result = await db.execute(regime_stmt)
    regime_rows = regime_result.all()

    # Collapse consecutive same-regime rows into contiguous bands
    regime_bands: list[RegimeBandRange] = []
    current_band: dict[str, object] | None = None
    for row in regime_rows:
        d = row.as_of_date
        r = row.raw_regime
        if current_band is None or current_band["regime"] != r:
            if current_band is not None:
                regime_bands.append(
                    RegimeBandRange(
                        start=current_band["start"],  # type: ignore[arg-type]
                        end=current_band["end"],  # type: ignore[arg-type]
                        regime=current_band["regime"],  # type: ignore[arg-type]
                    )
                )
            current_band = {"start": d, "end": d, "regime": r}
        else:
            current_band["end"] = d
    if current_band is not None:
        regime_bands.append(
            RegimeBandRange(
                start=current_band["start"],  # type: ignore[arg-type]
                end=current_band["end"],  # type: ignore[arg-type]
                regime=current_band["regime"],  # type: ignore[arg-type]
            )
        )

    return RegimeOverlayRead(
        dates=dates,
        spy_values=spy_values,
        regime_bands=regime_bands,
        period=period,
    )


# ── TAA routes (Sprint 3) ───────────────────────────────────────


@router.get(
    "/{profile}/regime-bands",
    response_model=RegimeBandsRead,
    summary="Current regime bands",
    description=(
        "Returns the current smoothed regime centers and effective "
        "optimizer bands for a profile. Includes IPS clamps and "
        "transition velocity for audit."
    ),
)
async def get_regime_bands(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RegimeBandsRead:
    _validate_profile(profile)

    # Fetch latest taa_regime_state row
    stmt = (
        select(TaaRegimeState)
        .where(TaaRegimeState.profile == profile)
        .order_by(TaaRegimeState.as_of_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    taa = result.scalar_one_or_none()

    if taa is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No TAA regime state found for profile '{profile}'. "
            "The risk_calc worker may not have run yet.",
        )

    effective_bands_raw: dict[str, dict[str, float]] = taa.effective_bands or {}
    effective_bands = {
        bid: EffectiveBandRead(**band_data)
        for bid, band_data in effective_bands_raw.items()
    }

    # Determine IPS clamps by comparing with strategic allocation
    ips_clamps: list[str] = []
    strategic_stmt = select(StrategicAllocation).where(
        StrategicAllocation.profile == profile,
        StrategicAllocation.effective_from <= taa.as_of_date,
        (StrategicAllocation.effective_to.is_(None))
        | (StrategicAllocation.effective_to > taa.as_of_date),
    )
    strategic_result = await db.execute(strategic_stmt)
    for sa in strategic_result.scalars().all():
        band = effective_bands_raw.get(sa.block_id)
        if band is None:
            continue
        if band.get("min", 0) > float(sa.min_weight) + 1e-6:
            ips_clamps.append(f"{sa.block_id}_min_raised")
        if band.get("max", 1) < float(sa.max_weight) - 1e-6:
            ips_clamps.append(f"{sa.block_id}_max_lowered")

    return RegimeBandsRead(
        profile=profile,
        as_of_date=taa.as_of_date,
        raw_regime=taa.raw_regime,
        stress_score=taa.stress_score,
        smoothed_centers=taa.smoothed_centers or {},
        effective_bands=effective_bands,
        transition_velocity=taa.transition_velocity,
        ips_clamps_applied=ips_clamps,
    )


@router.get(
    "/{profile}/taa-history",
    response_model=TaaHistoryRead,
    summary="TAA regime state history",
    description=(
        "Returns the time series of TAA regime states for a profile. "
        "Ordered newest-first. Supports pagination via limit/offset."
    ),
)
async def get_taa_history(
    profile: str,
    limit: int = Query(default=30, ge=1, le=365),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> TaaHistoryRead:
    _validate_profile(profile)

    # Total count
    count_stmt = (
        select(func.count())
        .select_from(TaaRegimeState)
        .where(TaaRegimeState.profile == profile)
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # Rows
    stmt = (
        select(TaaRegimeState)
        .where(TaaRegimeState.profile == profile)
        .order_by(TaaRegimeState.as_of_date.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    rows = [TaaHistoryRow.model_validate(row) for row in result.scalars().all()]

    return TaaHistoryRead(profile=profile, rows=rows, total=total)


@router.get(
    "/{profile}/effective-with-regime",
    response_model=list[EffectiveAllocationWithRegimeRead],
    summary="Effective allocation with regime bands",
    description=(
        "Computed effective allocation enriched with current regime-adjusted "
        "bands. Combines strategic + tactical + TAA regime data."
    ),
)
async def get_effective_with_regime(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[EffectiveAllocationWithRegimeRead]:
    _validate_profile(profile)
    today = date.today()

    # Get strategic allocations
    strategic_stmt = select(StrategicAllocation).where(
        StrategicAllocation.profile == profile,
        StrategicAllocation.effective_from <= today,
        (StrategicAllocation.effective_to.is_(None))
        | (StrategicAllocation.effective_to > today),
    )
    strategic_result = await db.execute(strategic_stmt)
    strategic_map: dict[str, StrategicAllocation] = {
        row.block_id: row for row in strategic_result.scalars().all()
    }

    # Get tactical positions (ic_manual > regime_auto)
    tactical_stmt = select(TacticalPosition).where(
        TacticalPosition.profile == profile,
        TacticalPosition.valid_from <= today,
        (TacticalPosition.valid_to.is_(None)) | (TacticalPosition.valid_to >= today),
    )
    tactical_result = await db.execute(tactical_stmt)
    tactical_map: dict[str, TacticalPosition] = {}
    for row in tactical_result.scalars().all():
        existing = tactical_map.get(row.block_id)
        if existing is None:
            tactical_map[row.block_id] = row
        else:
            row_source = row.source or "ic_manual"
            existing_source = existing.source or "ic_manual"
            if row_source == "ic_manual" and existing_source != "ic_manual":
                tactical_map[row.block_id] = row
            elif existing_source == "ic_manual":
                pass
            elif row.created_at > existing.created_at:
                tactical_map[row.block_id] = row

    # Get latest TAA regime state
    taa_stmt = (
        select(TaaRegimeState)
        .where(TaaRegimeState.profile == profile)
        .order_by(TaaRegimeState.as_of_date.desc())
        .limit(1)
    )
    taa_result = await db.execute(taa_stmt)
    taa = taa_result.scalar_one_or_none()
    regime_bands: dict[str, dict[str, float]] = (taa.effective_bands or {}) if taa else {}

    all_blocks = set(strategic_map.keys()) | set(tactical_map.keys())
    effective: list[EffectiveAllocationWithRegimeRead] = []
    for block_id in sorted(all_blocks):
        s = strategic_map.get(block_id)
        t = tactical_map.get(block_id)
        s_weight = s.target_weight if s else Decimal(0)
        t_weight = t.overweight if t else Decimal(0)
        band = regime_bands.get(block_id)
        effective.append(
            EffectiveAllocationWithRegimeRead(
                profile=profile,
                block_id=block_id,
                strategic_weight=s.target_weight if s else None,
                tactical_overweight=t.overweight if t else None,
                effective_weight=s_weight + t_weight,
                min_weight=s.min_weight if s else None,
                max_weight=s.max_weight if s else None,
                regime_min=band.get("min") if band else None,
                regime_max=band.get("max") if band else None,
                regime_center=band.get("center") if band else None,
            ),
        )

    # Audit: log TAA state access for institutional compliance
    if taa is not None:
        await write_audit_event(
            db,
            actor_id=user.actor_id,
            action="taa_state_viewed",
            entity_type="TaaRegimeState",
            entity_id=str(taa.id),
            after={
                "profile": profile,
                "raw_regime": taa.raw_regime,
                "as_of_date": taa.as_of_date.isoformat(),
            },
        )

    return effective

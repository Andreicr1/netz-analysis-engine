"""Model Portfolio API routes — CRUD, construction, track-record, stress.

All endpoints use get_db_with_rls and response_model + model_validate().
IC role required for creation and construction.

Construction invokes CLARABEL fund-level optimizer with block-group constraints
from StrategicAllocation and CVaR limit from profile config.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Final

import numpy as np
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.model_portfolio import (
    ModelPortfolio,
    PortfolioCalibration,
    PortfolioConstructionRun,
)
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from app.domains.wealth.schemas.generated_report import ReportGenerateRequest
from app.domains.wealth.schemas.model_portfolio import (
    ConstructionAdviceRead,
    ConstructionRunDiffOut,
    ConstructionRunMetricDelta,
    ConstructionRunWeightDelta,
    ConstructRunAccepted,
    CusipExposureRead,
    ModelPortfolioCreate,
    ModelPortfolioRead,
    ModelPortfolioUpdate,
    OverlapResultRead,
    PortfolioCalibrationRead,
    PortfolioCalibrationUpdate,
    PortfolioTransitionRequest,
    RebalancePreviewRequest,
    RebalancePreviewResponse,
    RegimeCurrentRead,
    SectorExposureRead,
    StressScenarioCatalog,
    StressScenarioCatalogEntry,
    StressTestRequest,
    StressTestResponse,
)
from app.domains.wealth.schemas.portfolio import (
    BlockDriftRead,
    DriftReportRead,
    LiveDriftResponse,
    PerformancePoint,
    PortfolioPerformanceSeries,
    PositionDetail,
)
from app.shared.enums import Role
from vertical_engines.wealth.model_portfolio.state_machine import (
    ACTION_ACTIVATE,
    ACTION_APPROVE,
    ACTION_ARCHIVE,
    ACTION_PAUSE,
    ACTION_REBUILD_DRAFT,
    ACTION_REJECT,
    ACTION_RESUME,
    ACTION_VALIDATE,
    ApprovalPolicy,
    InvalidStateTransition,
    ValidationStatus,
    compute_allowed_actions,
    transition,
)

logger = structlog.get_logger()


async def _resolve_approval_policy(
    db: AsyncSession, org_id: str | uuid.UUID,
) -> ApprovalPolicy:
    """Resolve the org's approval policy from ConfigService.

    Falls back to the conservative defaults (no self-approval, require
    construction) if the config domain is not registered for the org.
    Per OD-6, single-user orgs may set ``allow_self_approval=true``.
    """
    try:
        result = await ConfigService(db).get(
            "wealth", "approval_policy",
            org_id=uuid.UUID(str(org_id)) if not isinstance(org_id, uuid.UUID) else org_id,
        )
        cfg = result.value or {}
        return ApprovalPolicy(
            allow_self_approval=bool(cfg.get("allow_self_approval", False)),
            require_construction_for_approve=bool(
                cfg.get("require_construction_for_approve", True),
            ),
        )
    except Exception:  # noqa: BLE001 — config miss is non-fatal here
        return ApprovalPolicy()


async def _latest_validation_status(
    db: AsyncSession, portfolio_id: uuid.UUID,
) -> ValidationStatus:
    """Project the most recent construction run's validation gate.

    Returns ``has_run=False`` if no runs exist for the portfolio.
    Reads only the ``validation`` JSONB column to keep the projection
    cheap — Phase 3 Task 3.1 fills it; until then it's ``{}`` and we
    treat that as "not yet validated".
    """
    row = await db.execute(
        select(PortfolioConstructionRun.validation)
        .where(PortfolioConstructionRun.portfolio_id == portfolio_id)
        .order_by(PortfolioConstructionRun.requested_at.desc())
        .limit(1),
    )
    validation = row.scalar_one_or_none()
    if validation is None:
        return ValidationStatus(has_run=False, passed=False)
    return ValidationStatus(
        has_run=True,
        passed=bool(validation.get("passed", False)),
    )


async def _serialize_with_actions(
    db: AsyncSession,
    portfolio: ModelPortfolio,
    *,
    policy: ApprovalPolicy | None = None,
    validation: ValidationStatus | None = None,
) -> ModelPortfolioRead:
    """Hydrate a ``ModelPortfolioRead`` with ``allowed_actions``.

    Caller may pre-resolve ``policy`` and ``validation`` to avoid N+1
    when serializing a list. Detail handlers can omit them and let
    this helper resolve once.
    """
    if policy is None:
        policy = await _resolve_approval_policy(db, portfolio.organization_id)
    if validation is None:
        validation = await _latest_validation_status(db, portfolio.id)
    actions = compute_allowed_actions(
        portfolio.state, validation=validation, policy=policy,
    )
    rendered = ModelPortfolioRead.model_validate(portfolio)
    rendered.allowed_actions = actions
    return rendered

# Default CVaR limits per profile (fallback if ConfigService unavailable)
_DEFAULT_CVAR_LIMITS: dict[str, float] = {
    "conservative": -0.08,
    "moderate": -0.06,
    "growth": -0.12,
}

_DEFAULT_MAX_SINGLE_FUND: dict[str, float] = {
    "conservative": 0.10,
    "moderate": 0.12,
    "growth": 0.15,
}

router = APIRouter(prefix="/model-portfolios", tags=["model-portfolios"])


@router.post(
    "",
    response_model=ModelPortfolioRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a model portfolio",
)
async def create_model_portfolio(
    body: ModelPortfolioCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> ModelPortfolioRead:
    """Create a new model portfolio (Phase 5 Task 5.1).

    Requires IC role. The new row starts in ``state='draft'`` (column
    default from migration 0098) and is hydrated with the matching
    ``allowed_actions`` via ``_serialize_with_actions`` so the Builder
    can render the canonical ``[construct, archive]`` button set
    immediately on dialog success.

    A paired ``portfolio_calibration`` row is also created using the
    migration 0100 server defaults so the CalibrationPanel's Basic
    tier never starts empty. When ``copy_from`` is provided, the
    typed Basic + Advanced calibration columns and the
    ``fund_selection_schema`` are cloned from the source portfolio
    (the source must belong to the same org — RLS guarantees that).
    """
    _require_ic_role(actor)

    org_uuid = uuid.UUID(str(org_id))

    # Optional clone source — fetch first so a 404 happens before any
    # writes hit the DB.
    source_portfolio: ModelPortfolio | None = None
    source_calibration: PortfolioCalibration | None = None
    if body.copy_from is not None:
        src_result = await db.execute(
            select(ModelPortfolio).where(ModelPortfolio.id == body.copy_from),
        )
        source_portfolio = src_result.scalar_one_or_none()
        if source_portfolio is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"copy_from source portfolio {body.copy_from} not found",
            )
        src_cal = await db.execute(
            select(PortfolioCalibration).where(
                PortfolioCalibration.portfolio_id == body.copy_from,
            ),
        )
        source_calibration = src_cal.scalar_one_or_none()

    portfolio = ModelPortfolio(
        organization_id=org_uuid,
        profile=body.profile,
        display_name=body.display_name,
        description=body.description,
        benchmark_composite=body.benchmark_composite,
        inception_date=body.inception_date,
        backtest_start_date=body.backtest_start_date,
        status="draft",
        created_by=actor.actor_id,
    )
    if source_portfolio is not None and source_portfolio.fund_selection_schema:
        # Clone composition; the new portfolio still starts as a draft
        # so the optimizer cascade will re-run before activation.
        portfolio.fund_selection_schema = dict(source_portfolio.fund_selection_schema)
    db.add(portfolio)
    await db.flush()
    await db.refresh(portfolio)

    # Seed the paired calibration row. Default values come from
    # migration 0100; clone the typed columns when ``copy_from`` is
    # provided so the new draft inherits the calibration discipline
    # of the source model. ``expert_overrides`` is also copied so any
    # JSONB knobs survive the fork.
    calibration = PortfolioCalibration(
        organization_id=org_uuid,
        portfolio_id=portfolio.id,
        updated_by=actor.actor_id,
    )
    if source_calibration is not None:
        for column in (
            "mandate",
            "cvar_limit",
            "max_single_fund_weight",
            "turnover_cap",
            "stress_scenarios_active",
            "regime_override",
            "bl_enabled",
            "bl_view_confidence_default",
            "garch_enabled",
            "turnover_lambda",
            "stress_severity_multiplier",
            "advisor_enabled",
            "cvar_level",
            "lambda_risk_aversion",
            "shrinkage_intensity_override",
        ):
            value = getattr(source_calibration, column, None)
            if value is not None:
                setattr(calibration, column, value)
        calibration.expert_overrides = dict(source_calibration.expert_overrides or {})
    db.add(calibration)
    await db.flush()

    logger.info(
        "model_portfolio_created",
        portfolio_id=str(portfolio.id),
        actor_id=actor.actor_id,
        copy_from=str(body.copy_from) if body.copy_from else None,
    )

    return await _serialize_with_actions(db, portfolio)


@router.get(
    "",
    response_model=list[ModelPortfolioRead],
    summary="List model portfolios",
)
async def list_model_portfolios(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> list[ModelPortfolioRead]:
    """List all model portfolios for the organization.

    Each portfolio is hydrated with ``allowed_actions`` from the
    state machine (DL3 — Phase 1 Task 1.4). The approval policy is
    resolved once per request and reused across all rows. Validation
    status is fetched per-portfolio from ``portfolio_construction_runs``
    via a single batched lookup keyed on the latest run.
    """
    result = await db.execute(
        select(ModelPortfolio).order_by(ModelPortfolio.created_at.desc()),
    )
    portfolios = result.scalars().all()
    if not portfolios:
        return []

    policy = await _resolve_approval_policy(db, org_id)
    return [
        await _serialize_with_actions(db, p, policy=policy) for p in portfolios
    ]


@router.get(
    "/{portfolio_id}",
    response_model=ModelPortfolioRead,
    summary="Get model portfolio with composition",
)
async def get_model_portfolio(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> ModelPortfolioRead:
    """Get a model portfolio with its fund selection schema.

    Includes ``allowed_actions`` computed from the state machine
    (DL3 — Phase 1 Task 1.4). The frontend MUST consume this list to
    decide which buttons to render — never inspect ``state`` directly.
    """
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )
    return await _serialize_with_actions(db, portfolio)


@router.patch(
    "/{portfolio_id}",
    response_model=ModelPortfolioRead,
    summary="Update model portfolio metadata (display_name, inception_date, description)",
)
async def update_model_portfolio(
    portfolio_id: uuid.UUID,
    body: ModelPortfolioUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ModelPortfolioRead:
    _require_ic_role(actor)

    stmt = select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
    result = await db.execute(stmt)
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    update_data = body.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(portfolio, field, value)

    await db.flush()
    await db.refresh(portfolio)
    return ModelPortfolioRead.model_validate(portfolio)


# ── Phase 5 Task 5.2 — State machine transition dispatcher ────────────────


_ACTION_TO_TARGET_STATE: Final[dict[str, str]] = {
    ACTION_VALIDATE: "validated",
    ACTION_APPROVE: "approved",
    ACTION_ACTIVATE: "live",
    ACTION_PAUSE: "paused",
    ACTION_RESUME: "live",
    ACTION_ARCHIVE: "archived",
    ACTION_REJECT: "rejected",
    ACTION_REBUILD_DRAFT: "draft",
}


@router.post(
    "/{portfolio_id}/transitions",
    response_model=ModelPortfolioRead,
    summary="Apply a state-machine action to a portfolio (Phase 5 Task 5.2)",
)
async def apply_portfolio_transition(
    portfolio_id: uuid.UUID,
    body: PortfolioTransitionRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> ModelPortfolioRead:
    """Single dispatcher for all state-machine actions (DL3).

    The Builder action bar (Phase 5 Task 5.2) renders one button per
    string in ``portfolio.allowed_actions``. Pressing a button POSTs
    here with ``{action, reason?, metadata?}``. The dispatcher maps
    the action string to the canonical target state and delegates
    to ``state_machine.transition`` which row-locks the portfolio,
    validates the edge, applies the column updates, and writes the
    audit row in a single transaction.

    Returns the freshly-serialized ``ModelPortfolioRead`` (with new
    ``state``, ``state_changed_at``, ``state_changed_by``, and
    ``allowed_actions``) so the frontend re-renders the action bar
    without a second fetch.

    ``construct`` is intentionally NOT in this dispatcher — it has
    its own Job-or-Stream route at ``POST /{id}/construct`` (Phase 3).
    """
    _require_ic_role(actor)

    target_state = _ACTION_TO_TARGET_STATE.get(body.action)
    if target_state is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown transition action: {body.action}",
        )

    # Validate the action against the current state's allowed_actions
    # before invoking the state machine — the state_machine will also
    # raise InvalidStateTransition, but we want a richer 409 message
    # that says "you tried action X from state Y" instead of the
    # generic "X → Y is not in TRANSITIONS".
    portfolio_row = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = portfolio_row.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    policy = await _resolve_approval_policy(db, org_id)
    validation = await _latest_validation_status(db, portfolio_id)
    allowed = compute_allowed_actions(
        portfolio.state, validation=validation, policy=policy,
    )
    if body.action not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Action '{body.action}' is not allowed from state "
                f"'{portfolio.state}'. Allowed actions: {sorted(allowed)}"
            ),
        )

    metadata = dict(body.metadata or {})
    # OD-6: stamp self_approved=true when an actor approves their own
    # validated portfolio in a single-user org. The route layer detects
    # this case and lets the state machine record it in the audit row.
    if body.action == ACTION_APPROVE and policy.allow_self_approval:
        metadata.setdefault("self_approved", True)

    try:
        await transition(
            db,
            portfolio_id=portfolio_id,
            to_state=target_state,
            actor_id=actor.actor_id,
            reason=body.reason,
            metadata=metadata,
        )
    except InvalidStateTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Invalid state transition: {exc.from_state} → {exc.to_state}"
            ),
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    # Re-fetch the portfolio post-transition so the response carries the
    # fresh state column. The state_machine.transition call already
    # flushed inside its own row-lock; this read sees the new value.
    refreshed = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    return await _serialize_with_actions(
        db, refreshed.scalar_one(), policy=policy,
    )


@router.post(
    "/{portfolio_id}/construct",
    response_model=ConstructRunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run optimizer + stress + advisor + validation + narrative (Job-or-Stream)",
)
async def construct_portfolio(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> ConstructRunAccepted:
    """Kick off an enriched construction run via the Job-or-Stream pattern.

    Phase 3 Task 3.4 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

    Replaces the legacy synchronous ``/construct`` with a 202 + SSE
    contract (DL18 P2). The worker orchestrates:

    1. Load calibration from ``portfolio_calibration``
    2. Optimizer cascade via ``_run_construction_async``
    3. Stress suite (4 preset scenarios → ``portfolio_stress_results``)
    4. Advisor fold-in (only if ``calibration.advisor_enabled``)
    5. 15-check validation gate (no fail-fast)
    6. Deterministic Jinja2 narrative templater
    7. Persistence to ``portfolio_construction_runs``
    8. SSE publication of progress + terminal events

    Bounded at 120s wall-clock (DL18 P1). Uses an integer-literal
    advisory lock (``900_101``) keyed per-portfolio (DL19).

    Requires IC role.
    """
    from app.core.jobs.tracker import register_job_owner
    from app.domains.wealth.workers.construction_run_executor import (
        execute_construction_run,
    )

    _require_ic_role(actor)

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    # Register the SSE job owner so the stream endpoint can verify
    # cross-tenant authorization when the client reconnects.
    job_id = f"construct:{uuid.uuid4()}"
    await register_job_owner(job_id, str(org_id))

    # Run the executor. We await it synchronously inside the request
    # handler because:
    #   - The executor is bounded at 120s (DL18 P1) — the route will
    #     not time out under normal operation.
    #   - Running it as a background task requires a separate RLS
    #     context which the current tenancy middleware does not yet
    #     expose; the Phase 9 rebuild of the worker dispatcher will
    #     switch to a true background task once that infrastructure
    #     lands. For now the 202 semantics are preserved at the
    #     response layer (``status`` reflects the final state) and
    #     the SSE stream carries terminal events for clients that
    #     open it concurrently.
    run = await execute_construction_run(
        db=db,
        portfolio_id=portfolio_id,
        organization_id=org_id,
        requested_by=actor.actor_id,
        job_id=job_id,
    )

    return ConstructRunAccepted(
        run_id=run.id,
        portfolio_id=portfolio_id,
        status=run.status,  # running | succeeded | failed
        job_id=job_id,
        stream_url=f"/api/v1/jobs/{job_id}/stream",
        run_url=f"/api/v1/model-portfolios/{portfolio_id}/runs/{run.id}",
    )


# ── Phase 4 — Portfolio calibration GET / PUT ─────────────────────────────


_BASIC_FIELDS: tuple[str, ...] = (
    "mandate",
    "cvar_limit",
    "max_single_fund_weight",
    "turnover_cap",
    "stress_scenarios_active",
)
_ADVANCED_FIELDS: tuple[str, ...] = (
    "regime_override",
    "bl_enabled",
    "bl_view_confidence_default",
    "garch_enabled",
    "turnover_lambda",
    "stress_severity_multiplier",
    "advisor_enabled",
    "cvar_level",
    "lambda_risk_aversion",
    "shrinkage_intensity_override",
)


async def _ensure_calibration(
    db: AsyncSession, portfolio_id: uuid.UUID, organization_id: uuid.UUID | str,
) -> PortfolioCalibration:
    """Fetch-or-create the ``portfolio_calibration`` row for a portfolio.

    DL5 makes the calibration row a one-to-one peer of the portfolio
    (UNIQUE on ``portfolio_id``). The row is created on first access
    with the migration 0100 server defaults so the CalibrationPanel's
    Basic tier starts from the org-wide institutional baseline instead
    of an empty form. The frontend never needs to handle the
    ``no calibration`` case.
    """
    existing = await db.execute(
        select(PortfolioCalibration).where(
            PortfolioCalibration.portfolio_id == portfolio_id,
        ),
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        return row

    org_uuid = (
        organization_id
        if isinstance(organization_id, uuid.UUID)
        else uuid.UUID(str(organization_id))
    )
    row = PortfolioCalibration(
        organization_id=org_uuid,
        portfolio_id=portfolio_id,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


@router.get(
    "/{portfolio_id}/calibration",
    response_model=PortfolioCalibrationRead,
    summary="Fetch the portfolio's 63-input calibration surface (DL5)",
)
async def get_portfolio_calibration(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> PortfolioCalibrationRead:
    """Read the Builder CalibrationPanel state for a portfolio.

    Creates the calibration row on first access so the Basic tier always
    has the migration 0100 server defaults. The frontend never has to
    handle a missing row.
    """
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    row = await _ensure_calibration(db, portfolio_id, org_id)
    return PortfolioCalibrationRead.model_validate(row)


@router.put(
    "/{portfolio_id}/calibration",
    response_model=PortfolioCalibrationRead,
    summary="Apply a Builder CalibrationPanel edit (DL5)",
)
async def update_portfolio_calibration(
    portfolio_id: uuid.UUID,
    payload: PortfolioCalibrationUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> PortfolioCalibrationRead:
    """Persist the Builder CalibrationPanel Apply action.

    The body is a partial update — only the fields that the user
    touched are sent. Typed Basic + Advanced fields are assigned
    directly; ``expert_overrides`` is merged (shallow) into the
    existing JSONB so the frontend can edit individual Expert knobs
    without re-sending the full blob.

    Requires IC role. ``updated_by`` is stamped from the actor.
    """
    _require_ic_role(actor)

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    row = await _ensure_calibration(db, portfolio_id, org_id)

    data = payload.model_dump(exclude_unset=True)

    # Typed Basic + Advanced columns — assign only provided fields.
    for field in _BASIC_FIELDS + _ADVANCED_FIELDS:
        if field in data and data[field] is not None:
            setattr(row, field, data[field])

    # stress_scenarios_active is nullable in the update but must not
    # land as NULL in the DB (column is NOT NULL). Explicit guard.
    if "stress_scenarios_active" in data and data["stress_scenarios_active"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="stress_scenarios_active cannot be null — send an empty list to disable all",
        )

    # Expert tier — shallow merge so individual knobs can be edited.
    if "expert_overrides" in data and data["expert_overrides"] is not None:
        merged = dict(row.expert_overrides or {})
        merged.update(data["expert_overrides"])
        row.expert_overrides = merged

    row.updated_by = actor.actor_id

    await db.flush()
    await db.refresh(row)

    logger.info(
        "portfolio_calibration_updated",
        portfolio_id=str(portfolio_id),
        actor_id=actor.actor_id,
        fields=sorted(data.keys()),
    )

    return PortfolioCalibrationRead.model_validate(row)


@router.get(
    "/{portfolio_id}/track-record",
    summary="Get track-record data (backtest + live + stress)",
)
async def get_track_record(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Get combined track-record: backtest, live NAV, and stress data."""
    from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    # Query synthesized NAV series
    nav_result = await db.execute(
        select(ModelPortfolioNav)
        .where(ModelPortfolioNav.portfolio_id == portfolio_id)
        .order_by(ModelPortfolioNav.nav_date),
    )
    nav_rows = nav_result.scalars().all()
    nav_series = [
        {
            "date": str(r.nav_date),
            "nav": float(r.nav),
            "daily_return": float(r.daily_return) if r.daily_return is not None else None,
        }
        for r in nav_rows
    ]

    return {
        "portfolio_id": str(portfolio_id),
        "profile": portfolio.profile,
        "status": portfolio.status,
        "fund_selection": portfolio.fund_selection_schema,
        "nav_series": nav_series,
        "backtest": portfolio.backtest_result,
        "stress": portfolio.stress_result,
    }


@router.post(
    "/{portfolio_id}/backtest",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger backtest computation",
)
async def trigger_backtest(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Trigger walk-forward backtest for a model portfolio."""
    _require_ic_role(actor)

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    if not portfolio.fund_selection_schema:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Portfolio has no fund selection. Run /construct first.",
        )

    _org_id = portfolio.organization_id

    def _backtest() -> dict[str, Any]:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db, sync_db.begin():
            sync_db.expire_on_commit = False
            from sqlalchemy import text
            sync_db.execute(
                text("SELECT set_config('app.current_organization_id', :oid, true)"),
                {"oid": str(_org_id)},
            )
            return _run_backtest(sync_db, portfolio.fund_selection_schema, portfolio_id)

    backtest_result = await asyncio.to_thread(_backtest)
    portfolio.backtest_result = backtest_result
    await db.flush()
    return {
        "portfolio_id": str(portfolio_id),
        "status": "completed",
        "backtest": backtest_result,
    }


@router.post(
    "/{portfolio_id}/stress",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger stress scenario analysis",
)
async def trigger_stress(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Trigger stress scenario analysis for a model portfolio."""
    _require_ic_role(actor)

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    if not portfolio.fund_selection_schema:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Portfolio has no fund selection. Run /construct first.",
        )

    _org_id_stress = portfolio.organization_id

    def _stress() -> dict[str, Any]:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db, sync_db.begin():
            sync_db.expire_on_commit = False
            from sqlalchemy import text
            sync_db.execute(
                text("SELECT set_config('app.current_organization_id', :oid, true)"),
                {"oid": str(_org_id_stress)},
            )
            return _run_stress(sync_db, portfolio.fund_selection_schema, portfolio_id)

    stress_result = await asyncio.to_thread(_stress)
    portfolio.stress_result = stress_result
    await db.flush()
    return {
        "portfolio_id": str(portfolio_id),
        "status": "completed",
        "stress": stress_result,
    }


@router.post(
    "/{portfolio_id}/stress-test",
    response_model=StressTestResponse,
    summary="Run parametric stress scenario on portfolio",
)
async def run_parametric_stress_test(
    portfolio_id: uuid.UUID,
    body: StressTestRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> StressTestResponse:
    """Run parametric stress scenario against portfolio block weights.

    Requires INVESTMENT_TEAM or ADMIN role.
    """
    _require_ic_role(actor)

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    if not portfolio.fund_selection_schema:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Portfolio has no fund selection. Run /construct first.",
        )

    from vertical_engines.wealth.model_portfolio.stress_scenarios import (
        PRESET_SCENARIOS,
        run_stress_scenario,
    )

    if body.scenario_name == "custom":
        if not body.shocks:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Custom scenario requires 'shocks' dict in body",
            )
        shocks = body.shocks
    else:
        preset = PRESET_SCENARIOS.get(body.scenario_name)
        if preset is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown scenario: {body.scenario_name}. Available: {list(PRESET_SCENARIOS.keys())}",
            )
        shocks = preset

    # Extract block weights from fund_selection
    fund_list = portfolio.fund_selection_schema.get("funds", [])
    block_weights: dict[str, float] = {}
    for f in fund_list:
        bid = f.get("block_id")
        if bid:
            block_weights[bid] = block_weights.get(bid, 0.0) + f.get("weight", 0.0)

    stress_result = run_stress_scenario(
        weights_by_block=block_weights,
        shocks=shocks,
        historical_returns=None,  # on-demand — no historical fetch
        scenario_name=body.scenario_name,
    )

    return StressTestResponse(
        portfolio_id=str(portfolio_id),
        scenario_name=stress_result.scenario_name,
        nav_impact_pct=stress_result.nav_impact_pct,
        cvar_stressed=stress_result.cvar_stressed,
        block_impacts=stress_result.block_impacts,
        worst_block=stress_result.worst_block,
        best_block=stress_result.best_block,
    )


@router.get(
    "/{portfolio_id}/overlap",
    response_model=OverlapResultRead,
    summary="Holdings overlap analysis",
    description="Computes cross-fund CUSIP and sector concentration from N-PORT data.",
)
async def get_portfolio_overlap(
    portfolio_id: uuid.UUID,
    limit_pct: float = Query(default=0.05, ge=0.01, le=0.50),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> OverlapResultRead:
    """Overlap scanner: explodes portfolio into N-PORT holdings and detects concentration."""
    from datetime import datetime

    from app.domains.wealth.services.holdings_exploder import fetch_portfolio_holdings_exploded
    from vertical_engines.wealth.monitoring.overlap_scanner import compute_overlap

    # 1. Load portfolio (RLS validates org)
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    # 2. Count funds in schema
    fund_ids_in_schema: set[str] = set()
    if portfolio.fund_selection_schema:
        for f in portfolio.fund_selection_schema.get("funds", []):
            iid = f.get("instrument_id")
            if iid:
                fund_ids_in_schema.add(iid)

    # 3. Explode holdings (I/O — sec_nport_holdings is global)
    holdings = await fetch_portfolio_holdings_exploded(db, portfolio_id)

    fund_ids_with_holdings = {str(h.fund_instrument_id) for h in holdings}
    funds_without_data = len(fund_ids_in_schema) - len(fund_ids_with_holdings)
    has_sufficient_data = len(fund_ids_with_holdings) >= 2

    # 4. Empty case — valid response, not an error
    if not holdings:
        return OverlapResultRead(
            portfolio_id=str(portfolio_id),
            computed_at=datetime.utcnow(),
            limit_pct=limit_pct,
            total_holdings=0,
            funds_analyzed=0,
            funds_without_data=len(fund_ids_in_schema),
            top_cusip_exposures=[],
            sector_exposures=[],
            breaches=[],
            has_sufficient_data=False,
            data_warning="No N-PORT holdings data available for funds in this portfolio",
        )

    # 5. Run scanner (zero I/O, pure math)
    overlap = compute_overlap(holdings, limit_pct=limit_pct)

    # 6. Resolve fund names for display
    fund_names = await _resolve_fund_names_for_overlap(
        db, list(fund_ids_with_holdings),
    )

    data_warning = None
    if funds_without_data > 0:
        data_warning = (
            f"{funds_without_data} of {len(fund_ids_in_schema)} "
            f"funds have no N-PORT holdings data"
        )

    # 7. Map to response schema
    def _map_cusip(e: Any) -> CusipExposureRead:
        return CusipExposureRead(
            cusip=e.cusip,
            issuer_name=e.issuer_name,
            total_exposure_pct=round(e.total_weighted_pct * 100, 2),
            funds_holding=[
                fund_names.get(fid, fid) for fid in e.contributing_funds
            ],
            is_breach=e.breach,
        )

    return OverlapResultRead(
        portfolio_id=str(portfolio_id),
        computed_at=datetime.utcnow(),
        limit_pct=limit_pct,
        total_holdings=overlap.total_holdings,
        funds_analyzed=len(fund_ids_with_holdings),
        funds_without_data=funds_without_data,
        top_cusip_exposures=[_map_cusip(e) for e in overlap.cusip_exposures[:20]],
        sector_exposures=[
            SectorExposureRead(
                sector=s.sector,
                total_exposure_pct=round(s.total_weighted_pct * 100, 2),
                cusip_count=s.n_cusips,
            )
            for s in overlap.sector_exposures
        ],
        breaches=[_map_cusip(e) for e in overlap.breaches],
        has_sufficient_data=has_sufficient_data,
        data_warning=data_warning,
    )


@router.post(
    "/{portfolio_id}/construction-advice",
    response_model=ConstructionAdviceRead,
    summary="Diagnose CVaR gaps and recommend candidate funds",
)
async def get_construction_advice(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> ConstructionAdviceRead:
    """Analyze block coverage gaps and recommend candidate funds.

    Uses existing optimizer result + strategic allocation to identify
    uncovered blocks, screen candidates from the global catalog, project
    per-candidate CVaR via historical simulation, and find a minimum viable
    set of additions.  Advisory only — does not modify the portfolio.
    """
    from dataclasses import asdict

    from app.domains.wealth.services.candidate_screener import (
        discover_candidates,
        fetch_candidate_holdings,
        fetch_candidate_returns,
        fetch_portfolio_holdings_cusips,
        fetch_portfolio_returns,
        load_block_metadata,
        load_strategic_targets,
    )
    from vertical_engines.wealth.model_portfolio.construction_advisor import build_advice

    _require_ic_role(actor)

    # 1. Load portfolio
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    fund_selection = portfolio.fund_selection_schema
    if not fund_selection or not fund_selection.get("funds"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Portfolio has no fund selection. Run construct first.",
        )

    opt_meta = fund_selection.get("optimization", {})
    current_cvar = opt_meta.get("cvar_95")
    if current_cvar is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No CVaR data in optimization result. Run construct first.",
        )

    profile = portfolio.profile

    # 2. Redis cache check
    cache_key = _hash_advice_input(str(portfolio_id), str(portfolio.updated_at))
    cached = await _get_cached_advice(cache_key)
    if cached is not None:
        logger.info("construction_advice_cache_hit", cache_key=cache_key)
        return ConstructionAdviceRead(**cached)

    # ── Phase 1: parallel fetch of everything independent of candidates ──
    (
        block_metadata,
        strategic_targets,
        (portfolio_daily_returns, portfolio_ret_series, current_weights),
        portfolio_holdings,
        all_cvar_limits,
    ) = await asyncio.gather(
        load_block_metadata(db),
        load_strategic_targets(db, profile),
        fetch_portfolio_returns(db, fund_selection),
        fetch_portfolio_holdings_cusips(db, fund_selection),
        _resolve_all_cvar_limits(db),
    )

    if not strategic_targets:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No strategic allocation defined for this profile.",
        )

    # 4. Determine block weights from optimizer result
    block_weights: dict[str, float] = {}
    for f in fund_selection.get("funds", []):
        bid = f.get("block_id")
        w = f.get("weight", 0.0)
        if bid:
            block_weights[bid] = block_weights.get(bid, 0.0) + w

    # 5. Identify gap blocks (target > 0 but missing or underweight)
    gap_block_ids = [
        bid for bid, target in strategic_targets.items()
        if target > 0 and block_weights.get(bid, 0.0) < target * 0.5
    ]

    # 6. Discover candidates from global catalog
    candidates = await discover_candidates(db, gap_block_ids, max_per_block=20)

    # ── Phase 2: candidate-dependent data only ───────────────────────────
    candidate_instrument_ids = [uuid.UUID(c.instrument_id) for c in candidates]

    candidate_returns_map, candidate_holdings_map = await asyncio.gather(
        fetch_candidate_returns(db, candidate_instrument_ids),
        fetch_candidate_holdings(db, candidate_instrument_ids),
    )

    # 8. CVaR limits (already resolved in Phase 1)
    cvar_limit = opt_meta.get("cvar_limit") or all_cvar_limits.get(profile, -0.08)
    alternative_cvar_limits = all_cvar_limits

    # 9. Run pure advisor engine in thread (CPU-bound numpy)
    if portfolio_daily_returns.size > 0 and len(candidate_returns_map) > 0:
        advice = await asyncio.to_thread(
            build_advice,
            portfolio_id=str(portfolio_id),
            profile=profile,
            current_cvar_95=float(current_cvar),
            cvar_limit=float(cvar_limit),
            block_weights=block_weights,
            strategic_targets=strategic_targets,
            block_metadata=block_metadata,
            candidates=candidates,
            portfolio_returns=portfolio_ret_series,
            portfolio_daily_returns=portfolio_daily_returns,
            candidate_returns=candidate_returns_map,
            current_weights=current_weights,
            candidate_holdings=candidate_holdings_map,
            portfolio_holdings=portfolio_holdings,
            alternative_cvar_limits=alternative_cvar_limits,
        )
    else:
        # Not enough data for full analysis — return gap analysis only
        from vertical_engines.wealth.model_portfolio.construction_advisor import analyze_block_gaps
        from vertical_engines.wealth.model_portfolio.models import AlternativeProfile

        coverage = analyze_block_gaps(block_weights, strategic_targets, block_metadata)
        alt_profiles = [
            AlternativeProfile(
                profile=ap,
                cvar_limit=al,
                current_cvar_would_pass=float(current_cvar) >= al,
            )
            for ap, al in alternative_cvar_limits.items()
            if ap != profile and float(current_cvar) >= al
        ]
        from vertical_engines.wealth.model_portfolio.models import ConstructionAdvice

        advice = ConstructionAdvice(
            portfolio_id=str(portfolio_id),
            profile=profile,
            current_cvar_95=float(current_cvar),
            cvar_limit=float(cvar_limit),
            cvar_gap=round(float(current_cvar) - float(cvar_limit), 6),
            coverage=coverage,
            candidates=[],
            minimum_viable_set=None,
            alternative_profiles=alt_profiles,
        )

    # 10. Serialize and cache
    result_dict = asdict(advice)
    await _set_cached_advice(cache_key, result_dict)

    logger.info(
        "construction_advice_computed",
        portfolio_id=str(portfolio_id),
        profile=profile,
        current_cvar=current_cvar,
        cvar_limit=cvar_limit,
        n_candidates=len(advice.candidates),
        mvs_found=advice.minimum_viable_set is not None,
    )

    return ConstructionAdviceRead(**result_dict)


# ── Rebalance Preview ────────────────────────────────────────────────────


@router.post(
    "/{portfolio_id}/rebalance/preview",
    response_model=RebalancePreviewResponse,
    summary="Preview rebalance trades (stateless)",
    description=(
        "Computes suggested BUY/SELL/HOLD trades by comparing the model "
        "portfolio's target weights against externally-provided current "
        "holdings. No DB writes — pure calculation. All values in USD."
    ),
)
async def rebalance_preview(
    portfolio_id: uuid.UUID,
    body: RebalancePreviewRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RebalancePreviewResponse:
    """Stateless rebalance preview: target vs current → trades."""
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    fund_selection = portfolio.fund_selection_schema
    if not fund_selection or not fund_selection.get("funds"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Portfolio has no fund selection. Run Construct first.",
        )

    from vertical_engines.wealth.rebalancing.preview_service import (
        compute_rebalance_preview,
    )

    preview = compute_rebalance_preview(
        portfolio_id=portfolio_id,
        portfolio_name=portfolio.display_name,
        profile=portfolio.profile,
        fund_selection_schema=fund_selection,
        current_holdings=[h.model_dump() for h in body.current_holdings],
        cash_available=body.cash_available,
        total_aum_override=body.total_aum,
    )

    # ── CVaR awareness: estimate projected CVaR from fund_risk_metrics ──
    cvar_95_projected: float | None = None
    cvar_limit_value: float | None = None
    cvar_warning = False

    try:
        from app.domains.wealth.models.risk import FundRiskMetrics

        target_funds = fund_selection.get("funds", [])
        target_ids = [uuid.UUID(f["instrument_id"]) for f in target_funds]
        target_weights = {str(f["instrument_id"]): float(f.get("weight", 0)) for f in target_funds}

        if target_ids:
            # Latest CVaR per fund from fund_risk_metrics (GLOBAL table, no RLS)
            risk_stmt = (
                select(
                    FundRiskMetrics.instrument_id,
                    FundRiskMetrics.cvar_95_12m,
                )
                .where(FundRiskMetrics.instrument_id.in_(target_ids))
                .where(FundRiskMetrics.cvar_95_12m.is_not(None))
                .distinct(FundRiskMetrics.instrument_id)
                .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.as_of.desc())
            )
            risk_rows = await db.execute(risk_stmt)
            cvar_map = {
                str(row.instrument_id): float(row.cvar_95_12m)
                for row in risk_rows.all()
            }

            # Weighted portfolio CVaR (linear approximation — conservative upper bound)
            if cvar_map:
                weighted_cvar = sum(
                    target_weights.get(iid, 0) * cvar
                    for iid, cvar in cvar_map.items()
                )
                cvar_95_projected = round(weighted_cvar, 6)

            # Load cvar_limit from strategic allocation
            today = date.today()
            alloc_stmt = (
                select(StrategicAllocation.cvar_limit)
                .where(
                    StrategicAllocation.profile == portfolio.profile,
                    StrategicAllocation.effective_from <= today,
                )
                .where(
                    (StrategicAllocation.effective_to.is_(None))
                    | (StrategicAllocation.effective_to >= today),
                )
                .limit(1)
            )
            alloc_row = (await db.execute(alloc_stmt)).scalar_one_or_none()
            if alloc_row is not None:
                cvar_limit_value = float(alloc_row)

            if cvar_95_projected is not None and cvar_limit_value is not None:
                # Warning when projected CVaR >= 90% of limit (approaching breach)
                cvar_warning = cvar_95_projected >= cvar_limit_value * 0.9
    except Exception:
        logger.warning("rebalance_cvar_estimation_failed", portfolio_id=str(portfolio_id), exc_info=True)

    preview["cvar_95_projected"] = cvar_95_projected
    preview["cvar_limit"] = cvar_limit_value
    preview["cvar_warning"] = cvar_warning

    return RebalancePreviewResponse(**preview)


# ── Drift Endpoints ──────────────────────────────────────────────────────


@router.get(
    "/{portfolio_id}/drift",
    response_model=DriftReportRead,
    summary="Block-level allocation drift from latest snapshot",
)
async def get_drift_report(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> DriftReportRead:
    """Compute block-level drift using the latest PortfolioSnapshot weights
    versus strategic + tactical targets. Delegates to existing
    ``compute_drift()`` in quant_queries — zero new math.
    """
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    from app.domains.wealth.services.quant_queries import compute_drift

    drift = await compute_drift(db, portfolio.profile)

    return DriftReportRead(
        profile=drift.profile,
        as_of_date=drift.as_of_date,
        blocks=[
            BlockDriftRead(
                block_id=b.block_id,
                current_weight=b.current_weight,
                target_weight=b.target_weight,
                absolute_drift=b.absolute_drift,
                relative_drift=b.relative_drift,
                status=b.status,
            )
            for b in drift.blocks
        ],
        max_drift_pct=drift.max_drift_pct,
        overall_status=drift.overall_status,
        rebalance_recommended=drift.rebalance_recommended,
        estimated_turnover=drift.estimated_turnover,
    )


@router.get(
    "/{portfolio_id}/drift/live",
    response_model=LiveDriftResponse,
    summary="Live drift using latest nav_timeseries prices",
    description=(
        "Computes allocation drift by multiplying fund_selection_schema "
        "target weights by the latest nav_timeseries prices to derive "
        "current live weights, then passes to compute_block_drifts(). "
        "Frontend should debounce calls (e.g. every 30s or on material "
        "price change)."
    ),
)
async def get_live_drift(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> LiveDriftResponse:
    """Compute drift from live NAV prices in nav_timeseries.

    1. Load fund_selection_schema (target weights per instrument + block).
    2. Query latest nav_timeseries price per instrument in the portfolio.
    3. Multiply target_weight * latest_nav to get live position values.
    4. Aggregate to block-level current weights.
    5. Load strategic + tactical block targets.
    6. Pass to existing ``compute_block_drifts()`` — zero new math.
    """
    from app.domains.wealth.models.allocation import TacticalPosition
    from app.domains.wealth.models.nav import NavTimeseries
    from quant_engine.drift_service import compute_block_drifts, resolve_drift_thresholds

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    fund_selection = portfolio.fund_selection_schema
    if not fund_selection or not fund_selection.get("funds"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Portfolio has no fund selection. Run Construct first.",
        )

    funds: list[dict] = fund_selection["funds"]
    instrument_ids = [uuid.UUID(f["instrument_id"]) for f in funds]

    # Query latest NAV price per instrument (DISTINCT ON + ORDER BY desc)
    latest_nav_subq = (
        select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav,
            NavTimeseries.nav_date,
        )
        .where(NavTimeseries.instrument_id.in_(instrument_ids))
        .where(NavTimeseries.nav.is_not(None))
        .distinct(NavTimeseries.instrument_id)
        .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date.desc())
        .subquery()
    )
    nav_result = await db.execute(select(latest_nav_subq))
    nav_rows = nav_result.all()
    price_map: dict[str, float] = {
        str(row.instrument_id): float(row.nav)
        for row in nav_rows
        if row.nav is not None
    }
    # Track the most recent NAV date across all instruments for staleness indicator
    latest_nav_date = max((row.nav_date for row in nav_rows if row.nav_date is not None), default=None)

    # Compute live position values: target_weight * latest_nav
    instrument_block: dict[str, str] = {}
    position_values: dict[str, float] = {}
    for fund in funds:
        iid = fund["instrument_id"]
        block_id = fund.get("block_id", "unknown")
        target_weight = float(fund.get("weight", 0))
        live_nav = price_map.get(iid)
        if live_nav is not None and live_nav > 0:
            position_values[iid] = target_weight * live_nav
        else:
            position_values[iid] = target_weight
        instrument_block[iid] = block_id

    # Aggregate to block-level current weights
    total_value = sum(position_values.values()) or 1.0
    block_values: dict[str, float] = {}
    for iid, val in position_values.items():
        bid = instrument_block.get(iid, "unknown")
        block_values[bid] = block_values.get(bid, 0.0) + val
    current_weights: dict[str, float] = {
        bid: val / total_value for bid, val in block_values.items()
    }

    # Build target weights from strategic + tactical allocations
    today = date.today()
    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == portfolio.profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= today),
        )
    )
    alloc_result = await db.execute(alloc_stmt)
    strategic = {a.block_id: float(a.target_weight) for a in alloc_result.scalars().all()}

    tact_stmt = (
        select(TacticalPosition)
        .where(
            TacticalPosition.profile == portfolio.profile,
            TacticalPosition.valid_from <= today,
        )
        .where(
            (TacticalPosition.valid_to.is_(None))
            | (TacticalPosition.valid_to >= today),
        )
    )
    tact_result = await db.execute(tact_stmt)
    # ic_manual overrides regime_auto for same block
    tactical: dict[str, float] = {}
    _tact_sources: dict[str, str] = {}
    for t in tact_result.scalars().all():
        t_source = t.source or "ic_manual"
        existing_source = _tact_sources.get(t.block_id)
        if existing_source is None or (t_source == "ic_manual" and existing_source != "ic_manual"):
            tactical[t.block_id] = float(t.overweight)
            _tact_sources[t.block_id] = t_source

    target_weights: dict[str, float] = {}
    for block_id in set(strategic.keys()) | set(tactical.keys()):
        target_weights[block_id] = strategic.get(block_id, 0.0) + tactical.get(block_id, 0.0)

    # Fallback: derive targets from fund_selection if no allocations
    if not target_weights:
        for fund in funds:
            bid = fund.get("block_id", "unknown")
            target_weights[bid] = target_weights.get(bid, 0.0) + float(fund.get("weight", 0))

    # Delegate to existing pure function
    maintenance, urgent = resolve_drift_thresholds()
    drifts = compute_block_drifts(current_weights, target_weights, maintenance, urgent)

    max_abs = max((abs(d.absolute_drift) for d in drifts), default=0.0)
    if any(d.status == "urgent" for d in drifts):
        overall = "urgent"
    elif any(d.status == "maintenance" for d in drifts):
        overall = "maintenance"
    else:
        overall = "ok"

    meaningful = [abs(d.absolute_drift) for d in drifts if abs(d.absolute_drift) >= 0.005]
    turnover = sum(meaningful) / 2
    rebalance_recommended = overall != "ok" and turnover >= 0.01

    return LiveDriftResponse(
        portfolio_id=str(portfolio_id),
        profile=portfolio.profile,
        as_of=date.today(),
        total_aum=total_value,
        blocks=[
            BlockDriftRead(
                block_id=d.block_id,
                current_weight=d.current_weight,
                target_weight=d.target_weight,
                absolute_drift=d.absolute_drift,
                relative_drift=d.relative_drift,
                status=d.status,
            )
            for d in drifts
        ],
        max_drift_pct=round(max_abs, 6),
        overall_status=overall,
        rebalance_recommended=rebalance_recommended,
        estimated_turnover=round(turnover, 6),
        latest_nav_date=latest_nav_date,
    )


# ── Activate ─────────────────────────────────────────────────────────────


@router.post(
    "/{portfolio_id}/activate",
    response_model=ModelPortfolioRead,
    summary="Activate a portfolio after successful construction",
)
async def activate_portfolio(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> ModelPortfolioRead:
    """Transition portfolio status from draft to active.

    Requires that the most recent construction produced a CVaR within
    the profile limit.  Rejects activation if CVaR exceeds the limit.
    """
    _require_ic_role(actor)

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    fund_selection = portfolio.fund_selection_schema
    if not fund_selection or not fund_selection.get("funds"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Portfolio has no fund selection. Run construct first.",
        )

    opt_meta = fund_selection.get("optimization", {})
    if not opt_meta.get("cvar_within_limit", False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot activate: CVaR exceeds profile limit. Add funds or adjust profile.",
        )

    portfolio.status = "active"
    await db.flush()
    await db.refresh(portfolio)

    logger.info(
        "portfolio_activated",
        portfolio_id=str(portfolio_id),
        profile=portfolio.profile,
    )

    return ModelPortfolioRead.model_validate(portfolio)


# ── Advice cache helpers ──────────────────────────────────────────────────


def _hash_advice_input(portfolio_id: str, updated_at: str) -> str:
    """Deterministic hash for advice cache key."""
    import hashlib
    import json

    payload = json.dumps({
        "portfolio_id": portfolio_id,
        "updated_at": updated_at,
        "date": date.today().isoformat(),
    }, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()[:24]


async def _get_cached_advice(cache_key: str) -> dict | None:
    """Check Redis for cached advice result (fail-open)."""
    try:
        import redis.asyncio as aioredis

        from app.core.jobs.tracker import get_redis_pool

        r = aioredis.Redis(connection_pool=get_redis_pool())
        try:
            cached = await r.get(f"advice:cache:{cache_key}")
            if cached:
                import json

                return json.loads(cached)
        finally:
            await r.aclose()
    except Exception:
        logger.debug("advice_cache_miss", cache_key=cache_key)
    return None


async def _set_cached_advice(cache_key: str, result: dict, ttl: int = 600) -> None:
    """Cache advice result in Redis (10min TTL, fail-open)."""
    try:
        import json

        import redis.asyncio as aioredis

        from app.core.jobs.tracker import get_redis_pool

        r = aioredis.Redis(connection_pool=get_redis_pool())
        try:
            await r.set(
                f"advice:cache:{cache_key}",
                json.dumps(result, default=str),
                ex=ttl,
            )
        finally:
            await r.aclose()
    except Exception:
        logger.debug("advice_cache_set_failed", cache_key=cache_key)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _sanitize_for_jsonb(obj: Any) -> Any:
    """Replace NaN/Inf floats with None so PostgreSQL JSONB accepts the payload."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize_for_jsonb(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_jsonb(v) for v in obj]
    return obj


def _require_ic_role(actor: Actor) -> None:
    """Verify actor has INVESTMENT_TEAM or ADMIN role."""
    if not actor.has_role(Role.INVESTMENT_TEAM):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Investment Committee role required",
        )


def _extract_fund_weights(
    fund_selection: dict[str, Any],
) -> tuple[list[uuid.UUID], list[float]]:
    """Extract fund IDs and weights from fund_selection_schema."""
    funds = fund_selection.get("funds", [])
    fund_ids = [uuid.UUID(f["instrument_id"]) for f in funds]
    weights = [f["weight"] for f in funds]
    return fund_ids, weights


async def _run_construction_async(
    db: AsyncSession,
    profile: str,
    org_id: str,
    portfolio_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Run optimizer-driven portfolio construction (fully async).

    Steps:
    1. Load approved universe + manager_score
    2. Query StrategicAllocation for block constraints + CVaR limit
    3. Compute fund-level covariance + expected returns from NAV timeseries
    4. Invoke CLARABEL fund-level optimizer with block-group constraints
    5. Build PortfolioComposition from optimizer output
    6. Fallback to block-level heuristic if fund-level optimization fails
    """
    from app.domains.wealth.models.allocation import TaaRegimeState as _TaaRS
    from app.domains.wealth.services.quant_queries import compute_fund_level_inputs
    from quant_engine.optimizer_service import (
        BlockConstraint,
        FundOptimizationResult,
        ProfileConstraints,
        optimize_fund_portfolio,
    )
    from vertical_engines.wealth.model_portfolio.models import OptimizationMeta
    from vertical_engines.wealth.model_portfolio.portfolio_builder import (
        construct,
        construct_from_optimizer,
    )

    # ── 1. Determine current regime for ELITE filtering ──
    _regime_stmt = (
        select(_TaaRS.raw_regime)
        .where(_TaaRS.profile == profile)
        .order_by(_TaaRS.as_of_date.desc())
        .limit(1)
    )
    _regime_result = await db.execute(_regime_stmt)
    current_regime = _regime_result.scalar_one_or_none() or "RISK_ON"

    # ── 2. Load approved universe (filtered by regime ELITE set) ──
    universe_funds = await _load_universe_funds(db, org_id, regime=current_regime)
    if not universe_funds:
        return {"funds": [], "profile": profile, "error": "No approved funds in universe"}

    # ── 3. Query strategic allocation for this profile ──
    today = date.today()
    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to > today),
        )
    )
    alloc_result = await db.execute(alloc_stmt)
    allocations = alloc_result.scalars().all()

    if not allocations:
        return {"funds": [], "profile": profile, "error": "No strategic allocation defined"}

    # Defense in depth: collapse duplicate active rows to the latest version per block.
    seen_blocks: dict[str, StrategicAllocation] = {}
    for allocation in allocations:
        current = seen_blocks.get(allocation.block_id)
        if current is None or allocation.effective_from > current.effective_from:
            seen_blocks[allocation.block_id] = allocation
    allocations = list(seen_blocks.values())

    strategic_targets = {a.block_id: float(a.target_weight) for a in allocations}

    # ── Resolve CVaR limit from profile config ──
    cvar_limit = await _resolve_cvar_limit(db, profile)

    # ── TAA: Resolve dynamic regime bands (or fallback to static IPS) ──
    from app.domains.wealth.models.allocation import TaaRegimeState
    from app.domains.wealth.models.block import AllocationBlock
    from quant_engine.taa_band_service import resolve_effective_bands

    # Fetch block → asset_class mapping
    block_ids = [a.block_id for a in allocations]
    block_ac_result = await db.execute(
        select(AllocationBlock.block_id, AllocationBlock.asset_class)
        .where(AllocationBlock.block_id.in_(block_ids))
    )
    block_asset_classes = {bid: ac for bid, ac in block_ac_result.all()}

    # Read taa_enabled from calibration (default True)
    taa_enabled = True
    if portfolio_id is not None:
        cal_result = await db.execute(
            select(PortfolioCalibration.expert_overrides)
            .where(PortfolioCalibration.portfolio_id == portfolio_id)
        )
        expert_overrides = cal_result.scalar_one_or_none()
        if isinstance(expert_overrides, dict):
            taa_enabled = expert_overrides.get("taa_enabled", True)

    # Fetch latest taa_regime_state for this org+profile
    taa_state_row = None
    if taa_enabled:
        taa_stmt = (
            select(TaaRegimeState)
            .where(
                TaaRegimeState.profile == profile,
            )
            .order_by(TaaRegimeState.as_of_date.desc())
            .limit(1)
        )
        taa_result = await db.execute(taa_stmt)
        taa_obj = taa_result.scalar_one_or_none()
        if taa_obj is not None:
            taa_state_row = {
                "raw_regime": taa_obj.raw_regime,
                "stress_score": float(taa_obj.stress_score) if taa_obj.stress_score is not None else None,
                "smoothed_centers": taa_obj.smoothed_centers,
                "effective_bands": taa_obj.effective_bands,
            }

    # Fetch TAA config from ConfigService
    taa_config = None
    if taa_enabled:
        from app.core.config.config_service import ConfigService as _CS
        _cs = _CS(db)
        taa_cfg_result = await _cs.get("liquid_funds", "taa_bands", org_id)
        if taa_cfg_result:
            taa_config = taa_cfg_result.value

    alloc_dicts = [
        {
            "block_id": a.block_id,
            "target_weight": float(a.target_weight),
            "min_weight": float(a.min_weight),
            "max_weight": float(a.max_weight),
        }
        for a in allocations
    ]

    block_constraints, taa_provenance = resolve_effective_bands(
        allocations=alloc_dicts,
        block_asset_classes=block_asset_classes,
        taa_regime_state=taa_state_row,
        taa_config=taa_config,
        taa_enabled=taa_enabled,
    )

    # Resolve max_single_fund_weight from profile config
    max_single_fund = await _resolve_max_single_fund(db, profile)

    constraints = ProfileConstraints(
        blocks=block_constraints,
        cvar_limit=cvar_limit,
        max_single_fund_weight=max_single_fund,
    )

    # Build fund metadata lookup
    fund_info: dict[str, dict[str, Any]] = {}
    fund_blocks: dict[str, str] = {}
    fund_instrument_ids: list[uuid.UUID] = []

    for f in universe_funds:
        fid = f["instrument_id"]
        fund_info[fid] = f
        if f.get("block_id"):
            fund_blocks[fid] = f["block_id"]
        fund_instrument_ids.append(uuid.UUID(fid))

    # ── 3+4. Fund-level optimization ──
    composition = None

    try:
        # ── BL-5: Fetch regime probs for regime-conditioned covariance ──
        regime_config: dict[str, Any] = {}
        try:
            regime_snap = await db.execute(
                select(PortfolioSnapshot.regime_probs)
                .where(PortfolioSnapshot.regime_probs.isnot(None))
                .order_by(PortfolioSnapshot.snapshot_date.desc())
                .limit(1),
            )
            regime_row = regime_snap.scalar_one_or_none()
            if regime_row and isinstance(regime_row, dict):
                p_high = regime_row.get("p_high_vol")
                if p_high is not None:
                    # Build a synthetic probs array from VIX history for the lookback
                    from app.domains.wealth.models.macro import MacroData

                    vix_stmt = (
                        select(MacroData.value)
                        .where(MacroData.series_id == "VIXCLS")
                        .order_by(MacroData.obs_date.desc())
                        .limit(504)
                    )
                    vix_result = await db.execute(vix_stmt)
                    vix_values = [float(r[0]) for r in vix_result.all()]
                    if len(vix_values) >= 63:
                        vix_values.reverse()
                        # Simple threshold-based probs as proxy (full HMM runs in worker)
                        vix_arr = np.array(vix_values)
                        median_vix = float(np.median(vix_arr))
                        regime_probs = (vix_arr / (median_vix + vix_arr)).tolist()
                        regime_config["_regime_probs"] = regime_probs
        except Exception:
            logger.debug("regime_probs_fetch_failed_using_standard_cov")

        cov_matrix, expected_returns, available_ids, fund_skewness, fund_excess_kurtosis = (
            await compute_fund_level_inputs(
                db,
                fund_instrument_ids,
                config=regime_config or None,
                portfolio_id=portfolio_id,
                profile=profile,
            )
        )

        # Filter to funds with NAV data
        opt_fund_ids = [fid for fid in available_ids if fid in fund_blocks]
        if len(opt_fund_ids) < 2:
            raise ValueError(f"Need ≥2 funds with NAV + block, found {len(opt_fund_ids)}")

        # Re-index covariance to match opt_fund_ids
        id_to_idx = {fid: i for i, fid in enumerate(available_ids)}
        indices = [id_to_idx[fid] for fid in opt_fund_ids]
        sub_cov = cov_matrix[np.ix_(indices, indices)]
        sub_returns = {fid: expected_returns[fid] for fid in opt_fund_ids}
        sub_blocks = {fid: fund_blocks[fid] for fid in opt_fund_ids}
        sub_skewness = fund_skewness[indices]
        sub_excess_kurtosis = fund_excess_kurtosis[indices]

        # Filter and rescale constraints to covered blocks only.
        # When universe covers a subset of blocks, original min/max don't
        # sum to 1.0 → infeasible.  Rescale proportionally so the optimizer
        # can find a valid fully-invested allocation.
        covered_blocks = set(sub_blocks.values())
        active_raw = [bc for bc in block_constraints if bc.block_id in covered_blocks]

        target_sum = sum(
            strategic_targets.get(bc.block_id, bc.max_weight) for bc in active_raw
        )
        if target_sum > 0 and len(active_raw) < len(block_constraints):
            scale = 1.0 / target_sum
            active_block_constraints = [
                BlockConstraint(
                    block_id=bc.block_id,
                    min_weight=0.0,  # relax floor — partial universe
                    max_weight=min(bc.max_weight * scale, 1.0),
                )
                for bc in active_raw
            ]
            # Feasibility check: effective block max is min(block_max, n_funds × max_single_fund).
            # If the sum of effective maxes < 1.0, constraints are infeasible → relax.
            effective_max_single = min(max_single_fund * (1.0 / max(target_sum, 0.01)), 1.0)
            funds_per_block: dict[str, int] = {}
            for fid in opt_fund_ids:
                blk = sub_blocks.get(fid)
                if blk:
                    funds_per_block[blk] = funds_per_block.get(blk, 0) + 1
            sum_of_scaled_maxes = sum(
                min(bc.max_weight, funds_per_block.get(bc.block_id, 1) * effective_max_single)
                for bc in active_block_constraints
            )
            if sum_of_scaled_maxes < 1.0:
                logger.info(
                    "block_constraints_relaxed_sparse_universe",
                    covered_blocks=list(covered_blocks),
                    sum_of_maxes=round(sum_of_scaled_maxes, 4),
                    reason="sum_of_maxes < 1.0 — only max_single_fund applies",
                )
                active_block_constraints = [
                    BlockConstraint(block_id=bc.block_id, min_weight=0.0, max_weight=1.0)
                    for bc in active_block_constraints
                ]
        else:
            active_block_constraints = active_raw

        active_constraints = ProfileConstraints(
            blocks=active_block_constraints,
            cvar_limit=cvar_limit,
            max_single_fund_weight=min(max_single_fund * (1.0 / max(target_sum, 0.01)), 1.0)
            if target_sum > 0 and len(active_raw) < len(block_constraints)
            else max_single_fund,
        )

        logger.info(
            "optimizer_constraints_prepared",
            n_funds=len(opt_fund_ids),
            covered_blocks=list(covered_blocks),
            total_blocks=len(block_constraints),
            target_sum=round(target_sum, 4) if target_sum else None,
            active_blocks=[
                {"id": bc.block_id, "min": bc.min_weight, "max": bc.max_weight}
                for bc in active_block_constraints
            ],
            max_single_fund=active_constraints.max_single_fund_weight,
        )

        from app.core.config.config_service import ConfigService
        config_svc = ConfigService(db)
        optimizer_result = await config_svc.get("wealth", "optimizer", str(org_id))
        optimizer_config = optimizer_result.value if optimizer_result else {}
        cf_factor = float(optimizer_config.get("cf_relaxation_factor", 1.3))

        fund_result: FundOptimizationResult = await optimize_fund_portfolio(
            fund_ids=opt_fund_ids,
            fund_blocks=sub_blocks,
            expected_returns=sub_returns,
            cov_matrix=sub_cov,
            constraints=active_constraints,
            skewness=sub_skewness,
            excess_kurtosis=sub_excess_kurtosis,
            cf_relaxation_factor=cf_factor,
        )

        if fund_result.status.startswith("optimal") and fund_result.weights:
            opt_meta = OptimizationMeta(
                expected_return=fund_result.expected_return,
                portfolio_volatility=fund_result.portfolio_volatility,
                sharpe_ratio=fund_result.sharpe_ratio,
                solver=fund_result.solver_info or "CLARABEL",
                status=fund_result.status,
                cvar_95=fund_result.cvar_95,
                cvar_limit=fund_result.cvar_limit,
                cvar_within_limit=fund_result.cvar_within_limit,
            )
            composition = construct_from_optimizer(
                profile, fund_result.weights, fund_info, opt_meta,
            )
            logger.info(
                "fund_level_optimizer_succeeded",
                profile=profile,
                n_funds=len(fund_result.weights),
                sharpe=fund_result.sharpe_ratio,
                cvar_95=fund_result.cvar_95,
                cvar_limit=fund_result.cvar_limit,
                cvar_within_limit=fund_result.cvar_within_limit,
            )
        else:
            logger.warning(
                "fund_level_optimizer_non_optimal",
                profile=profile,
                status=fund_result.status,
            )

    except ValueError as e:
        logger.warning(
            "fund_level_optimizer_insufficient_data",
            profile=profile,
            error=str(e),
        )

    # ── 5. Fallback to block-level heuristic if fund-level failed ──
    if composition is None:
        fallback_meta = OptimizationMeta(
            expected_return=0.0,
            portfolio_volatility=0.0,
            sharpe_ratio=0.0,
            solver="heuristic_fallback",
            status="fallback:insufficient_fund_data",
            cvar_95=None,
            cvar_limit=cvar_limit,
            cvar_within_limit=False,
        )
        composition = construct(
            profile, universe_funds, strategic_targets,
            optimization_meta=fallback_meta,
        )

    # ── 6. Serialize result ──
    result: dict[str, Any] = {
        "profile": composition.profile,
        "total_weight": composition.total_weight,
        "funds": [
            {
                "instrument_id": str(fw.instrument_id),
                "fund_name": fw.fund_name,
                "block_id": fw.block_id,
                "weight": fw.weight,
                "score": fw.score,
            }
            for fw in composition.funds
        ],
    }

    # Include TAA provenance for calibration_snapshot enrichment
    result["taa"] = taa_provenance

    if composition.optimization:
        result["optimization"] = {
            "expected_return": composition.optimization.expected_return,
            "portfolio_volatility": composition.optimization.portfolio_volatility,
            "sharpe_ratio": composition.optimization.sharpe_ratio,
            "solver": composition.optimization.solver,
            "status": composition.optimization.status,
            "cvar_95": composition.optimization.cvar_95,
            "cvar_limit": composition.optimization.cvar_limit,
            "cvar_within_limit": composition.optimization.cvar_within_limit,
        }

    # ── BL-7: Factor decomposition (best-effort, never blocks) ──
    if composition.optimization and composition.optimization.status.startswith("optimal"):
        try:
            factor_result = await _compute_factor_exposures(
                db, fund_instrument_ids, fund_result.weights, opt_fund_ids,
            )
            if factor_result:
                result["optimization"]["factor_exposures"] = factor_result
        except Exception:
            logger.debug("factor_decomposition_skipped")

    return result


async def _compute_factor_exposures(
    db: AsyncSession,
    fund_instrument_ids: list[uuid.UUID],
    fund_weights_dict: dict[str, float],
    opt_fund_ids: list[str],
) -> dict[str, float] | None:
    """Compute PCA factor exposures for the optimized portfolio (best-effort)."""
    try:
        from app.domains.wealth.models.nav import NavTimeseries
        from quant_engine.factor_model_service import decompose_factors

        # Fetch aligned returns matrix for optimized funds
        end_date = date.today()
        start_date = date.today() - __import__("datetime").timedelta(days=504)

        from collections import defaultdict as _dd

        returns_by_fund: dict[str, list[float]] = _dd(list)
        stmt = (
            select(NavTimeseries.instrument_id, NavTimeseries.return_1d)
            .where(
                NavTimeseries.instrument_id.in_([uuid.UUID(fid) for fid in opt_fund_ids]),
                NavTimeseries.nav_date >= start_date,
                NavTimeseries.nav_date <= end_date,
                NavTimeseries.return_1d.isnot(None),
                NavTimeseries.return_type == "log",
            )
            .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
        )
        result = await db.execute(stmt)
        for inst_id, ret in result.all():
            returns_by_fund[str(inst_id)].append(float(ret))

        # Align to common length
        valid_ids = [fid for fid in opt_fund_ids if len(returns_by_fund.get(fid, [])) >= 60]
        if len(valid_ids) < 3:
            return None

        min_len = min(len(returns_by_fund[fid]) for fid in valid_ids)
        returns_matrix = np.column_stack([
            np.array(returns_by_fund[fid][-min_len:]) for fid in valid_ids
        ])

        weights = np.array([fund_weights_dict.get(fid, 0.0) for fid in valid_ids])
        w_sum = weights.sum()
        if w_sum > 0:
            weights = weights / w_sum

        factor_result = decompose_factors(
            returns_matrix=returns_matrix,
            macro_proxies=None,
            portfolio_weights=weights,
            n_factors=min(3, len(valid_ids) - 1),
        )
        return factor_result.portfolio_factor_exposures
    except Exception:
        logger.debug("factor_exposure_computation_failed")
        return None


async def _load_universe_funds(
    db: AsyncSession,
    org_id: str,
    regime: str = "RISK_ON",
) -> list[dict[str, Any]]:
    """Load approved universe instruments with manager_score from risk metrics.

    The optimizer works over the FULL approved universe — not just ELITE.
    ELITE is a screener UX badge for analyst navigation, not a construction
    constraint. More candidates = more degrees of freedom = better portfolio.

    Liquid funds (registered_us, etf, ucits_eu, money_market) are approved
    by default when imported to the org. Only private_us and bdc require
    manual DD-gated approval via UniverseApproval.
    """
    from sqlalchemy import func as sa_func

    from app.domains.wealth.models.instrument import Instrument
    from app.domains.wealth.models.instrument_org import InstrumentOrg
    from app.domains.wealth.models.risk import FundRiskMetrics

    # Subquery: latest risk metrics row per instrument (for manager_score)
    latest_risk = (
        select(
            FundRiskMetrics.instrument_id,
            sa_func.max(FundRiskMetrics.calc_date).label("max_date"),
        )
        .where(FundRiskMetrics.organization_id.is_(None))
        .group_by(FundRiskMetrics.instrument_id)
        .subquery("latest_risk")
    )

    stmt = (
        select(
            Instrument.instrument_id,
            Instrument.name,
            InstrumentOrg.block_id,
        )
        .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
        .join(
            FundRiskMetrics,
            (FundRiskMetrics.instrument_id == Instrument.instrument_id)
            & (FundRiskMetrics.organization_id.is_(None)),
        )
        .join(
            latest_risk,
            (latest_risk.c.instrument_id == FundRiskMetrics.instrument_id)
            & (latest_risk.c.max_date == FundRiskMetrics.calc_date),
        )
        .where(
            Instrument.is_active == True,
            InstrumentOrg.block_id.isnot(None),
            # All funds imported to the org (instruments_org with block_id)
            # are eligible for construction. Liquid funds (MF/ETF/MMF/UCITS)
            # are approved by default at import time. Private/BDC funds
            # require DD-gated approval before instruments_org import.
            # The gate is at IMPORT time, not at construction time.
        )
    )
    funds_result = await db.execute(stmt)
    funds_rows = funds_result.all()

    if not funds_rows:
        return []

    fund_ids = [r.instrument_id for r in funds_rows]

    # Latest risk metrics for manager_score
    risk_stmt = (
        select(FundRiskMetrics.instrument_id, FundRiskMetrics.manager_score)
        .where(FundRiskMetrics.instrument_id.in_(fund_ids))
        .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.calc_date.desc())
        .distinct(FundRiskMetrics.instrument_id)
    )
    risk_result = await db.execute(risk_stmt)
    score_map = {
        r.instrument_id: float(r.manager_score) if r.manager_score else None
        for r in risk_result.all()
    }

    return [
        {
            "instrument_id": str(r.instrument_id),
            "fund_name": r.name,
            "block_id": r.block_id,
            "manager_score": score_map.get(r.instrument_id),
        }
        for r in funds_rows
    ]


async def _resolve_cvar_limit(
    db: AsyncSession,
    profile: str,
) -> float:
    """Resolve CVaR limit from ConfigService, falling back to hardcoded defaults."""
    try:
        from app.core.config.config_service import ConfigService

        config_svc = ConfigService(db)
        result = await config_svc.get("liquid_funds", "portfolio_profiles")
        profiles = result.value.get("profiles", {})
        profile_cfg = profiles.get(profile, {})
        cvar_cfg = profile_cfg.get("cvar", {})
        limit = cvar_cfg.get("limit")
        if limit is not None:
            return float(limit)
    except Exception:
        logger.debug("config_service_cvar_fallback", profile=profile)

    return _DEFAULT_CVAR_LIMITS.get(profile, -0.08)


async def _resolve_all_cvar_limits(db: AsyncSession) -> dict[str, float]:
    """Resolve CVaR limits for all profiles in a single ConfigService call."""
    try:
        from app.core.config.config_service import ConfigService

        config_svc = ConfigService(db)
        result = await config_svc.get("liquid_funds", "portfolio_profiles")
        profiles_cfg = result.value.get("profiles", {})

        limits: dict[str, float] = {}
        for profile_name in ("conservative", "moderate", "growth"):
            cvar_cfg = profiles_cfg.get(profile_name, {}).get("cvar", {})
            limit = cvar_cfg.get("limit")
            limits[profile_name] = float(limit) if limit is not None else _DEFAULT_CVAR_LIMITS.get(profile_name, -0.08)
        return limits
    except Exception:
        logger.debug("config_service_all_cvar_fallback")
        return dict(_DEFAULT_CVAR_LIMITS)


async def _resolve_max_single_fund(
    db: AsyncSession,
    profile: str,
) -> float:
    """Resolve max single fund weight from ConfigService."""
    try:
        from app.core.config.config_service import ConfigService

        config_svc = ConfigService(db)
        result = await config_svc.get("liquid_funds", "portfolio_profiles")
        profiles = result.value.get("profiles", {})
        profile_cfg = profiles.get(profile, {})
        max_w = profile_cfg.get("max_single_fund_weight")
        if max_w is not None:
            return float(max_w)
    except Exception:
        logger.debug("config_service_max_fund_fallback", profile=profile)

    return _DEFAULT_MAX_SINGLE_FUND.get(profile, 0.15)


async def _create_day0_snapshot(
    db: AsyncSession,
    portfolio: ModelPortfolio,
    fund_selection: dict[str, Any],
    org_id: str,
) -> None:
    """Create day-0 PortfolioSnapshot with actual CVaR from optimizer."""
    funds = fund_selection.get("funds", [])
    if not funds:
        return

    # Aggregate fund weights to block-level for snapshot.weights
    block_weights: dict[str, float] = {}
    for f in funds:
        bid = f["block_id"]
        block_weights[bid] = block_weights.get(bid, 0.0) + f["weight"]

    optimization = fund_selection.get("optimization", {})
    snapshot_date = date.today()

    # Use actual CVaR from optimizer (not volatility).
    # Values may be None (sanitized from NaN upstream) — treat as missing.
    cvar_current_val = optimization.get("cvar_95")
    cvar_limit_val = optimization.get("cvar_limit")

    # Guard against any residual NaN/Inf floats
    if isinstance(cvar_current_val, float) and not math.isfinite(cvar_current_val):
        cvar_current_val = None
    if isinstance(cvar_limit_val, float) and not math.isfinite(cvar_limit_val):
        cvar_limit_val = None

    # Compute utilization: |cvar_current / cvar_limit| x 100
    cvar_utilized = None
    if cvar_current_val is not None and cvar_limit_val is not None and cvar_limit_val != 0:
        cvar_utilized = round(abs(cvar_current_val / cvar_limit_val) * 100, 2)

    # Determine trigger status from CVaR utilization
    trigger = "ok"
    if cvar_utilized is not None:
        if cvar_utilized >= 100.0:
            trigger = "urgent"
        elif cvar_utilized >= 80.0:
            trigger = "maintenance"

    # Delete existing snapshot for this date (re-construct replaces it)
    from sqlalchemy import delete

    await db.execute(
        delete(PortfolioSnapshot).where(
            PortfolioSnapshot.organization_id == org_id,
            PortfolioSnapshot.profile == portfolio.profile,
            PortfolioSnapshot.snapshot_date == snapshot_date,
        ),
    )

    snapshot = PortfolioSnapshot(
        organization_id=org_id,
        profile=portfolio.profile,
        snapshot_date=snapshot_date,
        weights=_sanitize_for_jsonb(block_weights),
        fund_selection=_sanitize_for_jsonb(fund_selection),
        cvar_current=Decimal(str(round(cvar_current_val, 6))) if cvar_current_val is not None else None,
        cvar_limit=Decimal(str(round(cvar_limit_val, 6))) if cvar_limit_val is not None else None,
        cvar_utilized_pct=Decimal(str(cvar_utilized)) if cvar_utilized is not None else None,
        trigger_status=trigger,
        consecutive_breach_days=0,
    )
    db.add(snapshot)
    await db.flush()
    logger.info(
        "day0_snapshot_created",
        profile=portfolio.profile,
        snapshot_date=str(snapshot_date),
        blocks=len(block_weights),
        cvar_95=cvar_current_val,
        cvar_limit=cvar_limit_val,
        trigger_status=trigger,
    )


async def _resolve_fund_names_for_overlap(
    db: AsyncSession,
    fund_instrument_ids: list[str],
) -> dict[str, str]:
    """Resolve instrument_id → fund name for overlap display."""
    if not fund_instrument_ids:
        return {}
    from app.domains.wealth.models.instrument import Instrument

    stmt = select(
        Instrument.instrument_id,
        Instrument.name,
    ).where(
        Instrument.instrument_id.in_([uuid.UUID(fid) for fid in fund_instrument_ids]),
    )
    result = await db.execute(stmt)
    return {str(row.instrument_id): row.name for row in result.all()}


def _run_backtest(
    db: Any,
    fund_selection: dict[str, Any],
    portfolio_id: uuid.UUID,
) -> dict[str, Any]:
    """Run backtest in sync thread."""
    from vertical_engines.wealth.model_portfolio.track_record import compute_backtest

    fund_ids, weights = _extract_fund_weights(fund_selection)
    result = compute_backtest(
        db, fund_ids=fund_ids, weights=weights, portfolio_id=portfolio_id,
    )

    return {
        "mean_sharpe": result.mean_sharpe,
        "std_sharpe": result.std_sharpe,
        "positive_folds": result.positive_folds,
        "total_folds": result.total_folds,
        "youngest_fund_start": str(result.youngest_fund_start) if result.youngest_fund_start else None,
        "folds": [
            {
                "fold": f.fold,
                "sharpe": f.sharpe,
                "cvar_95": f.cvar_95,
                "max_drawdown": f.max_drawdown,
                "n_obs": f.n_obs,
            }
            for f in result.folds
        ],
    }


def _run_stress(
    db: Any,
    fund_selection: dict[str, Any],
    portfolio_id: uuid.UUID,
) -> dict[str, Any]:
    """Run stress scenarios in sync thread."""
    from vertical_engines.wealth.model_portfolio.track_record import compute_stress

    fund_ids, weights = _extract_fund_weights(fund_selection)
    result = compute_stress(
        db, fund_ids=fund_ids, weights=weights, portfolio_id=portfolio_id,
    )

    return {
        "scenarios": [
            {
                "name": s.name,
                "start_date": str(s.start_date),
                "end_date": str(s.end_date),
                "portfolio_return": s.portfolio_return,
                "max_drawdown": s.max_drawdown,
            }
            for s in result.scenarios
        ],
    }


# ── Holdings & Performance endpoints ────────────────────────


@router.get(
    "/{portfolio_id}/holdings",
    response_model=list[PositionDetail],
    summary="Detailed holdings with latest prices",
)
async def get_holdings(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[PositionDetail]:
    """Return all positions in a model portfolio with latest prices and P&L.

    Reads ``fund_selection_schema`` for weights, joins ``instruments_universe``
    for metadata, and ``nav_timeseries`` for latest + previous prices.

    Computed fields: position_value, intraday_pnl, intraday_pnl_pct.
    """
    from sqlalchemy import text as sa_text

    from app.domains.wealth.schemas.portfolio import PositionDetail

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    fund_selection = portfolio.fund_selection_schema
    if not fund_selection or not fund_selection.get("funds"):
        return []

    # Build instrument_id → (weight, block_id) map
    fund_map: dict[str, dict] = {}
    for f in fund_selection["funds"]:
        iid = f.get("instrument_id")
        w = f.get("weight")
        if iid and w:
            fund_map[str(iid)] = {"weight": float(w), "block_id": f.get("block_id")}

    if not fund_map:
        return []

    instrument_ids = list(fund_map.keys())
    placeholders = ", ".join(f"'{iid}'" for iid in instrument_ids)

    # Single query: instruments + latest NAV + previous NAV
    query = sa_text(f"""
        WITH latest_nav AS (
            SELECT DISTINCT ON (instrument_id)
                instrument_id, nav_date, nav, currency
            FROM nav_timeseries
            WHERE instrument_id::text IN ({placeholders})
            ORDER BY instrument_id, nav_date DESC
        ),
        prev_nav AS (
            SELECT DISTINCT ON (nt.instrument_id)
                nt.instrument_id, nt.nav AS prev_nav
            FROM nav_timeseries nt
            JOIN latest_nav ln ON ln.instrument_id = nt.instrument_id
                AND nt.nav_date < ln.nav_date
            ORDER BY nt.instrument_id, nt.nav_date DESC
        )
        SELECT
            iu.instrument_id, iu.ticker, iu.name,
            iu.asset_class, COALESCE(ln.currency, iu.currency, 'USD') AS currency,
            ln.nav AS last_price, pn.prev_nav AS previous_close, ln.nav_date AS price_date
        FROM instruments_universe iu
        LEFT JOIN latest_nav ln ON ln.instrument_id = iu.instrument_id
        LEFT JOIN prev_nav pn ON pn.instrument_id = iu.instrument_id
        WHERE iu.instrument_id::text IN ({placeholders})
    """)

    rows = await db.execute(query)

    portfolio_nav = float(portfolio.inception_nav or 1000)
    positions: list[PositionDetail] = []

    for row in rows.mappings():
        iid = str(row["instrument_id"])
        meta = fund_map.get(iid, {"weight": 0.0, "block_id": None})
        weight = Decimal(str(meta["weight"]))
        last_price = Decimal(str(row["last_price"])) if row["last_price"] else None
        prev_close = Decimal(str(row["previous_close"])) if row["previous_close"] else None

        # Compute intraday P&L
        position_value = weight * Decimal(str(portfolio_nav)) if last_price else None
        intraday_pnl: Decimal | None = None
        intraday_pnl_pct: Decimal | None = None

        if last_price and prev_close and prev_close != 0:
            price_change_pct = (last_price - prev_close) / prev_close
            intraday_pnl_pct = price_change_pct * 100
            if position_value is not None:
                intraday_pnl = position_value * price_change_pct

        positions.append(PositionDetail(
            instrument_id=row["instrument_id"],
            ticker=row["ticker"],
            name=row["name"] or "",
            asset_class=row["asset_class"] or "",
            currency=row["currency"] or "USD",
            weight=weight,
            block_id=meta.get("block_id"),
            last_price=last_price,
            previous_close=prev_close,
            price_date=row["price_date"],
            position_value=position_value,
            intraday_pnl=intraday_pnl,
            intraday_pnl_pct=intraday_pnl_pct,
        ))

    # Sort by position value descending
    positions.sort(key=lambda p: p.position_value or Decimal("0"), reverse=True)
    return positions


@router.get(
    "/{portfolio_id}/performance",
    response_model=PortfolioPerformanceSeries,
    summary="Historical NAV time series for charting",
)
async def get_performance(
    portfolio_id: uuid.UUID,
    timeframe: str = Query("1Y", pattern="^(1M|3M|6M|1Y|YTD|SI)$"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> PortfolioPerformanceSeries:
    """Return the model portfolio's historical NAV series from ``model_portfolio_nav``.

    Timeframes: 1M, 3M, 6M, 1Y, YTD, SI (since inception).
    Benchmark NAV is fetched from ``benchmark_nav`` if the portfolio has one.
    """
    from datetime import timedelta

    from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav
    from app.domains.wealth.schemas.portfolio import PerformancePoint, PortfolioPerformanceSeries

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if not portfolio:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Portfolio not found")

    # Compute start date from timeframe
    today = date.today()
    start_date: date
    if timeframe == "1M":
        start_date = today - timedelta(days=30)
    elif timeframe == "3M":
        start_date = today - timedelta(days=90)
    elif timeframe == "6M":
        start_date = today - timedelta(days=180)
    elif timeframe == "1Y":
        start_date = today - timedelta(days=365)
    elif timeframe == "YTD":
        start_date = date(today.year, 1, 1)
    else:  # SI
        start_date = portfolio.inception_date or date(2020, 1, 1)

    # Query model_portfolio_nav
    nav_stmt = (
        select(ModelPortfolioNav)
        .where(
            ModelPortfolioNav.portfolio_id == portfolio_id,
            ModelPortfolioNav.nav_date >= start_date,
        )
        .order_by(ModelPortfolioNav.nav_date)
    )
    nav_result = await db.execute(nav_stmt)
    nav_rows = nav_result.scalars().all()

    # Build series with cumulative return
    series: list[PerformancePoint] = []
    first_nav: float | None = None

    for row in nav_rows:
        nav_val = float(row.nav) if row.nav else 0
        if first_nav is None and nav_val > 0:
            first_nav = nav_val
        cum_return = ((nav_val / first_nav) - 1) * 100 if first_nav and first_nav > 0 else None

        series.append(PerformancePoint(
            nav_date=row.nav_date,
            nav=row.nav,
            daily_return=row.daily_return,
            cumulative_return=Decimal(str(round(cum_return, 4))) if cum_return is not None else None,
        ))

    return PortfolioPerformanceSeries(
        portfolio_id=portfolio_id,
        profile=portfolio.profile or "",
        inception_date=portfolio.inception_date,
        inception_nav=portfolio.inception_nav or Decimal("1000"),
        benchmark_name=portfolio.benchmark_composite,
        series=series,
        as_of=today,
    )


# ═══════════════════════════════════════════════════════════════════════
# UNIFIED REPORT ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════


@router.get(
    "/{portfolio_id}/reports",
    summary="List all generated reports for a portfolio",
    description=(
        "Returns historical reports (fact sheets, long-form DD, monthly) "
        "from the WealthGeneratedReport registry."
    ),
)
async def list_portfolio_reports(
    portfolio_id: uuid.UUID,
    report_type: str | None = Query(default=None, description="Filter by report type"),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> dict[str, Any]:
    """Unified report history for a portfolio.

    Queries the WealthGeneratedReport table for all report types,
    optionally filtered by report_type.
    """
    from app.domains.wealth.models.generated_report import WealthGeneratedReport
    from app.domains.wealth.schemas.generated_report import (
        ReportHistoryItem,
        ReportHistoryResponse,
    )

    # Verify portfolio exists
    result = await db.execute(
        select(ModelPortfolio.id).where(ModelPortfolio.id == portfolio_id),
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    stmt = (
        select(WealthGeneratedReport)
        .where(
            WealthGeneratedReport.portfolio_id == portfolio_id,
            WealthGeneratedReport.status == "completed",
        )
        .order_by(WealthGeneratedReport.generated_at.desc())
        .limit(limit)
    )

    if report_type:
        stmt = stmt.where(WealthGeneratedReport.report_type == report_type)

    rows = await db.execute(stmt)
    reports = rows.scalars().all()

    items = [ReportHistoryItem.model_validate(r) for r in reports]
    return ReportHistoryResponse(
        portfolio_id=portfolio_id,
        reports=items,
        total=len(items),
    ).model_dump(mode="json")


@router.post(
    "/{portfolio_id}/reports/generate",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger background report generation",
    description=(
        "Dispatches a background job to generate a report. "
        "Returns a job_id for SSE progress streaming."
    ),
)
async def generate_portfolio_report(
    portfolio_id: uuid.UUID,
    body: ReportGenerateRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> dict[str, Any]:
    """Unified report generation trigger.

    Accepts report_type and dispatches to the appropriate engine.
    Returns a job_id immediately; progress is streamed via SSE.
    """
    from app.core.jobs.tracker import register_job_owner

    _require_ic_role(actor)

    req = body

    # Verify portfolio exists and has fund selection
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    if not portfolio.fund_selection_schema:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Portfolio has no fund selection. Run /construct first.",
        )

    as_of = req.as_of_date or date.today()

    # Generate job_id with report-type prefix
    prefix_map = {
        "fact_sheet": "fs",
        "monthly_report": "mcr",
    }
    prefix = prefix_map.get(req.report_type, "rpt")
    job_id = f"{prefix}-{portfolio_id}-{uuid.uuid4().hex[:8]}"

    # Register job for SSE streaming
    await register_job_owner(job_id, str(org_id))

    # Dispatch background task based on report type
    import asyncio

    asyncio.create_task(
        _run_report_generation(
            job_id=job_id,
            portfolio_id=str(portfolio_id),
            organization_id=str(org_id),
            report_type=req.report_type,
            language=req.language,
            format=req.format,
            as_of=as_of,
        ),
    )

    return {
        "job_id": job_id,
        "portfolio_id": str(portfolio_id),
        "report_type": req.report_type,
        "status": "accepted",
    }


@router.get(
    "/{portfolio_id}/reports/stream/{job_id}",
    summary="SSE stream for report generation progress",
)
async def stream_report_progress(
    portfolio_id: uuid.UUID,
    job_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    org_id: str = Depends(get_org_id),
) -> Any:
    """Subscribe to SSE events for a report generation job."""
    from app.core.jobs.sse import create_job_stream
    from app.core.jobs.tracker import verify_job_owner

    if not await verify_job_owner(job_id, str(org_id)):
        raise HTTPException(status_code=403, detail="Job not found or unauthorized")

    return await create_job_stream(request, job_id)


# ── Background report generation task ──────────────────────────────


async def _run_report_generation(
    *,
    job_id: str,
    portfolio_id: str,
    organization_id: str,
    report_type: str,
    language: str,
    format: str,
    as_of: date,
) -> None:
    """Background task: dispatch to appropriate report engine and publish SSE events."""
    from app.core.jobs.tracker import publish_event, publish_terminal_event

    try:
        await publish_event(job_id, "progress", {
            "stage": "QUEUED",
            "message": "Report generation queued",
            "pct": 0,
        })

        if report_type == "fact_sheet":
            await _generate_fact_sheet_job(
                job_id=job_id,
                portfolio_id=portfolio_id,
                organization_id=organization_id,
                language=language,
                format=format,
                as_of=as_of,
            )
        elif report_type == "monthly_report":
            await _generate_monthly_report_job(
                job_id=job_id,
                portfolio_id=portfolio_id,
                organization_id=organization_id,
            )
        else:
            await publish_terminal_event(job_id, "error", {
                "error": f"Unknown report type: {report_type}",
            })

    except Exception as exc:
        logger.exception("report_generation_background_failed", job_id=job_id)
        await publish_terminal_event(job_id, "error", {"error": str(exc)})


async def _generate_fact_sheet_job(
    *,
    job_id: str,
    portfolio_id: str,
    organization_id: str,
    language: str,
    format: str,
    as_of: date,
) -> None:
    """Fact sheet generation with SSE progress events."""
    from app.core.jobs.tracker import publish_event, publish_terminal_event
    from app.domains.wealth.routes.common import _get_content_semaphore, require_content_slot

    await publish_event(job_id, "progress", {
        "stage": "FETCHING_MARKET_DATA",
        "message": "Loading portfolio and market data",
        "pct": 10,
    })

    await require_content_slot()
    try:
        await publish_event(job_id, "progress", {
            "stage": "GENERATING_PDF",
            "message": f"Rendering {format} fact sheet ({language.upper()})",
            "pct": 40,
        })

        def _generate() -> dict:
            from app.core.db.session import sync_session_factory

            with sync_session_factory() as sync_db, sync_db.begin():
                sync_db.expire_on_commit = False
                from sqlalchemy import text
                sync_db.execute(
                    text("SELECT set_config('app.current_organization_id', :oid, true)"),
                    {"oid": str(organization_id)},
                )
                from ai_engine.pipeline.storage_routing import gold_fact_sheet_path
                from vertical_engines.wealth.fact_sheet import FactSheetEngine

                engine = FactSheetEngine()
                pdf_buf = engine.generate(
                    sync_db,
                    portfolio_id=portfolio_id,
                    organization_id=organization_id,
                    format=format,
                    language=language,
                    as_of=as_of,
                )

                storage_path = gold_fact_sheet_path(
                    org_id=uuid.UUID(organization_id),
                    vertical="wealth",
                    portfolio_id=portfolio_id,
                    as_of_date=as_of.isoformat(),
                    language=language,
                    filename=f"{format}.pdf",
                )

                return {
                    "storage_path": storage_path,
                    "pdf_bytes": pdf_buf.read(),
                    "format": format,
                    "language": language,
                }

        gen_result = await asyncio.to_thread(_generate)

        await publish_event(job_id, "progress", {
            "stage": "STORING_PDF",
            "message": "Uploading PDF to storage",
            "pct": 80,
        })

        # Async storage write
        from app.services.storage_client import get_storage_client
        storage = get_storage_client()
        pdf_bytes = gen_result["pdf_bytes"]
        await storage.write(gen_result["storage_path"], pdf_bytes, content_type="application/pdf")

        # Persist report record
        from app.core.db.engine import async_session_factory
        from app.core.tenancy.middleware import set_rls_context
        from app.domains.wealth.models.generated_report import WealthGeneratedReport

        try:
            async with async_session_factory() as record_db:
                await set_rls_context(record_db, uuid.UUID(organization_id))
                report_record = WealthGeneratedReport(
                    organization_id=uuid.UUID(organization_id),
                    portfolio_id=uuid.UUID(portfolio_id),
                    report_type="fact_sheet",
                    job_id=job_id,
                    storage_path=gen_result["storage_path"],
                    display_filename=f"fact-sheet-{portfolio_id}-{format}.pdf",
                    size_bytes=len(pdf_bytes),
                    status="completed",
                )
                record_db.add(report_record)
                await record_db.commit()
        except Exception:
            logger.warning("fact_sheet_report_record_failed", exc_info=True)

        await publish_terminal_event(job_id, "done", {
            "status": "completed",
            "report_type": "fact_sheet",
            "storage_path": gen_result["storage_path"],
            "size_bytes": len(pdf_bytes),
        })

    finally:
        _get_content_semaphore().release()


async def _generate_monthly_report_job(
    *,
    job_id: str,
    portfolio_id: str,
    organization_id: str,
) -> None:
    """Monthly report generation with SSE progress."""
    from app.core.db.engine import async_session_factory
    from app.core.jobs.tracker import publish_event, publish_terminal_event
    from app.core.tenancy.middleware import set_rls_context

    try:
        async with async_session_factory() as db:
            await set_rls_context(db, uuid.UUID(organization_id))

            await publish_event(job_id, "progress", {
                "stage": "FETCHING_MARKET_DATA",
                "message": "Loading portfolio and performance data",
                "pct": 10,
            })

            from vertical_engines.wealth.monthly_report import MonthlyReportEngine
            engine = MonthlyReportEngine()

            await publish_event(job_id, "progress", {
                "stage": "RUNNING_QUANT_ENGINE",
                "message": "Computing performance attribution and risk metrics",
                "pct": 25,
            })

            result = await engine.generate(
                db,
                portfolio_id=portfolio_id,
                organization_id=organization_id,
            )

            await publish_event(job_id, "progress", {
                "stage": "GENERATING_PDF",
                "message": "Rendering monthly report PDF",
                "pct": 60,
            })

            pdf_storage_key = ""
            if result.status != "failed":
                try:
                    from vertical_engines.wealth.monthly_report.pdf_renderer import (
                        MonthlyPDFRenderer,
                    )
                    renderer = MonthlyPDFRenderer()
                    pdf_bytes = await renderer.render(result, db=db, organization_id=organization_id)

                    if pdf_bytes:
                        from ai_engine.pipeline.storage_routing import gold_monthly_report_path
                        pdf_storage_key = gold_monthly_report_path(
                            org_id=uuid.UUID(organization_id),
                            portfolio_id=portfolio_id,
                            job_id=job_id,
                        )

                        await publish_event(job_id, "progress", {
                            "stage": "STORING_PDF",
                            "message": "Uploading PDF to storage",
                            "pct": 85,
                        })

                        from app.services.storage_client import create_storage_client
                        storage = create_storage_client()
                        await storage.write(pdf_storage_key, pdf_bytes)

                        # Persist record
                        try:
                            async with async_session_factory() as record_db:
                                await set_rls_context(record_db, uuid.UUID(organization_id))
                                from app.domains.wealth.models.generated_report import (
                                    WealthGeneratedReport,
                                )
                                record_db.add(WealthGeneratedReport(
                                    organization_id=uuid.UUID(organization_id),
                                    portfolio_id=uuid.UUID(portfolio_id),
                                    report_type="monthly_report",
                                    job_id=job_id,
                                    storage_path=pdf_storage_key,
                                    display_filename=f"monthly-report-{portfolio_id}.pdf",
                                    size_bytes=len(pdf_bytes),
                                    status="completed",
                                ))
                                await record_db.commit()
                        except Exception:
                            logger.warning("monthly_report_record_failed", exc_info=True)
                except Exception:
                    logger.warning("monthly_report_pdf_generation_failed", exc_info=True)

            await publish_terminal_event(
                job_id,
                "done" if result.status != "failed" else "error",
                {
                    "status": result.status,
                    "report_type": "monthly_report",
                    "storage_path": pdf_storage_key,
                    "error": getattr(result, "error", None),
                },
            )

    except Exception as exc:
        logger.exception("monthly_report_background_failed", job_id=job_id)
        await publish_terminal_event(job_id, "error", {"error": str(exc)})


# ── Phase 3: construction run detail + stress catalog + regime current ────


@router.get(
    "/{portfolio_id}/runs/{run_id}",
    summary="Get a persisted construction run by ID",
)
async def get_construction_run(
    portfolio_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a single persisted construction run.

    Phase 3 Task 3.4 / 3.7 — the E2E smoke test reads runs via this
    endpoint after the ``/construct`` call completes. The full
    enrichment payload (optimizer_trace, validation, narrative,
    advisor, stress_results, ex_ante_metrics, ...) is returned
    as a flat dict — the frontend reads the JSONB columns directly
    without a separate Pydantic schema (Phase 4 wires it into the
    Builder's ``ConstructionNarrative.svelte``).

    Prompts are Netz IP and never leak here: the ``narrative``
    JSONB carries only RENDERED strings, not template source.
    """
    from app.domains.wealth.models.model_portfolio import PortfolioConstructionRun

    row = await db.execute(
        select(PortfolioConstructionRun).where(
            PortfolioConstructionRun.id == run_id,
            PortfolioConstructionRun.portfolio_id == portfolio_id,
        ),
    )
    run = row.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"construction run {run_id} not found",
        )

    return {
        "run_id": str(run.id),
        "portfolio_id": str(run.portfolio_id),
        "status": run.status,
        "as_of_date": run.as_of_date.isoformat(),
        "requested_by": run.requested_by,
        "requested_at": run.requested_at.isoformat() if run.requested_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "wall_clock_ms": run.wall_clock_ms,
        "failure_reason": run.failure_reason,
        "calibration_snapshot": run.calibration_snapshot,
        "optimizer_trace": run.optimizer_trace,
        "binding_constraints": run.binding_constraints,
        "regime_context": run.regime_context,
        "statistical_inputs": run.statistical_inputs,
        "ex_ante_metrics": run.ex_ante_metrics,
        "ex_ante_vs_previous": run.ex_ante_vs_previous,
        "factor_exposure": run.factor_exposure,
        "stress_results": run.stress_results,
        "advisor": run.advisor,
        "validation": run.validation,
        "narrative": run.narrative,
        "rationale_per_weight": run.rationale_per_weight,
        "weights_proposed": run.weights_proposed,
    }


@router.get(
    "/{portfolio_id}/runs/latest",
    summary="Get the most recent persisted construction run for a portfolio",
)
async def get_latest_construction_run(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any] | None:
    """Return the most recent succeeded/failed construction run.

    Phase 6 Block B added this endpoint so the Portfolio Analytics
    surface can render the FactorExposure + StressImpactMatrix charts
    without first triggering a new construct. Returns ``None`` (200
    with null body) when the portfolio has no runs yet — strict empty
    state per OD-26.

    Identical response shape to ``GET /{portfolio_id}/runs/{run_id}``
    so the frontend's ``ConstructionRunPayload`` decoder works for
    both endpoints. The order is ``requested_at DESC`` so the most
    recent run wins, regardless of status.
    """
    from app.domains.wealth.models.model_portfolio import PortfolioConstructionRun

    row = await db.execute(
        select(PortfolioConstructionRun)
        .where(PortfolioConstructionRun.portfolio_id == portfolio_id)
        .order_by(PortfolioConstructionRun.requested_at.desc())
        .limit(1),
    )
    run = row.scalar_one_or_none()
    if run is None:
        return None

    return {
        "run_id": str(run.id),
        "portfolio_id": str(run.portfolio_id),
        "status": run.status,
        "as_of_date": run.as_of_date.isoformat(),
        "requested_by": run.requested_by,
        "requested_at": run.requested_at.isoformat() if run.requested_at else None,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "wall_clock_ms": run.wall_clock_ms,
        "failure_reason": run.failure_reason,
        "calibration_snapshot": run.calibration_snapshot,
        "optimizer_trace": run.optimizer_trace,
        "binding_constraints": run.binding_constraints,
        "regime_context": run.regime_context,
        "statistical_inputs": run.statistical_inputs,
        "ex_ante_metrics": run.ex_ante_metrics,
        "ex_ante_vs_previous": run.ex_ante_vs_previous,
        "factor_exposure": run.factor_exposure,
        "stress_results": run.stress_results,
        "advisor": run.advisor,
        "validation": run.validation,
        "narrative": run.narrative,
        "rationale_per_weight": run.rationale_per_weight,
        "weights_proposed": run.weights_proposed,
    }


# ── Phase 2 Session C commit 4: mv_construction_run_diff endpoint ────


@router.get(
    "/{portfolio_id}/construction/runs/{run_id}/diff",
    response_model=ConstructionRunDiffOut,
    summary="Weight + metrics delta between a run and its predecessor",
)
async def get_construction_run_diff(
    portfolio_id: uuid.UUID,
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> ConstructionRunDiffOut:
    """Return the weight and ex-ante metric deltas for this run.

    Reads from the ``mv_construction_run_diff`` materialized view
    (shipped in Session 2.B commit 0118). The view pre-computes, for
    every run whose status is ``succeeded`` or ``superseded``, a
    JSONB dict keyed by instrument_id for weight changes and keyed by
    ex-ante metric name for metric changes, compared against the
    immediately preceding run on the same portfolio.

    404 is returned when:

    * The ``(portfolio_id, run_id)`` pair has no row in the MV. This
      happens for runs that have not reached a terminal success state,
      or when the MV has not been refreshed since the run landed.

    The response body shape is laid down by
    ``ConstructionRunDiffOut`` in ``schemas/model_portfolio.py``. The
    schema runs a belt-and-suspenders sanitisation pass on
    ``metrics_delta`` keys via ``humanize_metric`` so any residual
    jargon from a future upstream regression is stripped at the API
    boundary.
    """
    result = await db.execute(
        text(
            """
            SELECT
                portfolio_id,
                run_id,
                previous_run_id,
                requested_at,
                weight_delta_jsonb,
                metrics_delta_jsonb,
                status_delta_text
            FROM mv_construction_run_diff
            WHERE portfolio_id = :portfolio_id
              AND run_id = :run_id
            """,
        ),
        {"portfolio_id": portfolio_id, "run_id": run_id},
    )
    row = result.mappings().one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Construction run diff not available yet. The run may "
                "not have completed or the materialized view needs a "
                "refresh."
            ),
        )

    # The MV emits raw JSONB dicts — convert to the typed Pydantic
    # model shape. Each weight_delta_jsonb value is a {from, to, delta}
    # triple; metrics_delta_jsonb values are the same shape but with
    # possibly-None numeric fields.
    weight_delta_raw: dict[str, dict[str, Any]] = dict(row["weight_delta_jsonb"] or {})
    metrics_delta_raw: dict[str, dict[str, Any]] = dict(row["metrics_delta_jsonb"] or {})

    weight_delta: dict[str, ConstructionRunWeightDelta] = {
        instrument_id: ConstructionRunWeightDelta.model_validate(delta)
        for instrument_id, delta in weight_delta_raw.items()
    }

    metrics_delta: dict[str, ConstructionRunMetricDelta] = {}
    for metric_key, delta in metrics_delta_raw.items():
        # ``delta`` may be None if ex-ante metric was non-numeric —
        # the MV emits {"from": "...", "to": "...", "delta": null}
        def _coerce_optional_float(v: Any) -> float | None:
            if v is None:
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        metrics_delta[metric_key] = ConstructionRunMetricDelta(
            **{
                "from": _coerce_optional_float(delta.get("from")),
                "to": _coerce_optional_float(delta.get("to")),
                "delta": _coerce_optional_float(delta.get("delta")),
            },
        )

    return ConstructionRunDiffOut(
        portfolio_id=row["portfolio_id"],
        run_id=row["run_id"],
        previous_run_id=row["previous_run_id"],
        requested_at=row["requested_at"],
        weight_delta=weight_delta,
        metrics_delta=metrics_delta,
        status_delta_text=row["status_delta_text"],
    )


# Separate router prefixed /portfolio for the catalog + regime endpoints.
# Using a second APIRouter keeps the /model-portfolios prefix clean
# while giving us the plan-mandated `/portfolio/stress-test/scenarios`
# and `/portfolio/regime/current` paths.
portfolio_meta_router = APIRouter(prefix="/portfolio", tags=["portfolio-meta"])


#: DL7 — the 4 canonical stress scenarios. Display metadata is baked
#: here (not in ConfigService) because the scenario set is stable
#: across tenants and the shock vectors live in ``stress_scenarios.py``.
_STRESS_CATALOG_META: dict[str, dict[str, str]] = {
    "gfc_2008": {
        "display_name": "Global Financial Crisis (2008)",
        "description": (
            "Subprime mortgage collapse and Lehman failure. "
            "Equity -38% to -50%, HY credit -26%, Treasuries +6%."
        ),
    },
    "covid_2020": {
        "display_name": "COVID-19 Pandemic (Q1 2020)",
        "description": (
            "Rapid global selloff. Equity -30% to -40%, "
            "HY credit -12%, Treasuries +8%."
        ),
    },
    "taper_2013": {
        "display_name": "Taper Tantrum (2013)",
        "description": (
            "Fed signalled tapering of QE — bonds and EM equities "
            "sold off simultaneously. Gold -28%."
        ),
    },
    "rate_shock_200bps": {
        "display_name": "Rate Shock (+200 bps)",
        "description": (
            "Parallel 200bp shift in the yield curve. Long-duration "
            "bonds -12%, equity -8% to -12%."
        ),
    },
}


@portfolio_meta_router.get(
    "/stress-test/scenarios",
    response_model=StressScenarioCatalog,
    summary="List the canonical preset stress scenarios (DL7)",
)
async def list_stress_scenarios(
    user: CurrentUser = Depends(get_current_user),
) -> StressScenarioCatalog:
    """Return the 4 canonical stress scenarios from ``PRESET_SCENARIOS``.

    Phase 3 Task 3.5. Consumed by the Builder's ``StressScenarioPanel``
    (Phase 4 Task 4.4) for the Matrix tab dropdown. The shock vectors
    live in ``vertical_engines/wealth/model_portfolio/stress_scenarios.py``
    and are the single source of truth — adding a new preset requires
    updating both that file and ``_STRESS_CATALOG_META`` above.
    """
    from vertical_engines.wealth.model_portfolio.stress_scenarios import (
        PRESET_SCENARIOS,
    )

    entries = []
    for scenario_id, shocks in PRESET_SCENARIOS.items():
        meta = _STRESS_CATALOG_META.get(scenario_id, {})
        entries.append(
            StressScenarioCatalogEntry(
                scenario_id=scenario_id,
                display_name=meta.get("display_name", scenario_id),
                description=meta.get("description", ""),
                shock_components={str(k): float(v) for k, v in shocks.items()},
                kind="preset",
            ),
        )
    return StressScenarioCatalog(
        as_of=date.today(),
        scenarios=entries,
    )


#: OD-22 locked — raw regime enum → client-safe label.
#: Kept in sync with ``narrative_templater.REGIME_CLIENT_SAFE_LABEL``.
_REGIME_CLIENT_SAFE_LABEL: dict[str, str] = {
    "NORMAL": "Balanced",
    "RISK_ON": "Expansion",
    "RISK_OFF": "Defensive",
    "CRISIS": "Stress",
    "INFLATION": "Inflation",
}


@portfolio_meta_router.get(
    "/regime/current",
    response_model=RegimeCurrentRead,
    summary="Current market regime with client-safe label (OD-22)",
)
async def get_current_regime_endpoint(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RegimeCurrentRead:
    """Return the current market regime with the OD-22 translation.

    Phase 3 Task 3.6. Consumed by the Builder's ``RegimeBanner`` and
    the AnalyticsColumn. The ``client_safe_label`` is the only label
    the frontend should surface to end users — the raw ``regime``
    enum is for developer debugging only.

    Falls back to ``NORMAL``/``Balanced`` if FRED macro data is
    unavailable (e.g. fresh dev DB with no macro ingest yet).
    """
    from quant_engine.regime_service import get_current_regime

    try:
        regime_read = await get_current_regime(db, config=None)
        regime_raw = regime_read.regime or "NORMAL"
        reasons = regime_read.reasons
        source = "fred" if (reasons and reasons.get("source") != "caller_fallback") else "caller_fallback"
        return RegimeCurrentRead(
            regime=regime_raw,
            client_safe_label=_REGIME_CLIENT_SAFE_LABEL.get(
                regime_raw, regime_raw.capitalize(),
            ),
            as_of_date=regime_read.as_of_date,
            reasons=reasons,
            source=source,
        )
    except Exception as exc:  # noqa: BLE001 — regime detection is best-effort
        logger.warning("regime_current_fallback", error=str(exc))
        return RegimeCurrentRead(
            regime="NORMAL",
            client_safe_label="Balanced",
            as_of_date=None,
            reasons={"source": "fallback", "error": str(exc)},
            source="caller_fallback",
        )


# ──────────────────────────────────────────────────────────────────
# Shadow OMS — Phase 9 Block D
# ──────────────────────────────────────────────────────────────────

from app.core.runtime.gates import get_idempotency_storage
from app.core.runtime.idempotency import idempotent
from app.core.security.clerk_auth import require_role
from app.domains.wealth.models.shadow_oms import (
    PortfolioActualHoldings,
    TradeTicket,
)
from app.domains.wealth.schemas.shadow_oms import (
    ActualHoldingsResponse,
    ExecuteTradesRequest,
    ExecuteTradesResponse,
    HoldingWeight,
    TradeTicketPage,
    TradeTicketResponse,
)


@router.get(
    "/{portfolio_id}/actual-holdings",
    response_model=ActualHoldingsResponse,
    summary="Get actual holdings (or target fallback for zero-drift baseline)",
)
async def get_actual_holdings(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> ActualHoldingsResponse:
    """Return the actual holdings for a live portfolio.

    Phase 9 Block D. Fallback rule: if ``portfolio_actual_holdings``
    has no row for this portfolio (first time going live), return the
    target weights from ``fund_selection_schema.funds`` as a zero-drift
    baseline. The frontend ``WeightVectorTable`` can then compare
    actual vs target with drift = 0 until the first rebalance lands.
    """
    # 1. Load the portfolio to ensure it exists under RLS
    stmt = select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
    result = await db.execute(stmt)
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")

    # 2. Try to load actual holdings
    stmt_actual = select(PortfolioActualHoldings).where(
        PortfolioActualHoldings.portfolio_id == portfolio_id,
    )
    result_actual = await db.execute(stmt_actual)
    actual_row = result_actual.scalar_one_or_none()

    if actual_row is not None:
        # Real holdings exist — return them
        holdings = [
            HoldingWeight.model_validate(h) for h in (actual_row.holdings or [])
        ]
        return ActualHoldingsResponse(
            portfolio_id=str(portfolio_id),
            source="actual",
            holdings=holdings,
            holdings_version=actual_row.holdings_version,
            last_rebalanced_at=actual_row.last_rebalanced_at,
        )

    # 3. Fallback — return target weights as zero-drift baseline
    fss = portfolio.fund_selection_schema or {}
    target_funds = fss.get("funds", [])
    holdings = [
        HoldingWeight(
            instrument_id=f.get("instrument_id", ""),
            fund_name=f.get("fund_name", "Unknown"),
            instrument_type=f.get("instrument_type"),
            block_id=f.get("block_id", ""),
            weight=f.get("weight", 0),
            score=f.get("score", 0),
        )
        for f in target_funds
    ]
    return ActualHoldingsResponse(
        portfolio_id=str(portfolio_id),
        source="target_fallback",
        holdings=holdings,
        last_rebalanced_at=None,
    )


def _execute_trades_idempotency_key(
    portfolio_id: uuid.UUID,
    payload: ExecuteTradesRequest,
    **_kwargs: Any,
) -> str:
    """Derive idempotency key from portfolio + expected_version.

    Two requests with the same portfolio and expected_version are
    logically the same mutation — the second is a retry.
    """
    return f"exec_trades:{portfolio_id}:{payload.expected_version}"


@router.post(
    "/{portfolio_id}/execute-trades",
    response_model=ExecuteTradesResponse,
    status_code=status.HTTP_200_OK,
    summary="Execute trade tickets and update actual holdings (Shadow OMS)",
    dependencies=[Depends(require_role(Role.ADMIN, Role.INVESTMENT_TEAM))],
)
@idempotent(
    key=_execute_trades_idempotency_key,
    ttl_s=300,
    storage=get_idempotency_storage(),
)
async def execute_trades(
    portfolio_id: uuid.UUID,
    payload: ExecuteTradesRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    org_id: uuid.UUID = Depends(get_org_id),
    actor: Actor = Depends(get_actor),
) -> ExecuteTradesResponse:
    """Execute a batch of trade tickets against a live portfolio.

    Phase 1 Terminal OMS Hardening. Transactional:
    1. Validate portfolio is in state='live'.
    2. Optimistic lock: SELECT ... FOR UPDATE on actual holdings,
       verify ``expected_version`` matches, else 409.
    3. INSERT one ``trade_tickets`` row per ticket.
    4. Apply every BUY/SELL delta to the holdings JSONB.
    5. Increment ``holdings_version`` and persist.

    If any step fails, the entire transaction rolls back.
    """
    from sqlalchemy.orm.attributes import flag_modified  # noqa: PLC0415

    # 1. Load portfolio — must be live
    stmt = select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
    result = await db.execute(stmt)
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    if portfolio.state != "live":
        raise HTTPException(
            status_code=400,
            detail=f"Portfolio must be in state 'live' to execute trades (current: {portfolio.state})",
        )

    actor_id = actor.user_id if actor else None

    # 2. Load or bootstrap actual holdings with FOR UPDATE (optimistic lock)
    stmt_actual = (
        select(PortfolioActualHoldings)
        .where(PortfolioActualHoldings.portfolio_id == portfolio_id)
        .with_for_update()
    )
    result_actual = await db.execute(stmt_actual)
    actual_row = result_actual.scalar_one_or_none()

    if actual_row is None:
        # Bootstrap from target weights — version starts at 1
        fss = portfolio.fund_selection_schema or {}
        seed_holdings = list(fss.get("funds", []))
        actual_row = PortfolioActualHoldings(
            portfolio_id=portfolio_id,
            organization_id=org_id,
            holdings=seed_holdings,
            holdings_version=1,
        )
        db.add(actual_row)
        await db.flush()

    # Optimistic lock check
    if actual_row.holdings_version != payload.expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Holdings version mismatch: expected {payload.expected_version}, "
                f"current {actual_row.holdings_version}. "
                "Another trade may have been executed concurrently — reload and retry."
            ),
        )

    # 3. Insert trade ticket rows
    persisted_tickets: list[TradeTicketResponse] = []
    for t in payload.tickets:
        ticket = TradeTicket(
            portfolio_id=portfolio_id,
            organization_id=org_id,
            instrument_id=t.instrument_id,
            action=t.action,
            delta_weight=t.delta_weight,
            executed_by=actor_id,
        )
        db.add(ticket)
        await db.flush()  # populate defaults (id, executed_at)
        persisted_tickets.append(
            TradeTicketResponse(
                id=str(ticket.id),
                instrument_id=ticket.instrument_id,
                action=ticket.action,
                delta_weight=float(ticket.delta_weight),
                executed_at=ticket.executed_at,
                execution_venue=ticket.execution_venue,
                fill_status=ticket.fill_status,
            ),
        )

    # 4. Apply deltas to the holdings JSONB
    holdings_list: list[dict] = list(actual_row.holdings or [])
    holdings_by_id = {h.get("instrument_id"): h for h in holdings_list}

    for t in payload.tickets:
        h = holdings_by_id.get(t.instrument_id)
        if h is None:
            continue  # instrument not in portfolio — skip gracefully
        current_weight = float(h.get("weight", 0))
        if t.action == "BUY":
            h["weight"] = current_weight + t.delta_weight
        elif t.action == "SELL":
            h["weight"] = max(0.0, current_weight - t.delta_weight)

    # 5. Persist updated holdings + increment version
    actual_row.holdings = holdings_list
    actual_row.holdings_version += 1
    actual_row.last_rebalanced_at = func.now()
    flag_modified(actual_row, "holdings")

    await db.commit()

    return ExecuteTradesResponse(
        portfolio_id=str(portfolio_id),
        trades_executed=len(persisted_tickets),
        tickets=persisted_tickets,
    )


@router.get(
    "/{portfolio_id}/trade-tickets",
    response_model=TradeTicketPage,
    summary="Paginated trade ticket history for a portfolio",
)
async def list_trade_tickets(
    portfolio_id: uuid.UUID,
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> TradeTicketPage:
    """Return paginated trade tickets ordered by executed_at DESC.

    Uses the composite index ``ix_trade_tickets_portfolio_executed_id``
    for efficient keyset-friendly pagination.
    """
    offset = (page - 1) * page_size

    # Count
    count_stmt = (
        select(func.count())
        .select_from(TradeTicket)
        .where(TradeTicket.portfolio_id == portfolio_id)
    )
    total = (await db.execute(count_stmt)).scalar() or 0

    # Fetch page
    data_stmt = (
        select(TradeTicket)
        .where(TradeTicket.portfolio_id == portfolio_id)
        .order_by(TradeTicket.executed_at.desc(), TradeTicket.id.desc())
        .offset(offset)
        .limit(page_size)
    )
    rows = (await db.execute(data_stmt)).scalars().all()

    items = [
        TradeTicketResponse(
            id=str(t.id),
            instrument_id=t.instrument_id,
            action=t.action,
            delta_weight=float(t.delta_weight),
            executed_at=t.executed_at,
            execution_venue=t.execution_venue,
            fill_status=t.fill_status,
        )
        for t in rows
    ]

    return TradeTicketPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=(page * page_size < total),
    )


# ═══════════════════════════════════════════��═══════════════════════════
# NAV HISTORY (Session 3 — Backtest Tab)
# ═════════════════════════════════════════════��═════════════════════════


@router.get(
    "/{portfolio_id}/nav-history",
    summary="NAV series with drawdown + summary metrics for charting",
)
async def get_nav_history(
    portfolio_id: uuid.UUID,
    period: str = Query("5Y", pattern="^(1Y|3Y|5Y|10Y)$"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return historical NAV, drawdown series, and summary metrics.

    Designed for the Builder BACKTEST tab (equity curve + underwater chart).
    Period controls the lookback window: 1Y/3Y/5Y/10Y.
    """
    from datetime import timedelta

    from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    # Compute lookback from period
    today = date.today()
    period_days = {"1Y": 365, "3Y": 365 * 3, "5Y": 365 * 5, "10Y": 365 * 10}
    start_date = today - timedelta(days=period_days[period])

    nav_stmt = (
        select(ModelPortfolioNav)
        .where(
            ModelPortfolioNav.portfolio_id == portfolio_id,
            ModelPortfolioNav.nav_date >= start_date,
        )
        .order_by(ModelPortfolioNav.nav_date)
    )
    nav_result = await db.execute(nav_stmt)
    nav_rows = nav_result.scalars().all()

    if not nav_rows:
        return {
            "portfolio_id": str(portfolio_id),
            "dates": [],
            "nav_series": [],
            "drawdown_series": [],
            "metrics": {"sharpe": None, "max_dd": None, "ann_return": None, "calmar": None},
        }

    dates: list[str] = []
    nav_values: list[float] = []
    drawdowns: list[float] = []
    daily_returns: list[float] = []
    running_max = 0.0

    for row in nav_rows:
        nav_val = float(row.nav)
        dates.append(row.nav_date.isoformat())
        nav_values.append(round(nav_val, 4))

        # Drawdown: dd_t = (nav_t / running_max) - 1
        running_max = max(running_max, nav_val)
        dd = (nav_val / running_max) - 1 if running_max > 0 else 0.0
        drawdowns.append(round(dd, 6))

        if row.daily_return is not None:
            daily_returns.append(float(row.daily_return))

    # Summary metrics
    metrics: dict[str, float | None] = {
        "sharpe": None,
        "max_dd": None,
        "ann_return": None,
        "calmar": None,
    }

    if daily_returns:
        returns_arr = np.array(daily_returns)
        mean_r = float(np.mean(returns_arr))
        std_r = float(np.std(returns_arr, ddof=1))
        rf_daily = 0.04 / 252

        # Annualized return
        ann_return = float((1 + mean_r) ** 252 - 1)
        metrics["ann_return"] = round(ann_return, 6)

        # Sharpe
        if std_r > 1e-12:
            sharpe = (mean_r - rf_daily) / std_r * np.sqrt(252)
            metrics["sharpe"] = round(float(sharpe), 4)

        # Max drawdown
        max_dd = min(drawdowns) if drawdowns else 0.0
        metrics["max_dd"] = round(max_dd, 6)

        # Calmar
        if metrics["max_dd"] is not None and abs(metrics["max_dd"]) > 1e-12:
            metrics["calmar"] = round(ann_return / abs(metrics["max_dd"]), 4)

    return {
        "portfolio_id": str(portfolio_id),
        "dates": dates,
        "nav_series": nav_values,
        "drawdown_series": drawdowns,
        "metrics": metrics,
    }


# ══��══════════════════════��═════════════════════════════��═══════════════
# MONTE CARLO (Session 3 — Monte Carlo Tab)
# ══════════════════════════════════════════════���════════════════════════


@router.post(
    "/{portfolio_id}/monte-carlo",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Monte Carlo simulation scoped to a model portfolio",
)
async def trigger_monte_carlo(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Run block-bootstrap Monte Carlo simulation for a model portfolio.

    Uses the portfolio's synthesized NAV from ``model_portfolio_nav``.
    Results cached in Redis (1h TTL).
    """
    import hashlib
    import json

    _require_ic_role(actor)

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id),
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    # Check Redis cache
    cache_key_input = json.dumps({
        "portfolio_id": str(portfolio_id),
        "date": date.today().isoformat(),
        "statistic": "return",
    }, sort_keys=True).encode()
    cache_key = f"mc:portfolio:{hashlib.sha256(cache_key_input).hexdigest()[:24]}"

    cached = await _get_cached_mc(cache_key)
    if cached:
        return cached

    # Fetch NAV series
    from app.domains.wealth.services.nav_reader import fetch_nav_series

    from datetime import timedelta
    start_date = date.today() - timedelta(days=int(1260 * 1.5))  # ~5Y buffer
    nav_rows = await fetch_nav_series(db, portfolio_id, start_date, date.today())

    if len(nav_rows) < 42:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient NAV data: {len(nav_rows)} rows (need >= 42)",
        )

    daily_returns = np.array([
        r.daily_return if r.daily_return is not None else 0.0
        for r in nav_rows
    ])

    from quant_engine.monte_carlo_service import run_monte_carlo

    mc_result = run_monte_carlo(
        daily_returns=daily_returns,
        n_simulations=1000,
        statistic="return",
        horizons=[252, 756, 1260],
    )

    response = {
        "portfolio_id": str(portfolio_id),
        "n_simulations": mc_result.n_simulations,
        "statistic": mc_result.statistic,
        "percentiles": mc_result.percentiles,
        "mean": mc_result.mean,
        "median": mc_result.median,
        "std": mc_result.std,
        "historical_value": mc_result.historical_value,
        "confidence_bars": mc_result.confidence_bars,
    }

    await _set_cached_mc(cache_key, response)
    return response


async def _get_cached_mc(cache_key: str) -> dict | None:
    """Check Redis for cached Monte Carlo result (fail-open)."""
    try:
        import json

        import redis.asyncio as aioredis

        from app.core.jobs.tracker import get_redis_pool

        r = aioredis.Redis(connection_pool=get_redis_pool())
        try:
            cached = await r.get(cache_key)
            if cached:
                return json.loads(cached)
        finally:
            await r.aclose()
    except Exception:
        logger.debug("mc_cache_miss", cache_key=cache_key)
    return None


async def _set_cached_mc(cache_key: str, result: dict, ttl: int = 3600) -> None:
    """Cache Monte Carlo result in Redis (1h TTL, fail-open)."""
    try:
        import json

        import redis.asyncio as aioredis

        from app.core.jobs.tracker import get_redis_pool

        r = aioredis.Redis(connection_pool=get_redis_pool())
        try:
            await r.set(cache_key, json.dumps(result, default=str), ex=ttl)
        finally:
            await r.aclose()
    except Exception:
        logger.debug("mc_cache_set_failed", cache_key=cache_key)

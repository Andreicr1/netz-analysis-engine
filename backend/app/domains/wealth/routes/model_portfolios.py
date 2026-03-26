"""Model Portfolio API routes — CRUD, construction, track-record, stress.

All endpoints use get_db_with_rls and response_model + model_validate().
IC role required for creation and construction.

Construction invokes CLARABEL optimizer for mathematically rigorous block weights,
then distributes within blocks by manager_score.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from app.domains.wealth.schemas.model_portfolio import (
    ModelPortfolioCreate,
    ModelPortfolioRead,
)
from app.shared.enums import Role

logger = structlog.get_logger()

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
    """Create a new model portfolio. Requires IC role."""
    _require_ic_role(actor)

    portfolio = ModelPortfolio(
        organization_id=org_id,
        profile=body.profile,
        display_name=body.display_name,
        description=body.description,
        benchmark_composite=body.benchmark_composite,
        inception_date=body.inception_date,
        backtest_start_date=body.backtest_start_date,
        status="draft",
        created_by=actor.actor_id,
    )
    db.add(portfolio)
    await db.flush()
    await db.refresh(portfolio)
    return ModelPortfolioRead.model_validate(portfolio)


@router.get(
    "",
    response_model=list[ModelPortfolioRead],
    summary="List model portfolios",
)
async def list_model_portfolios(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[ModelPortfolioRead]:
    """List all model portfolios for the organization."""
    result = await db.execute(
        select(ModelPortfolio).order_by(ModelPortfolio.created_at.desc())
    )
    return [ModelPortfolioRead.model_validate(p) for p in result.scalars().all()]


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
    """Get a model portfolio with its fund selection schema."""
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )
    return ModelPortfolioRead.model_validate(portfolio)


@router.post(
    "/{portfolio_id}/construct",
    response_model=ModelPortfolioRead,
    summary="Run optimizer-driven fund selection from universe",
)
async def construct_portfolio(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> ModelPortfolioRead:
    """Run CLARABEL optimizer + fund selection from approved universe. Requires IC role.

    Flow:
    1. Load approved universe and strategic allocation
    2. Compute expected returns + covariance from NAV timeseries
    3. Invoke CLARABEL solver for optimal block weights
    4. Distribute block weights to top-N funds by manager_score
    5. Persist fund_selection_schema with optimization metadata
    6. Create day-0 PortfolioSnapshot for monitoring engine
    """
    _require_ic_role(actor)

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    fund_selection = await _run_construction_async(db, portfolio.profile, org_id)

    portfolio.fund_selection_schema = fund_selection
    portfolio.status = "backtesting"
    await db.flush()

    # Create day-0 PortfolioSnapshot for monitoring engine tracking
    await _create_day0_snapshot(db, portfolio, fund_selection, org_id)

    await db.refresh(portfolio)
    return ModelPortfolioRead.model_validate(portfolio)


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
    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Model portfolio {portfolio_id} not found",
        )

    return {
        "portfolio_id": str(portfolio_id),
        "profile": portfolio.profile,
        "status": portfolio.status,
        "fund_selection": portfolio.fund_selection_schema,
        "backtest": None,  # Populated by POST /backtest
        "live_nav": None,  # Populated by daily worker
        "stress": None,  # Populated by POST /stress
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
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
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

        with sync_session_factory() as sync_db:
            sync_db.expire_on_commit = False
            from sqlalchemy import text
            sync_db.execute(text("SET LOCAL app.current_organization_id = :oid"), {"oid": _org_id})
            return _run_backtest(sync_db, portfolio.fund_selection_schema, portfolio_id)

    backtest_result = await asyncio.to_thread(_backtest)
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
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
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

        with sync_session_factory() as sync_db:
            sync_db.expire_on_commit = False
            from sqlalchemy import text
            sync_db.execute(text("SET LOCAL app.current_organization_id = :oid"), {"oid": _org_id_stress})
            return _run_stress(sync_db, portfolio.fund_selection_schema, portfolio_id)

    stress_result = await asyncio.to_thread(_stress)
    return {
        "portfolio_id": str(portfolio_id),
        "status": "completed",
        "stress": stress_result,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────


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
) -> dict[str, Any]:
    """Run optimizer-driven portfolio construction (fully async).

    Steps:
    1. Load approved universe via UniverseService (sync, offloaded to thread)
    2. Query StrategicAllocation for profile constraints
    3. Compute expected returns + covariance from NAV timeseries
    4. Invoke CLARABEL optimizer for optimal block weights
    5. Distribute block weights to funds via portfolio_builder.construct()
    """
    from app.domains.wealth.services.quant_queries import compute_inputs_from_nav
    from quant_engine.optimizer_service import (
        BlockConstraint,
        OptimizationResult,
        ProfileConstraints,
        optimize_portfolio,
    )
    from vertical_engines.wealth.model_portfolio.models import OptimizationMeta
    from vertical_engines.wealth.model_portfolio.portfolio_builder import construct

    # ── 1. Load approved universe (sync service, offload to thread) ──
    universe_funds = await _load_universe_funds(db, org_id)

    # ── 2. Query strategic allocation for this profile ──
    today = date.today()
    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= today)
        )
    )
    alloc_result = await db.execute(alloc_stmt)
    allocations = alloc_result.scalars().all()

    if not allocations:
        return {"funds": [], "profile": profile, "error": "No strategic allocation defined"}

    block_ids = [a.block_id for a in allocations]
    strategic_targets = {a.block_id: float(a.target_weight) for a in allocations}

    # ── 3. Compute optimization inputs from NAV timeseries ──
    opt_result: OptimizationResult | None = None
    optimized_weights: dict[str, float]
    optimization_meta: OptimizationMeta | None = None

    try:
        cov_matrix, expected_returns = await compute_inputs_from_nav(db, block_ids)

        # ── 4. Build constraints and invoke CLARABEL ──
        block_constraints = [
            BlockConstraint(
                block_id=a.block_id,
                min_weight=float(a.min_weight),
                max_weight=float(a.max_weight),
            )
            for a in allocations
        ]
        constraints = ProfileConstraints(blocks=block_constraints)

        opt_result = await optimize_portfolio(
            block_ids=block_ids,
            expected_returns=expected_returns,
            cov_matrix=cov_matrix,
            constraints=constraints,
        )

        if opt_result.status == "optimal" and opt_result.weights:
            optimized_weights = opt_result.weights
            optimization_meta = OptimizationMeta(
                expected_return=opt_result.expected_return,
                portfolio_volatility=opt_result.portfolio_volatility,
                sharpe_ratio=opt_result.sharpe_ratio,
                solver=opt_result.solver_info or "CLARABEL",
                status=opt_result.status,
            )
            logger.info(
                "optimizer_succeeded",
                profile=profile,
                sharpe=opt_result.sharpe_ratio,
                volatility=opt_result.portfolio_volatility,
                solver=opt_result.solver_info,
            )
        else:
            # Solver did not find optimal — fall back to strategic targets
            logger.warning(
                "optimizer_non_optimal_fallback",
                profile=profile,
                solver_status=opt_result.status,
                solver_info=opt_result.solver_info,
            )
            optimized_weights = strategic_targets
            optimization_meta = OptimizationMeta(
                expected_return=0.0,
                portfolio_volatility=0.0,
                sharpe_ratio=0.0,
                solver="heuristic_fallback",
                status=f"fallback:{opt_result.status}",
            )

    except ValueError as e:
        # Insufficient NAV data — fall back to strategic allocation targets
        logger.warning(
            "optimizer_insufficient_data_fallback",
            profile=profile,
            error=str(e),
        )
        optimized_weights = strategic_targets
        optimization_meta = OptimizationMeta(
            expected_return=0.0,
            portfolio_volatility=0.0,
            sharpe_ratio=0.0,
            solver="heuristic_fallback",
            status="fallback:insufficient_nav_data",
        )

    # ── 5. Distribute block weights to individual funds ──
    composition = construct(
        profile,
        universe_funds,
        optimized_weights,
        optimization_meta=optimization_meta,
    )

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

    # Attach optimization metadata for transparency
    if composition.optimization:
        result["optimization"] = {
            "expected_return": composition.optimization.expected_return,
            "portfolio_volatility": composition.optimization.portfolio_volatility,
            "sharpe_ratio": composition.optimization.sharpe_ratio,
            "solver": composition.optimization.solver,
            "status": composition.optimization.status,
        }

    return result


async def _load_universe_funds(
    db: AsyncSession,
    org_id: str,
) -> list[dict[str, Any]]:
    """Load approved universe instruments with manager_score from risk metrics."""
    from app.domains.wealth.models.instrument import Instrument
    from app.domains.wealth.models.risk import FundRiskMetrics
    from app.domains.wealth.models.universe_approval import UniverseApproval

    # Approved universe assets
    stmt = (
        select(
            Instrument.instrument_id,
            Instrument.name,
            Instrument.block_id,
        )
        .join(
            UniverseApproval,
            (UniverseApproval.instrument_id == Instrument.instrument_id)
            & (UniverseApproval.is_current == True)
            & (UniverseApproval.decision == "approved"),
        )
        .where(Instrument.is_active == True, Instrument.block_id.isnot(None))
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


async def _create_day0_snapshot(
    db: AsyncSession,
    portfolio: ModelPortfolio,
    fund_selection: dict[str, Any],
    org_id: str,
) -> None:
    """Create day-0 PortfolioSnapshot so monitoring engine starts tracking."""
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

    snapshot = PortfolioSnapshot(
        organization_id=org_id,
        profile=portfolio.profile,
        snapshot_date=snapshot_date,
        weights=block_weights,
        fund_selection=fund_selection,
        cvar_current=Decimal(str(round(optimization.get("portfolio_volatility", 0.0), 6)))
        if optimization else None,
        trigger_status="ok",
        consecutive_breach_days=0,
    )
    db.add(snapshot)
    await db.flush()
    logger.info(
        "day0_snapshot_created",
        profile=portfolio.profile,
        snapshot_date=str(snapshot_date),
        blocks=len(block_weights),
    )


def _run_backtest(
    db: Any,
    fund_selection: dict[str, Any],
    portfolio_id: uuid.UUID,
) -> dict[str, Any]:
    """Run backtest in sync thread."""
    from vertical_engines.wealth.model_portfolio.track_record import compute_backtest

    fund_ids, weights = _extract_fund_weights(fund_selection)
    result = compute_backtest(
        db, fund_ids=fund_ids, weights=weights, portfolio_id=portfolio_id
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
        db, fund_ids=fund_ids, weights=weights, portfolio_id=portfolio_id
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

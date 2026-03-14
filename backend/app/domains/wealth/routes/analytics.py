"""Analytics router — backtest, optimizer, correlation."""

import uuid
from datetime import UTC, date, datetime

import numpy as np
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.database import get_db
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.backtest import BacktestRun
from app.domains.wealth.schemas.analytics import (
    BacktestRequest,
    BacktestRunRead,
    CorrelationMatrix,
    OptimizeRequest,
    OptimizeResult,
    ParetoOptimizeResult,
)
from app.routers.common import validate_profile as _validate_profile
from quant_engine.backtest_service import fetch_returns_matrix, walk_forward_backtest
from quant_engine.optimizer_service import (
    BlockConstraint,
    ProfileConstraints,
    compute_inputs_from_nav,
    optimize_portfolio,
    optimize_portfolio_pareto,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/analytics")


@router.post(
    "/backtest",
    response_model=BacktestRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Run backtest (async)",
    description="Submits a backtest run. Returns immediately with a run_id to poll for results.",
)
async def create_backtest(
    body: BacktestRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> BacktestRunRead:
    _validate_profile(body.profile)

    # If cv=True in params, run walk-forward backtest synchronously (on-demand analytics)
    cv_metrics = None
    error_message = None
    status = "pending"

    if body.params.cv:
        # Resolve blocks for this profile
        today = date.today()
        alloc_stmt = (
            select(StrategicAllocation)
            .where(
                StrategicAllocation.profile == body.profile,
                StrategicAllocation.effective_from <= today,
            )
            .where(
                (StrategicAllocation.effective_to.is_(None))
                | (StrategicAllocation.effective_to >= today)
            )
        )
        alloc_result = await db.execute(alloc_stmt)
        allocations = alloc_result.scalars().all()

        if allocations:
            block_ids = [a.block_id for a in allocations]
            gap = body.params.gap  # bounded 1–63 by BacktestParams schema
            try:
                returns_matrix, _, equal_weights = await fetch_returns_matrix(db, block_ids)
                cv_metrics = walk_forward_backtest(
                    returns_matrix=returns_matrix,
                    weights=equal_weights,
                    gap=gap,
                )
                status = "completed"
            except RuntimeError as e:
                # scikit-learn not installed or walk-forward internal error
                logger.error("backtest_runtime_error", profile=body.profile, error=str(e))
                error_message = "Backtest computation failed: required dependency unavailable"
                status = "failed"
            except ValueError as e:
                logger.error("backtest_value_error", profile=body.profile, error=str(e))
                error_message = "Backtest computation failed: invalid input parameters"
                status = "failed"
        else:
            error_message = f"No strategic allocation for profile '{body.profile}'"
            status = "failed"

    run = BacktestRun(
        profile=body.profile,
        params=body.params.model_dump(),
        status=status,
        cv_metrics=cv_metrics,
        error_message=error_message,
        completed_at=datetime.now(UTC) if status in ("completed", "failed") else None,
    )
    db.add(run)
    await db.flush()
    await db.refresh(run)
    return BacktestRunRead.model_validate(run)


@router.get(
    "/backtest/{run_id}",
    response_model=BacktestRunRead,
    summary="Backtest results",
    description="Returns the status and results of a backtest run.",
)
async def get_backtest(
    run_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> BacktestRunRead:
    result = await db.execute(select(BacktestRun).where(BacktestRun.run_id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found"
        )
    return BacktestRunRead.model_validate(run)


@router.post(
    "/optimize",
    response_model=OptimizeResult,
    summary="Portfolio optimization",
    description=(
        "Runs portfolio optimization using cvxpy with CLARABEL solver. "
        "If expected_returns is omitted, computes from historical NAV data. "
        "Requires NAV data in nav_timeseries (run ingestion first)."
    ),
)
async def optimize(
    body: OptimizeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> OptimizeResult:
    _validate_profile(body.profile)

    # Get strategic allocation blocks for this profile
    today = date.today()
    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == body.profile,
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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No strategic allocation found for profile '{body.profile}'",
        )

    block_ids = [a.block_id for a in allocations]

    # Compute covariance matrix and expected returns from NAV data
    try:
        cov_matrix, computed_returns = await compute_inputs_from_nav(db, block_ids)
    except ValueError as e:
        logger.error("optimize_inputs_error", profile=body.profile, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient NAV data to compute optimization inputs",
        )

    # Use provided expected returns or computed ones
    expected_returns = body.expected_returns if body.expected_returns else computed_returns

    # Build constraints from strategic allocation
    block_constraints = [
        BlockConstraint(
            block_id=a.block_id,
            min_weight=float(a.min_weight),
            max_weight=float(a.max_weight),
        )
        for a in allocations
    ]
    constraints = ProfileConstraints(blocks=block_constraints)

    result = await optimize_portfolio(
        block_ids=block_ids,
        expected_returns=expected_returns,
        cov_matrix=cov_matrix,
        constraints=constraints,
    )

    return OptimizeResult(
        profile=body.profile,
        weights=result.weights,
        expected_return=result.expected_return,
        expected_risk=result.portfolio_volatility,
        sharpe_ratio=result.sharpe_ratio,
    )


@router.post(
    "/optimize/pareto",
    response_model=ParetoOptimizeResult,
    summary="Multi-objective portfolio optimization (Pareto)",
    description=(
        "Runs NSGA-II multi-objective optimization producing a Pareto front of "
        "risk-return tradeoffs. WEEKLY / ON-DEMAND ONLY — takes 45–135s. "
        "Daily pipeline uses /optimize (CLARABEL). "
        "Falls back to CLARABEL if pymoo is not installed."
    ),
)
async def optimize_pareto(
    body: OptimizeRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> ParetoOptimizeResult:
    _validate_profile(body.profile)

    today = date.today()
    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == body.profile,
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
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No strategic allocation found for profile '{body.profile}'",
        )

    block_ids = [a.block_id for a in allocations]

    try:
        cov_matrix, computed_returns = await compute_inputs_from_nav(db, block_ids)
    except ValueError as e:
        logger.error("optimize_pareto_inputs_error", profile=body.profile, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient NAV data to compute optimization inputs",
        )

    expected_returns = body.expected_returns if body.expected_returns else computed_returns

    block_constraints = [
        BlockConstraint(
            block_id=a.block_id,
            min_weight=float(a.min_weight),
            max_weight=float(a.max_weight),
        )
        for a in allocations
    ]
    constraints = ProfileConstraints(blocks=block_constraints)

    result = await optimize_portfolio_pareto(
        block_ids=block_ids,
        expected_returns=expected_returns,
        cov_matrix=cov_matrix,
        constraints=constraints,
        profile=body.profile,
        calc_date=today,
    )

    return ParetoOptimizeResult(
        profile=body.profile,
        recommended_weights=result.recommended_weights,
        pareto_sharpe=result.pareto_sharpe,
        pareto_cvar=result.pareto_cvar,
        n_solutions=result.n_solutions,
        seed=result.seed,
        input_hash=result.input_hash,
        status=result.status,
    )


@router.get(
    "/correlation",
    response_model=CorrelationMatrix,
    summary="Correlation matrix",
    description=(
        "Returns correlation matrix across allocation blocks, "
        "computed from NAV time-series using 1-year lookback."
    ),
)
async def get_correlation(
    blocks: str = Query(..., description="Comma-separated block IDs"),
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> CorrelationMatrix:
    block_list = [b.strip() for b in blocks.split(",") if b.strip()]
    if not block_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="At least one block required"
        )
    if len(block_list) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least 2 blocks required for correlation matrix",
        )
    if len(block_list) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 50 blocks supported for correlation matrix",
        )
    if any(len(b) > 80 for b in block_list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Block ID exceeds maximum length of 80 characters",
        )

    try:
        cov_matrix, _ = await compute_inputs_from_nav(db, block_list)
    except ValueError as e:
        logger.error("correlation_inputs_error", blocks=block_list, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient NAV data to compute correlation matrix",
        )

    # Convert covariance to correlation
    std = np.sqrt(np.diag(cov_matrix))
    # Guard against zero std
    std = np.where(std == 0, 1e-10, std)
    corr = cov_matrix / np.outer(std, std)
    # Clip to [-1, 1] for numerical safety
    corr = np.clip(corr, -1.0, 1.0)

    return CorrelationMatrix(
        blocks=block_list,
        matrix=[[round(float(corr[i, j]), 6) for j in range(len(block_list))]
                for i in range(len(block_list))],
        as_of_date=date.today(),
    )

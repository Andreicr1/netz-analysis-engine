"""Analytics router — backtest, optimizer, correlation."""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime

import numpy as np
import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.jobs.sse import create_job_stream
from app.core.jobs.tracker import (
    get_redis_pool,
    publish_event,
    publish_terminal_event,
    register_job_owner,
)
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.backtest import BacktestRun
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.routes.common import validate_profile as _validate_profile
from app.domains.wealth.schemas.analytics import (
    BacktestRequest,
    BacktestRunRead,
    CorrelationMatrix,
    OptimizeRequest,
    OptimizeResult,
    ParetoOptimizeResult,
    RollingCorrelationResult,
)
from app.domains.wealth.services.quant_queries import compute_inputs_from_nav, fetch_returns_matrix
from quant_engine.backtest_service import walk_forward_backtest
from quant_engine.optimizer_service import (
    BlockConstraint,
    ProfileConstraints,
    optimize_portfolio,
    optimize_portfolio_pareto,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/analytics")


# ---------------------------------------------------------------------------
# Redis result cache helpers
# ---------------------------------------------------------------------------

def _hash_analytics_input(
    block_ids: list[str],
    returns: list[float],
    cov_matrix: list[list[float]] | None = None,
    extra: dict | None = None,
) -> str:
    """Deterministic hash of analytics inputs for cache key."""
    payload: dict = {
        "blocks": sorted(block_ids),
        "returns": [round(r, 8) for r in returns],
        "date": date.today().isoformat(),
    }
    if cov_matrix:
        payload["cov"] = [[round(c, 8) for c in row] for row in cov_matrix]
    if extra:
        payload.update(extra)
    encoded = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()[:24]


async def _get_cached_result(cache_key: str) -> dict | None:
    """Check Redis for cached analytics result."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.Redis(connection_pool=get_redis_pool())
        try:
            cached = await r.get(f"analytics:cache:{cache_key}")
            if cached:
                return json.loads(cached)
        finally:
            await r.aclose()
    except Exception:
        logger.debug("analytics_cache_miss", cache_key=cache_key)
    return None


async def _set_cached_result(cache_key: str, result: dict, ttl: int = 3600) -> None:
    """Cache analytics result in Redis (1h TTL)."""
    try:
        import redis.asyncio as aioredis

        r = aioredis.Redis(connection_pool=get_redis_pool())
        try:
            await r.set(
                f"analytics:cache:{cache_key}",
                json.dumps(result, default=str),
                ex=ttl,
            )
        finally:
            await r.aclose()
    except Exception:
        logger.debug("analytics_cache_set_failed", cache_key=cache_key)


@router.post(
    "/backtest",
    response_model=BacktestRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Run backtest (async)",
    description="Submits a backtest run. Returns immediately with a run_id to poll for results.",
)
async def create_backtest(
    body: BacktestRequest,
    db: AsyncSession = Depends(get_db_with_rls),
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
                | (StrategicAllocation.effective_to >= today),
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
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> BacktestRunRead:
    result = await db.execute(select(BacktestRun).where(BacktestRun.run_id == run_id))
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found",
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
    db: AsyncSession = Depends(get_db_with_rls),
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
            | (StrategicAllocation.effective_to >= today),
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
    expected_returns = body.expected_returns or computed_returns

    # Check Redis cache
    returns_list = [expected_returns[bid] for bid in block_ids] if isinstance(expected_returns, dict) else list(expected_returns)
    cache_key = _hash_analytics_input(block_ids, returns_list, cov_matrix.tolist())
    cached = await _get_cached_result(cache_key)
    if cached:
        logger.info("optimize_cache_hit", profile=body.profile, cache_key=cache_key)
        return OptimizeResult(**cached)

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

    result_dict = {
        "profile": body.profile,
        "weights": result.weights,
        "expected_return": result.expected_return,
        "expected_risk": result.portfolio_volatility,
        "sharpe_ratio": result.sharpe_ratio,
    }
    await _set_cached_result(cache_key, result_dict)

    return OptimizeResult(**result_dict)


@router.post(
    "/optimize/pareto",
    response_model=ParetoOptimizeResult,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Multi-objective portfolio optimization (Pareto) — async",
    description=(
        "Runs NSGA-II multi-objective optimization producing a Pareto front of "
        "risk-return tradeoffs. Returns 202 with a job_id immediately. "
        "Poll via GET /optimize/pareto/{job_id}/stream (SSE) for progress. "
        "WEEKLY / ON-DEMAND ONLY — takes 45–135s. "
        "Daily pipeline uses /optimize (CLARABEL). "
        "Falls back to CLARABEL if pymoo is not installed."
    ),
)
async def optimize_pareto(
    body: OptimizeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
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
            | (StrategicAllocation.effective_to >= today),
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

    expected_returns = body.expected_returns or computed_returns

    # Generate job ID for SSE tracking
    job_id = str(uuid.uuid4())
    await register_job_owner(job_id, str(actor.organization_id))

    # Snapshot inputs for background task (avoid session leak across async boundary)
    frozen_block_ids = list(block_ids)
    frozen_returns = (
        {k: float(v) for k, v in expected_returns.items()}
        if isinstance(expected_returns, dict)
        else list(expected_returns)
    )
    frozen_cov = cov_matrix.tolist()
    frozen_constraints = [
        {"block_id": a.block_id, "min_weight": float(a.min_weight), "max_weight": float(a.max_weight)}
        for a in allocations
    ]
    profile = body.profile

    async def _run_pareto() -> None:
        try:
            await publish_event(job_id, "progress", {"stage": "optimizing", "pct": 10})

            constraints = ProfileConstraints(blocks=[
                BlockConstraint(**c) for c in frozen_constraints
            ])
            cov = np.array(frozen_cov)

            result = await optimize_portfolio_pareto(
                block_ids=frozen_block_ids,
                expected_returns=frozen_returns,
                cov_matrix=cov,
                constraints=constraints,
                profile=profile,
                calc_date=today,
            )

            await publish_terminal_event(job_id, "done", {
                "profile": profile,
                "recommended_weights": result.recommended_weights,
                "pareto_sharpe": result.pareto_sharpe,
                "pareto_cvar": result.pareto_cvar,
                "n_solutions": result.n_solutions,
                "seed": result.seed,
                "input_hash": result.input_hash,
                "status": result.status,
            })
        except Exception as e:
            logger.exception("pareto_background_failed", job_id=job_id)
            await publish_terminal_event(job_id, "error", {"message": str(e)})

    background_tasks.add_task(_run_pareto)

    return ParetoOptimizeResult(
        profile=body.profile,
        recommended_weights={},
        pareto_sharpe=[],
        pareto_cvar=[],
        n_solutions=0,
        seed=0,
        input_hash="",
        status="generating",
        job_id=job_id,
    )


@router.get(
    "/optimize/pareto/{job_id}/stream",
    summary="SSE stream for Pareto optimization progress",
)
async def stream_pareto_progress(
    job_id: str,
    request: Request,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """SSE stream for Pareto optimization progress."""
    return await create_job_stream(request, job_id)


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
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> CorrelationMatrix:
    block_list = [b.strip() for b in blocks.split(",") if b.strip()]
    if not block_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="At least one block required",
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


@router.get(
    "/rolling-correlation",
    response_model=RollingCorrelationResult,
    summary="Rolling correlation between two instruments",
    description=(
        "Returns a time series of rolling Pearson correlation between two instruments, "
        "computed from daily returns in nav_timeseries."
    ),
)
async def get_rolling_correlation(
    inst_a: uuid.UUID = Query(..., description="First instrument UUID"),
    inst_b: uuid.UUID = Query(..., description="Second instrument UUID"),
    window_days: int = Query(90, ge=10, le=252, description="Rolling window in trading days"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RollingCorrelationResult:
    if inst_a == inst_b:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="inst_a and inst_b must be different instruments",
        )

    # Load instrument names
    inst_stmt = select(Instrument.instrument_id, Instrument.name).where(
        Instrument.instrument_id.in_([inst_a, inst_b]),
    )
    inst_result = await db.execute(inst_stmt)
    name_map = {row.instrument_id: row.name for row in inst_result.all()}

    if len(name_map) < 2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both instruments not found",
        )

    # Load returns for both instruments
    nav_stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id.in_([inst_a, inst_b]),
            NavTimeseries.return_1d.isnot(None),
        )
        .order_by(NavTimeseries.nav_date)
    )
    nav_result = await db.execute(nav_stmt)

    returns_a: dict[date, float] = {}
    returns_b: dict[date, float] = {}
    for row in nav_result.all():
        if row.instrument_id == inst_a:
            returns_a[row.nav_date] = float(row.return_1d)
        else:
            returns_b[row.nav_date] = float(row.return_1d)

    # Date intersection
    common_dates = sorted(set(returns_a.keys()) & set(returns_b.keys()))
    if len(common_dates) < window_days:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient overlapping data: {len(common_dates)} days (need {window_days})",
        )

    # Compute rolling correlation
    arr_a = np.array([returns_a[d] for d in common_dates])
    arr_b = np.array([returns_b[d] for d in common_dates])

    dates_out: list[str] = []
    values_out: list[float] = []

    for i in range(window_days, len(common_dates) + 1):
        window_a = arr_a[i - window_days:i]
        window_b = arr_b[i - window_days:i]
        corr = float(np.corrcoef(window_a, window_b)[0, 1])
        dates_out.append(common_dates[i - 1].isoformat())
        values_out.append(round(corr, 6))

    return RollingCorrelationResult(
        dates=dates_out,
        values=values_out,
        instrument_a=name_map[inst_a],
        instrument_b=name_map[inst_b],
    )

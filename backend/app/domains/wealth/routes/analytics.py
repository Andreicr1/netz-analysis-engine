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
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.backtest import BacktestRun
from app.domains.wealth.models.block import AllocationBlock
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.routes.common import validate_profile as _validate_profile
from app.domains.wealth.schemas.analytics import (
    BacktestRequest,
    BacktestRunRead,
    CorrelationMatrix,
    FactorAnalysisResponse,
    FactorContribution,
    FundRiskBudgetRead,
    MonteCarloConfidenceBar,
    MonteCarloRequest,
    MonteCarloResponse,
    OptimizeRequest,
    OptimizeResult,
    ParetoOptimizeResult,
    PeerGroupResponse,
    PeerRankingRead,
    RiskBudgetResponse,
    RollingCorrelationResult,
)
from app.domains.wealth.services.quant_queries import compute_inputs_from_nav, fetch_returns_matrix
from quant_engine.backtest_service import walk_forward_backtest
from quant_engine.factor_model_service import (
    compute_factor_contributions,
    decompose_factors,
)
from quant_engine.monte_carlo_service import run_monte_carlo
from quant_engine.optimizer_service import (
    BlockConstraint,
    ProfileConstraints,
    optimize_portfolio,
    optimize_portfolio_pareto,
)
from quant_engine.peer_group_service import compute_peer_rankings
from quant_engine.risk_budgeting_service import compute_risk_budget

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
    org_id: str = Depends(get_org_id),
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
        organization_id=org_id,
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


# ---------------------------------------------------------------------------
# Risk Budgeting (eVestment p.43-44)
# ---------------------------------------------------------------------------


async def _resolve_profile_weights(
    db: AsyncSession, profile: str,
) -> tuple[list[StrategicAllocation], list[str], list[str], np.ndarray]:
    """Resolve strategic allocations for a profile.

    Returns (allocations, block_ids, block_names, target_weights).
    """
    today = date.today()
    alloc_stmt = (
        select(StrategicAllocation, AllocationBlock.display_name)
        .join(AllocationBlock, AllocationBlock.block_id == StrategicAllocation.block_id)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= today),
        )
    )
    result = await db.execute(alloc_stmt)
    rows = result.all()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"No strategic allocation found for profile '{profile}'",
        )

    # Deduplicate by block_id — keep the latest effective_from per block
    # (overlapping date ranges cause duplicates, e.g. today boundary)
    seen: dict[str, tuple[StrategicAllocation, str]] = {}
    for alloc, display_name in rows:
        prev = seen.get(alloc.block_id)
        if prev is None or alloc.effective_from > prev[0].effective_from:
            seen[alloc.block_id] = (alloc, display_name)

    deduped = list(seen.values())
    allocations = [r[0] for r in deduped]
    block_ids = [a.block_id for a in allocations]
    block_names = [r[1] for r in deduped]
    weights = np.array([float(a.target_weight) for a in allocations])

    # Normalize weights to sum to 1
    w_sum = weights.sum()
    if w_sum > 0:
        weights = weights / w_sum

    return allocations, block_ids, block_names, weights


@router.post(
    "/risk-budget/{profile}",
    response_model=RiskBudgetResponse,
    summary="Risk budget decomposition (eVestment)",
    description=(
        "Computes MCTR, PCTR, MCETL, PCETL, and implied returns "
        "for each allocation block in the given profile. "
        "PCTR sums to 100%, PCETL sums to 100%."
    ),
)
async def get_risk_budget(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RiskBudgetResponse:
    _validate_profile(profile)

    allocations, block_ids, block_names, weights = await _resolve_profile_weights(db, profile)

    try:
        returns_matrix, _, _ = await fetch_returns_matrix(db, block_ids)
    except ValueError as e:
        logger.error("risk_budget_inputs_error", profile=profile, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient NAV data to compute risk budget",
        )

    result = compute_risk_budget(
        weights=weights,
        returns_matrix=returns_matrix,
        block_ids=block_ids,
        block_names=block_names,
    )

    return RiskBudgetResponse(
        profile=profile,
        portfolio_volatility=result.portfolio_volatility,
        portfolio_etl=result.portfolio_etl,
        portfolio_starr=result.portfolio_starr,
        funds=[
            FundRiskBudgetRead(
                block_id=f.block_id,
                block_name=f.block_name,
                weight=f.weight,
                mean_return=f.mean_return,
                mctr=f.mctr,
                pctr=f.pctr,
                mcetl=f.mcetl,
                pcetl=f.pcetl,
                implied_return_vol=f.implied_return_vol,
                implied_return_etl=f.implied_return_etl,
                difference_vol=f.difference_vol,
                difference_etl=f.difference_etl,
            )
            for f in result.funds
        ],
        as_of_date=date.today(),
    )


# ---------------------------------------------------------------------------
# Factor Analysis (eVestment p.46)
# ---------------------------------------------------------------------------


@router.get(
    "/factor-analysis/{profile}",
    response_model=FactorAnalysisResponse,
    summary="Factor analysis decomposition (PCA)",
    description=(
        "Decomposes portfolio risk into systematic (factor) and specific "
        "(idiosyncratic) components using PCA. Returns factor contributions "
        "and R² per factor."
    ),
)
async def get_factor_analysis(
    profile: str,
    n_factors: int = Query(3, ge=1, le=10, description="Number of PCA factors"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> FactorAnalysisResponse:
    _validate_profile(profile)

    _, block_ids, _, weights = await _resolve_profile_weights(db, profile)

    try:
        returns_matrix, _, _ = await fetch_returns_matrix(db, block_ids)
    except ValueError as e:
        logger.error("factor_analysis_inputs_error", profile=profile, error=str(e))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Insufficient NAV data to compute factor analysis",
        )

    # Align weights to returns matrix columns (fetch_returns_matrix may
    # return fewer columns than block_ids if some blocks lack NAV data)
    n_cols = returns_matrix.shape[1]
    if len(weights) != n_cols:
        weights = weights[:n_cols] if len(weights) > n_cols else np.pad(weights, (0, n_cols - len(weights)))
        w_sum = weights.sum()
        if w_sum > 0:
            weights = weights / w_sum

    # Run PCA decomposition
    factor_result = decompose_factors(
        returns_matrix=returns_matrix,
        macro_proxies=None,
        portfolio_weights=weights,
        n_factors=n_factors,
    )

    # Compute factor contributions
    contributions = compute_factor_contributions(factor_result)

    return FactorAnalysisResponse(
        profile=profile,
        systematic_risk_pct=contributions.systematic_risk_pct,
        specific_risk_pct=contributions.specific_risk_pct,
        factor_contributions=[
            FactorContribution(
                factor_label=fc["factor_label"],
                pct_contribution=fc["pct_contribution"],
            )
            for fc in contributions.factor_contributions
        ],
        r_squared=contributions.r_squared,
        portfolio_factor_exposures=factor_result.portfolio_factor_exposures,
        as_of_date=date.today(),
    )


# ---------------------------------------------------------------------------
# Monte Carlo Simulation
# ---------------------------------------------------------------------------


@router.post(
    "/monte-carlo",
    response_model=MonteCarloResponse,
    summary="Monte Carlo simulation (block bootstrap)",
    description=(
        "Runs bootstrapped Monte Carlo simulation on a fund or model portfolio. "
        "Uses 21-day block bootstrap to preserve autocorrelation. "
        "Supports max_drawdown, return, and sharpe statistics. "
        "Results cached in Redis (1h TTL)."
    ),
)
async def run_monte_carlo_endpoint(
    body: MonteCarloRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> MonteCarloResponse:
    from app.domains.wealth.models.instrument import Instrument
    from app.domains.wealth.models.model_portfolio import ModelPortfolio
    from app.domains.wealth.services.nav_reader import fetch_nav_series, is_model_portfolio

    # Resolve entity name
    entity_id = body.entity_id
    if await is_model_portfolio(db, entity_id):
        row = await db.execute(
            select(ModelPortfolio.display_name).where(ModelPortfolio.id == entity_id),
        )
        entity_name = row.scalar_one_or_none() or "Model Portfolio"
    else:
        row = await db.execute(
            select(Instrument.name).where(Instrument.instrument_id == entity_id),
        )
        entity_name = row.scalar_one_or_none()
        if entity_name is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")

    # Check Redis cache
    cache_extra = {
        "entity_id": str(entity_id),
        "statistic": body.statistic,
        "n_sims": body.n_simulations,
        "horizons": body.horizons or [252, 756, 1260, 1764, 2520],
    }
    cache_key = hashlib.sha256(
        json.dumps(cache_extra, sort_keys=True, default=str).encode(),
    ).hexdigest()[:24]
    cached = await _get_cached_result(f"mc:{cache_key}")
    if cached:
        return MonteCarloResponse(**cached)

    # Fetch NAV data (max lookback for robust bootstrap)
    from datetime import timedelta

    today = date.today()
    start_date = today - timedelta(days=int(1260 * 1.5))  # ~5Y buffer
    nav_rows = await fetch_nav_series(db, entity_id, start_date, today)

    if len(nav_rows) < 42:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient NAV data: {len(nav_rows)} rows (need ≥ 42)",
        )

    daily_returns = np.array([
        r.daily_return if r.daily_return is not None else 0.0
        for r in nav_rows
    ])

    result = run_monte_carlo(
        daily_returns=daily_returns,
        n_simulations=body.n_simulations,
        horizons=body.horizons,
        statistic=body.statistic,
    )

    response_dict = {
        "entity_id": entity_id,
        "entity_name": entity_name,
        "n_simulations": result.n_simulations,
        "statistic": result.statistic,
        "percentiles": result.percentiles,
        "mean": result.mean,
        "median": result.median,
        "std": result.std,
        "historical_value": result.historical_value,
        "confidence_bars": result.confidence_bars,
    }

    await _set_cached_result(f"mc:{cache_key}", response_dict)

    return MonteCarloResponse(
        entity_id=entity_id,
        entity_name=entity_name,
        n_simulations=result.n_simulations,
        statistic=result.statistic,
        percentiles=result.percentiles,
        mean=result.mean,
        median=result.median,
        std=result.std,
        historical_value=result.historical_value,
        confidence_bars=[
            MonteCarloConfidenceBar(**cb) for cb in result.confidence_bars
        ],
    )


# ---------------------------------------------------------------------------
# Peer Group Rankings (eVestment Section IV)
# ---------------------------------------------------------------------------


@router.get(
    "/peer-group/{entity_id}",
    response_model=PeerGroupResponse,
    summary="Peer group rankings (eVestment Section IV)",
    description=(
        "Ranks a fund against strategy-matched peers on key risk/return metrics. "
        "Uses strategy_label from instruments_universe for cohort selection. "
        "Falls back to broader category if exact cohort < 10 funds."
    ),
)
async def get_peer_group(
    entity_id: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> PeerGroupResponse:
    from app.domains.wealth.models.risk import FundRiskMetrics
    from app.domains.wealth.routes.entity_analytics import _resolve_entity_uuid

    # Resolve catalog external_id to UUID
    resolved_id = await _resolve_entity_uuid(db, entity_id)

    # Resolve entity name and strategy_label
    inst_row = await db.execute(
        select(Instrument.name, Instrument.attributes)
        .where(Instrument.instrument_id == resolved_id),
    )
    inst = inst_row.one_or_none()
    if inst is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")

    entity_name = inst[0]
    attrs = inst[1] or {}
    strategy_label = attrs.get("strategy_label", "")

    if not strategy_label:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Entity has no strategy_label — peer group comparison unavailable",
        )

    # Fetch fund's latest risk metrics
    fund_row = await db.execute(
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id == resolved_id)
        .order_by(FundRiskMetrics.calc_date.desc())
        .limit(1),
    )
    fund_metrics_obj = fund_row.scalar_one_or_none()
    if fund_metrics_obj is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No risk metrics available for this entity",
        )

    fund_date = fund_metrics_obj.calc_date

    # Fetch all peer funds with same strategy_label
    peer_stmt = (
        select(FundRiskMetrics)
        .join(Instrument, Instrument.instrument_id == FundRiskMetrics.instrument_id)
        .where(
            Instrument.attributes["strategy_label"].as_string() == strategy_label,
            FundRiskMetrics.calc_date == fund_date,
            FundRiskMetrics.instrument_id != resolved_id,
        )
    )
    peer_result = await db.execute(peer_stmt)
    peer_rows = peer_result.scalars().all()

    # Fallback: if < 10 peers, widen search (not filtered by strategy)
    if len(peer_rows) < 10:
        wider_stmt = (
            select(FundRiskMetrics)
            .where(
                FundRiskMetrics.calc_date == fund_date,
                FundRiskMetrics.instrument_id != resolved_id,
                FundRiskMetrics.sharpe_1y.isnot(None),
            )
            .limit(500)
        )
        wider_result = await db.execute(wider_stmt)
        wider_rows = wider_result.scalars().all()
        if len(wider_rows) > len(peer_rows):
            peer_rows = wider_rows
            strategy_label = f"{strategy_label} (broadened)"

    # Convert to dicts for peer_group_service
    def _to_dict(obj: FundRiskMetrics) -> dict[str, float | None]:
        return {
            "sharpe_1y": float(obj.sharpe_1y) if obj.sharpe_1y is not None else None,
            "sortino_1y": float(obj.sortino_1y) if obj.sortino_1y is not None else None,
            "return_1y": float(obj.return_1y) if obj.return_1y is not None else None,
            "max_drawdown_1y": float(obj.max_drawdown_1y) if obj.max_drawdown_1y is not None else None,
            "volatility_1y": float(obj.volatility_1y) if obj.volatility_1y is not None else None,
            "alpha_1y": float(obj.alpha_1y) if obj.alpha_1y is not None else None,
            "manager_score": float(obj.manager_score) if obj.manager_score is not None else None,
        }

    fund_dict = _to_dict(fund_metrics_obj)
    peer_dicts = [_to_dict(p) for p in peer_rows]

    result = compute_peer_rankings(
        fund_metrics=fund_dict,
        peer_metrics=peer_dicts,
        strategy_label=strategy_label,
    )

    return PeerGroupResponse(
        entity_id=resolved_id,
        entity_name=entity_name,
        strategy_label=result.strategy_label,
        peer_count=result.peer_count,
        rankings=[
            PeerRankingRead(
                metric_name=r.metric_name,
                value=r.value,
                percentile=r.percentile,
                quartile=r.quartile,
                peer_count=r.peer_count,
                peer_median=r.peer_median,
                peer_p25=r.peer_p25,
                peer_p75=r.peer_p75,
            )
            for r in result.rankings
        ],
        as_of_date=fund_date,
    )

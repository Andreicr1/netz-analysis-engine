"""Model Portfolio API routes — CRUD, construction, track-record, stress.

All endpoints use get_db_with_rls and response_model + model_validate().
IC role required for creation and construction.

Construction invokes CLARABEL fund-level optimizer with block-group constraints
from StrategicAllocation and CVaR limit from profile config.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import numpy as np
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
    from app.domains.wealth.models.model_portfolio_nav import ModelPortfolioNav

    result = await db.execute(
        select(ModelPortfolio).where(ModelPortfolio.id == portfolio_id)
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
        .order_by(ModelPortfolioNav.nav_date)
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
        "backtest": None,  # Populated by POST /backtest
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

        with sync_session_factory() as sync_db, sync_db.begin():
            sync_db.expire_on_commit = False
            from sqlalchemy import text
            safe_oid = str(_org_id).replace("'", "")
            sync_db.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
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

        with sync_session_factory() as sync_db, sync_db.begin():
            sync_db.expire_on_commit = False
            from sqlalchemy import text
            safe_oid = str(_org_id_stress).replace("'", "")
            sync_db.execute(text(f"SET LOCAL app.current_organization_id = '{safe_oid}'"))
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
    1. Load approved universe + manager_score
    2. Query StrategicAllocation for block constraints + CVaR limit
    3. Compute fund-level covariance + expected returns from NAV timeseries
    4. Invoke CLARABEL fund-level optimizer with block-group constraints
    5. Build PortfolioComposition from optimizer output
    6. Fallback to block-level heuristic if fund-level optimization fails
    """
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

    # ── 1. Load approved universe ──
    universe_funds = await _load_universe_funds(db, org_id)
    if not universe_funds:
        return {"funds": [], "profile": profile, "error": "No approved funds in universe"}

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

    strategic_targets = {a.block_id: float(a.target_weight) for a in allocations}

    # ── Resolve CVaR limit from profile config ──
    cvar_limit = await _resolve_cvar_limit(db, profile)

    block_constraints = [
        BlockConstraint(
            block_id=a.block_id,
            min_weight=float(a.min_weight),
            max_weight=float(a.max_weight),
        )
        for a in allocations
    ]

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
        cov_matrix, expected_returns, available_ids = await compute_fund_level_inputs(
            db, fund_instrument_ids
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

        # Filter constraints to blocks that have at least one fund
        covered_blocks = set(sub_blocks.values())
        active_block_constraints = [
            bc for bc in block_constraints if bc.block_id in covered_blocks
        ]
        active_constraints = ProfileConstraints(
            blocks=active_block_constraints,
            cvar_limit=cvar_limit,
            max_single_fund_weight=max_single_fund,
        )

        fund_result: FundOptimizationResult = await optimize_fund_portfolio(
            fund_ids=opt_fund_ids,
            fund_blocks=sub_blocks,
            expected_returns=sub_returns,
            cov_matrix=sub_cov,
            constraints=active_constraints,
        )

        if fund_result.status == "optimal" and fund_result.weights:
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

    # Use actual CVaR from optimizer (not volatility)
    cvar_current_val = optimization.get("cvar_95")
    cvar_limit_val = optimization.get("cvar_limit")

    # Compute utilization: |cvar_current / cvar_limit| × 100
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
        )
    )

    snapshot = PortfolioSnapshot(
        organization_id=org_id,
        profile=portfolio.profile,
        snapshot_date=snapshot_date,
        weights=block_weights,
        fund_selection=fund_selection,
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

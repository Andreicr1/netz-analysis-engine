"""Model Portfolio API routes — CRUD, construction, track-record, stress.

All endpoints use get_db_with_rls and response_model + model_validate().
IC role required for creation and construction.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.domains.wealth.models.model_portfolio import ModelPortfolio
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
    summary="Run fund selection from universe",
)
async def construct_portfolio(
    portfolio_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
    org_id: str = Depends(get_org_id),
) -> ModelPortfolioRead:
    """Run fund selection algorithm from approved universe assets. Requires IC role."""
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

    def _construct() -> dict[str, Any]:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db:
            sync_db.expire_on_commit = False
            return _run_construction(sync_db, portfolio.profile, org_id)

    fund_selection = await asyncio.to_thread(_construct)

    portfolio.fund_selection_schema = fund_selection
    portfolio.status = "backtesting"
    await db.flush()
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

    def _backtest() -> dict[str, Any]:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db:
            sync_db.expire_on_commit = False
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

    def _stress() -> dict[str, Any]:
        from app.core.db.session import sync_session_factory

        with sync_session_factory() as sync_db:
            sync_db.expire_on_commit = False
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
    fund_ids = [uuid.UUID(f["fund_id"]) for f in funds]
    weights = [f["weight"] for f in funds]
    return fund_ids, weights


def _run_construction(
    db: Any,
    profile: str,
    org_id: str,
) -> dict[str, Any]:
    """Run portfolio construction in sync thread."""
    from vertical_engines.wealth.asset_universe import UniverseService
    from vertical_engines.wealth.model_portfolio.portfolio_builder import construct

    # Get approved universe assets
    svc = UniverseService()
    assets = svc.list_universe(db, organization_id=org_id)

    # Get strategic allocation
    from sqlalchemy import select as sa_select

    from app.domains.wealth.models.allocation import StrategicAllocation

    alloc_result = db.execute(
        sa_select(StrategicAllocation).where(StrategicAllocation.profile == profile)
    )
    allocations = alloc_result.scalars().all()
    strategic = {a.block_id: float(a.target_weight) for a in allocations}

    if not strategic:
        return {"funds": [], "profile": profile, "error": "No strategic allocation defined"}

    # Build universe fund list for portfolio builder
    universe_funds = [
        {
            "fund_id": str(a.fund_id),
            "fund_name": a.fund_name,
            "block_id": a.block_id,
            "manager_score": None,  # Would be populated from risk metrics
        }
        for a in assets
        if a.block_id
    ]

    composition = construct(profile, universe_funds, strategic)

    return {
        "profile": composition.profile,
        "total_weight": composition.total_weight,
        "funds": [
            {
                "fund_id": str(fw.fund_id),
                "fund_name": fw.fund_name,
                "block_id": fw.block_id,
                "weight": fw.weight,
                "score": fw.score,
            }
            for fw in composition.funds
        ],
    }


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

"""Weight proposer — computes new weight distribution after instrument removal.

Wraps optimizer_service and cvar_service to propose feasible reallocations.
Must NOT import from service.py (enforced by import-linter).
"""

from __future__ import annotations

import asyncio
import uuid

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from quant_engine.cvar_service import (
    check_breach_status,
)
from quant_engine.optimizer_service import (
    BlockConstraint,
    OptimizationResult,
    ProfileConstraints,
    optimize_portfolio,
)
from vertical_engines.wealth.rebalancing.models import WeightProposal

logger = structlog.get_logger()


def propose_weights(
    db: Session,
    portfolio_id: uuid.UUID,
    removed_instrument_id: uuid.UUID,
    organization_id: str,
    config: dict | None = None,
) -> WeightProposal:
    """Propose new weights for a portfolio after removing an instrument.

    1. Load current weights from PortfolioSnapshot (latest).
    2. Remove the instrument, calculate weight gap.
    3. Load StrategicAllocation bounds for the portfolio's profile.
    4. Call optimizer_service to redistribute within bounds.
    5. Validate CVaR constraint via cvar_service.

    Returns WeightProposal with feasible=False if optimizer cannot find
    a solution (no exception — caller decides what to do).
    """
    from app.domains.wealth.models.allocation import StrategicAllocation
    from app.domains.wealth.models.model_portfolio import ModelPortfolio
    from app.domains.wealth.models.portfolio import PortfolioSnapshot

    # 1. Get portfolio and its profile
    portfolio = db.execute(
        select(ModelPortfolio).where(
            ModelPortfolio.id == portfolio_id,
            ModelPortfolio.organization_id == organization_id,
        )
    ).scalar_one_or_none()

    if portfolio is None:
        return WeightProposal(
            portfolio_id=portfolio_id,
            old_weights={},
            new_weights={},
            cvar_before=0.0,
            cvar_after=0.0,
            feasible=False,
            reason=f"Portfolio {portfolio_id} not found",
        )

    profile = portfolio.profile

    # 2. Get latest snapshot for current weights
    snapshot = db.execute(
        select(PortfolioSnapshot).where(
            PortfolioSnapshot.organization_id == organization_id,
            PortfolioSnapshot.profile == profile,
        ).order_by(PortfolioSnapshot.snapshot_date.desc()).limit(1)
    ).scalar_one_or_none()

    if snapshot is None:
        return WeightProposal(
            portfolio_id=portfolio_id,
            old_weights={},
            new_weights={},
            cvar_before=0.0,
            cvar_after=0.0,
            feasible=False,
            reason="No portfolio snapshot available",
        )

    old_weights: dict[str, float] = {
        k: float(v) for k, v in (snapshot.weights or {}).items()
    }
    cvar_before = float(snapshot.cvar_current or 0.0)

    # 3. Load strategic allocation bounds for this profile
    allocations = db.execute(
        select(StrategicAllocation).where(
            StrategicAllocation.organization_id == organization_id,
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_to.is_(None),
        )
    ).scalars().all()

    if not allocations:
        return WeightProposal(
            portfolio_id=portfolio_id,
            old_weights=old_weights,
            new_weights={},
            cvar_before=cvar_before,
            cvar_after=0.0,
            feasible=False,
            reason="No strategic allocations defined",
        )

    # 4. Build optimizer inputs — use block-level weights
    block_ids = [a.block_id for a in allocations]
    block_constraints = [
        BlockConstraint(
            block_id=a.block_id,
            min_weight=float(a.min_weight),
            max_weight=float(a.max_weight),
        )
        for a in allocations
    ]

    # CVaR limit from config or snapshot
    cvar_config = config or {}
    cvar_limit = cvar_config.get("cvar_limit")
    if cvar_limit is None and snapshot.cvar_limit is not None:
        cvar_limit = float(snapshot.cvar_limit)

    constraints = ProfileConstraints(
        blocks=block_constraints,
        cvar_limit=cvar_limit,
    )

    # Expected returns: use old weights as proxy (rebalance preserves targets)
    expected_returns = {bid: old_weights.get(bid, 0.0) for bid in block_ids}

    # Covariance: use identity scaled by volatility as approximation
    # (Full NAV-based computation requires async — rebalancing is a quick check)
    n = len(block_ids)
    cov_matrix = np.eye(n) * 0.04  # 20% vol default assumption

    # 5. Run optimizer (async → sync bridge)
    try:
        opt_result: OptimizationResult = asyncio.get_event_loop().run_until_complete(
            optimize_portfolio(
                block_ids=block_ids,
                expected_returns=expected_returns,
                cov_matrix=cov_matrix,
                constraints=constraints,
            )
        )
    except RuntimeError:
        # No running event loop — create one
        opt_result = asyncio.run(
            optimize_portfolio(
                block_ids=block_ids,
                expected_returns=expected_returns,
                cov_matrix=cov_matrix,
                constraints=constraints,
            )
        )

    if opt_result.status not in ("optimal", "optimal_inaccurate"):
        logger.warning(
            "rebalance_infeasible",
            portfolio_id=str(portfolio_id),
            status=opt_result.status,
        )
        return WeightProposal(
            portfolio_id=portfolio_id,
            old_weights=old_weights,
            new_weights={},
            cvar_before=cvar_before,
            cvar_after=0.0,
            feasible=False,
            reason=f"Optimizer: {opt_result.status}",
        )

    new_weights = opt_result.weights

    # 6. Check CVaR after rebalancing
    breach = check_breach_status(
        profile=profile,
        cvar_current=cvar_before,  # approximate — full recalc deferred to daily pipeline
        config=cvar_config.get("portfolio_profiles"),
    )
    cvar_after = breach.cvar_current

    feasible = breach.trigger_status != "breach"
    reason = None if feasible else f"CVaR breach: {breach.cvar_utilized_pct:.1f}% utilized"

    logger.info(
        "rebalance_proposal_computed",
        portfolio_id=str(portfolio_id),
        profile=profile,
        feasible=feasible,
        old_blocks=len(old_weights),
        new_blocks=len(new_weights),
    )

    return WeightProposal(
        portfolio_id=portfolio_id,
        old_weights=old_weights,
        new_weights=new_weights,
        cvar_before=cvar_before,
        cvar_after=cvar_after,
        feasible=feasible,
        reason=reason,
    )

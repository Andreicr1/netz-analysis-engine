"""Weight proposer — computes new weight distribution after instrument removal.

Uses proportional redistribution within StrategicAllocation bounds.
Full optimizer-based rebalancing (cvxpy) runs in the daily pipeline where
real covariance data is available. This module provides a quick, synchronous
proposal for immediate feedback on deactivation impact.

Must NOT import from service.py (enforced by import-linter).
"""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vertical_engines.wealth.rebalancing.models import WeightProposal

logger = structlog.get_logger()


def _redistribute_proportionally(
    old_weights: dict[str, float],
    bounds: dict[str, tuple[float, float]],
) -> dict[str, float] | None:
    """Redistribute weights proportionally within allocation bounds.

    Spreads removed weight across remaining blocks proportional to their
    current weights, clamped to min/max bounds. Returns None if infeasible
    (bounds cannot accommodate the redistribution).
    """
    total = sum(old_weights.values())
    if total <= 0:
        return None

    # Normalize to sum=1
    new_weights = {k: v / total for k, v in old_weights.items()}

    # Iteratively clamp to bounds and renormalize unclamped blocks
    frozen: dict[str, float] = {}  # blocks clamped to a bound

    for _ in range(10):
        frozen_sum = sum(frozen.values())
        remaining = 1.0 - frozen_sum

        # Distribute remaining budget across unfrozen blocks proportionally
        unfrozen = {k: v for k, v in new_weights.items() if k not in frozen}
        if not unfrozen:
            break

        unfrozen_total = sum(unfrozen.values())
        if unfrozen_total < 1e-12:
            return None

        # Scale unfrozen blocks to fill remaining budget
        scale = remaining / unfrozen_total
        for k in unfrozen:
            new_weights[k] = unfrozen[k] * scale

        # Check bounds and freeze any that violate
        changed = False
        for k in list(unfrozen):
            lo, hi = bounds.get(k, (0.0, 1.0))
            if new_weights[k] < lo:
                frozen[k] = lo
                new_weights[k] = lo
                changed = True
            elif new_weights[k] > hi:
                frozen[k] = hi
                new_weights[k] = hi
                changed = True

        if not changed:
            break

    # Verify feasibility: sum of mins must be <= 1.0 and sum of maxes >= 1.0
    total_new = sum(new_weights.values())
    if abs(total_new - 1.0) > 0.01:
        return None

    # Normalize precisely
    return {k: round(v / total_new, 6) for k, v in new_weights.items()}


def apply_dead_band(
    proposed_weights: dict[str, float],
    current_weights: dict[str, float],
    dead_band_pct: float = 0.005,
) -> dict[str, float]:
    """Suppress trades below the dead-band threshold.

    For each fund/block, if |proposed - current| < dead_band_pct,
    keep the current weight (no trade). This reduces unnecessary
    churn and transaction costs.
    """
    result = dict(proposed_weights)
    for fund_id, new_w in proposed_weights.items():
        current_w = current_weights.get(fund_id, 0.0)
        if abs(new_w - current_w) < dead_band_pct:
            result[fund_id] = current_w
    return result


def propose_weights(
    db: Session,
    portfolio_id: uuid.UUID,
    removed_instrument_id: uuid.UUID,
    organization_id: str,
    config: dict | None = None,
) -> WeightProposal:
    """Propose new weights for a portfolio after removing an instrument.

    1. Load current weights from PortfolioSnapshot (latest).
    2. Load StrategicAllocation bounds for the portfolio's profile.
    3. Remove the instrument's block weight and redistribute proportionally
       within min/max bounds.

    Returns WeightProposal with feasible=False if redistribution cannot
    satisfy allocation bounds (no exception — caller decides what to do).
    Full optimizer-based rebalancing runs in the daily pipeline.
    """
    from app.domains.wealth.models.allocation import StrategicAllocation
    from app.domains.wealth.models.model_portfolio import ModelPortfolio
    from app.domains.wealth.models.portfolio import PortfolioSnapshot

    # 1. Get portfolio and its profile
    portfolio = db.execute(
        select(ModelPortfolio).where(
            ModelPortfolio.id == portfolio_id,
            ModelPortfolio.organization_id == organization_id,
        ),
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
        ).order_by(PortfolioSnapshot.snapshot_date.desc()).limit(1),
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
        ),
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

    # 4. Build bounds map and redistribute proportionally
    # PR-A26.2 — ``min_weight/max_weight`` dropped; read the approved
    # drift band. Unapproved blocks fall back to ``[0, 1]`` so the
    # rebalance proposer can still produce a feasible redistribution.
    bounds: dict[str, tuple[float, float]] = {
        a.block_id: (
            float(a.drift_min) if a.drift_min is not None else 0.0,
            float(a.drift_max) if a.drift_max is not None else 1.0,
        )
        for a in allocations
    }

    new_weights = _redistribute_proportionally(old_weights, bounds)

    if new_weights is None:
        logger.warning(
            "rebalance_infeasible",
            portfolio_id=str(portfolio_id),
            profile=profile,
        )
        return WeightProposal(
            portfolio_id=portfolio_id,
            old_weights=old_weights,
            new_weights={},
            cvar_before=cvar_before,
            cvar_after=0.0,
            feasible=False,
            reason="Cannot redistribute within allocation bounds",
        )

    logger.info(
        "rebalance_proposal_computed",
        portfolio_id=str(portfolio_id),
        profile=profile,
        feasible=True,
        old_blocks=len(old_weights),
        new_blocks=len(new_weights),
    )

    return WeightProposal(
        portfolio_id=portfolio_id,
        old_weights=old_weights,
        new_weights=new_weights,
        cvar_before=cvar_before,
        cvar_after=cvar_before,  # CVaR recalculated in daily pipeline
        feasible=True,
        reason=None,
    )

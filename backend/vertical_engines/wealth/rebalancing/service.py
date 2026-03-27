"""Rebalancing Service — entry point for rebalance impact and weight proposals.

Session injection pattern: caller provides db session.
Composes impact_analyzer (identify affected portfolios) and
weight_proposer (compute new weights via proportional redistribution).

Regime change detection: sustained regime switch for N consecutive
evaluations triggers rebalancing. Threshold configurable via ConfigService.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vertical_engines.wealth.rebalancing.impact_analyzer import compute_impact
from vertical_engines.wealth.rebalancing.models import (
    RebalanceImpact,
    RebalanceResult,
    WeightProposal,
)
from vertical_engines.wealth.rebalancing.weight_proposer import propose_weights

logger = structlog.get_logger()

# Default: 2 consecutive stress evaluations trigger rebalance
_DEFAULT_REGIME_CONSECUTIVE_THRESHOLD = 2


class RebalancingService:
    """Rebalancing engine for instrument removal and regime change triggers."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._config = config or {}
        self._regime_threshold = self._config.get(
            "regime_consecutive_threshold",
            _DEFAULT_REGIME_CONSECUTIVE_THRESHOLD,
        )

    def compute_rebalance_impact(
        self,
        db: Session,
        instrument_id: uuid.UUID,
        organization_id: str,
        trigger: str = "deactivation",
    ) -> RebalanceResult:
        """Compute full rebalance impact and weight proposals.

        1. Identify affected portfolios via impact_analyzer.
        2. For each affected portfolio, compute a weight proposal.
        3. Return aggregated result.
        """
        impact = compute_impact(
            db=db,
            instrument_id=instrument_id,
            organization_id=organization_id,
            trigger=trigger,
        )

        proposals: list[WeightProposal] = []
        for portfolio_id in impact.affected_portfolios:
            proposal = propose_weights(
                db=db,
                portfolio_id=portfolio_id,
                removed_instrument_id=instrument_id,
                organization_id=organization_id,
                config=self._config,
            )
            proposals.append(proposal)

        all_feasible = all(p.feasible for p in proposals) if proposals else True

        logger.info(
            "rebalance_computed",
            instrument_id=str(instrument_id),
            trigger=trigger,
            affected_count=len(impact.affected_portfolios),
            all_feasible=all_feasible,
        )

        return RebalanceResult(
            impact=impact,
            proposals=tuple(proposals),
            all_feasible=all_feasible,
            computed_at=datetime.now(UTC),
        )

    def propose_adjustments(
        self,
        db: Session,
        portfolio_id: uuid.UUID,
        removed_instrument_id: uuid.UUID,
        organization_id: str,
    ) -> WeightProposal:
        """Compute weight proposal for a single portfolio."""
        return propose_weights(
            db=db,
            portfolio_id=portfolio_id,
            removed_instrument_id=removed_instrument_id,
            organization_id=organization_id,
            config=self._config,
        )

    def detect_regime_trigger(
        self,
        db: Session,
        organization_id: str,
    ) -> list[RebalanceResult]:
        """Detect regime changes that warrant rebalancing.

        Checks PortfolioSnapshot for consecutive regime switches from
        normal/low_vol to stress/crisis. If sustained for >= threshold
        consecutive evaluations, triggers rebalance for affected instruments.

        Will be wired to a scheduler/worker in a follow-up sprint.
        """
        from app.domains.wealth.models.model_portfolio import ModelPortfolio

        # Get latest N snapshots per profile to detect consecutive regime changes
        threshold = self._regime_threshold
        _STRESS_REGIMES = frozenset({"stress", "crisis"})

        from sqlalchemy import text

        rows = db.execute(text("""
            SELECT p.profile, s.snapshot_date, s.regime
            FROM (
                SELECT DISTINCT profile
                FROM portfolio_snapshots
                WHERE organization_id = :org_id
            ) p
            CROSS JOIN LATERAL (
                SELECT snapshot_date, regime
                FROM portfolio_snapshots ps
                WHERE ps.organization_id = :org_id AND ps.profile = p.profile
                ORDER BY ps.snapshot_date DESC
                LIMIT :threshold
            ) s
        """), {"org_id": organization_id, "threshold": threshold}).all()

        # Group by profile
        from collections import defaultdict
        profile_snapshots: dict[str, list[tuple]] = defaultdict(list)
        for profile_name, snapshot_date, regime in rows:
            profile_snapshots[profile_name].append((snapshot_date, regime))

        results: list[RebalanceResult] = []

        for profile, snapshots in profile_snapshots.items():
            if len(snapshots) < threshold:
                continue

            # Check if all recent snapshots are in stress regime
            consecutive_stress = all(
                regime in _STRESS_REGIMES for _, regime in snapshots
            )

            if not consecutive_stress:
                continue

            logger.warning(
                "regime_change_trigger",
                profile=profile,
                consecutive_stress=threshold,
                organization_id=organization_id,
            )

            # Look up actual ModelPortfolio IDs for this profile
            portfolio_ids = [
                row[0] for row in db.execute(
                    select(ModelPortfolio.id).where(
                        ModelPortfolio.organization_id == organization_id,
                        ModelPortfolio.profile == profile,
                        ModelPortfolio.status == "active",
                    ),
                ).all()
            ]

            regime_impact = RebalanceImpact(
                instrument_id=uuid.UUID(int=0),
                affected_portfolios=tuple(portfolio_ids),
                weight_gap=0.0,
                trigger="regime_change",
            )

            results.append(RebalanceResult(
                impact=regime_impact,
                proposals=(),
                all_feasible=True,
                computed_at=datetime.now(UTC),
            ))

        return results

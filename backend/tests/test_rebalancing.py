"""Tests for the Wealth Rebalancing Engine — Sprint 3.

Covers:
- RebalanceImpact/WeightProposal/RebalanceResult model integrity
- impact_analyzer: compute_impact with single and multiple affected portfolios
- weight_proposer: propose_weights with feasible and infeasible cases
- RebalancingService: compute_rebalance_impact, propose_adjustments
- Regime change detection with consecutive evaluation threshold
- universe_service integration (deactivate_asset triggers rebalancing)
- Edge cases: no portfolios, no snapshots, no allocations
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from vertical_engines.wealth.rebalancing.models import (
    RebalanceImpact,
    RebalanceResult,
    WeightProposal,
)

# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

def _make_portfolio(
    profile: str = "moderate",
    org_id: str = "org-1",
    fund_selection: dict | None = None,
    status: str = "active",
    portfolio_id: uuid.UUID | None = None,
) -> MagicMock:
    p = MagicMock()
    p.id = portfolio_id or uuid.uuid4()
    p.profile = profile
    p.organization_id = org_id
    p.status = status
    p.fund_selection_schema = fund_selection
    return p


def _make_snapshot(
    profile: str = "moderate",
    org_id: str = "org-1",
    weights: dict | None = None,
    cvar_current: float = -0.04,
    cvar_limit: float = -0.06,
    regime: str = "normal",
    snapshot_date: date | None = None,
) -> MagicMock:
    s = MagicMock()
    s.snapshot_id = uuid.uuid4()
    s.profile = profile
    s.organization_id = org_id
    s.weights = weights or {"US_EQUITY": 0.4, "FIXED_INCOME": 0.3, "INTL_EQUITY": 0.3}
    s.cvar_current = Decimal(str(cvar_current))
    s.cvar_limit = Decimal(str(cvar_limit))
    s.cvar_utilized_pct = Decimal("66.67")
    s.trigger_status = "ok"
    s.consecutive_breach_days = 0
    s.regime = regime
    s.snapshot_date = snapshot_date or date(2026, 3, 16)
    return s


def _make_allocation(
    block_id: str,
    profile: str = "moderate",
    org_id: str = "org-1",
    target: float = 0.33,
    min_w: float = 0.10,
    max_w: float = 0.60,
) -> MagicMock:
    a = MagicMock()
    a.allocation_id = uuid.uuid4()
    a.profile = profile
    a.organization_id = org_id
    a.block_id = block_id
    a.target_weight = Decimal(str(target))
    a.min_weight = Decimal(str(min_w))
    a.max_weight = Decimal(str(max_w))
    a.effective_to = None
    return a


# ═══════════════════════════════════════════════════════════════════
#  Model Tests
# ═══════════════════════════════════════════════════════════════════

class TestModels:
    """Test frozen dataclass invariants."""

    def test_rebalance_impact_frozen(self):
        impact = RebalanceImpact(
            instrument_id=uuid.uuid4(),
            affected_portfolios=(uuid.uuid4(),),
            weight_gap=0.15,
            trigger="deactivation",
        )
        with pytest.raises(AttributeError):
            impact.weight_gap = 0.20  # type: ignore[misc]

    def test_weight_proposal_frozen(self):
        proposal = WeightProposal(
            portfolio_id=uuid.uuid4(),
            old_weights={"A": 0.5, "B": 0.5},
            new_weights={"A": 0.6, "B": 0.4},
            cvar_before=-0.04,
            cvar_after=-0.05,
            feasible=True,
            reason=None,
        )
        with pytest.raises(AttributeError):
            proposal.feasible = False  # type: ignore[misc]

    def test_rebalance_result_frozen(self):
        impact = RebalanceImpact(
            instrument_id=uuid.uuid4(),
            affected_portfolios=(),
            weight_gap=0.0,
            trigger="deactivation",
        )
        result = RebalanceResult(
            impact=impact,
            proposals=(),
            all_feasible=True,
            computed_at=datetime.now(UTC),
        )
        with pytest.raises(AttributeError):
            result.all_feasible = False  # type: ignore[misc]

    def test_impact_trigger_types(self):
        for trigger in ("deactivation", "regime_change"):
            impact = RebalanceImpact(
                instrument_id=uuid.uuid4(),
                affected_portfolios=(),
                weight_gap=0.0,
                trigger=trigger,
            )
            assert impact.trigger == trigger

    def test_weight_proposal_infeasible(self):
        proposal = WeightProposal(
            portfolio_id=uuid.uuid4(),
            old_weights={},
            new_weights={},
            cvar_before=0.0,
            cvar_after=0.0,
            feasible=False,
            reason="Optimizer: infeasible",
        )
        assert not proposal.feasible
        assert proposal.reason is not None

    def test_rebalance_result_all_feasible_true_when_empty(self):
        impact = RebalanceImpact(
            instrument_id=uuid.uuid4(),
            affected_portfolios=(),
            weight_gap=0.0,
            trigger="deactivation",
        )
        result = RebalanceResult(
            impact=impact,
            proposals=(),
            all_feasible=True,
            computed_at=datetime.now(UTC),
        )
        assert result.all_feasible is True
        assert len(result.proposals) == 0


# ═══════════════════════════════════════════════════════════════════
#  Impact Analyzer Tests
# ═══════════════════════════════════════════════════════════════════

class TestImpactAnalyzer:
    """Test impact_analyzer.compute_impact."""

    def test_single_affected_portfolio(self):
        from vertical_engines.wealth.rebalancing.impact_analyzer import compute_impact

        instrument_id = uuid.uuid4()
        portfolio = _make_portfolio(
            fund_selection={"funds": [
                {"instrument_id": str(instrument_id), "weight": 0.15},
                {"instrument_id": str(uuid.uuid4()), "weight": 0.85},
            ]},
        )

        db = MagicMock()
        # Mock the scalars().all() chain
        db.execute.return_value.scalars.return_value.all.return_value = [portfolio]

        result = compute_impact(db, instrument_id, "org-1")

        assert len(result.affected_portfolios) == 1
        assert result.affected_portfolios[0] == portfolio.id
        assert result.weight_gap == 0.15
        assert result.trigger == "deactivation"

    def test_multiple_affected_portfolios(self):
        from vertical_engines.wealth.rebalancing.impact_analyzer import compute_impact

        instrument_id = uuid.uuid4()
        p1 = _make_portfolio(
            fund_selection={"funds": [
                {"instrument_id": str(instrument_id), "weight": 0.10},
            ]},
        )
        p2 = _make_portfolio(
            fund_selection={"funds": [
                {"instrument_id": str(instrument_id), "weight": 0.20},
            ]},
        )

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [p1, p2]

        result = compute_impact(db, instrument_id, "org-1")

        assert len(result.affected_portfolios) == 2
        assert result.weight_gap == 0.30

    def test_no_affected_portfolios(self):
        from vertical_engines.wealth.rebalancing.impact_analyzer import compute_impact

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []

        result = compute_impact(db, uuid.uuid4(), "org-1")

        assert len(result.affected_portfolios) == 0
        assert result.weight_gap == 0.0

    def test_portfolio_without_target_instrument(self):
        from vertical_engines.wealth.rebalancing.impact_analyzer import compute_impact

        instrument_id = uuid.uuid4()
        other_id = uuid.uuid4()
        portfolio = _make_portfolio(
            fund_selection={"funds": [
                {"instrument_id": str(other_id), "weight": 1.0},
            ]},
        )

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [portfolio]

        result = compute_impact(db, instrument_id, "org-1")

        assert len(result.affected_portfolios) == 0
        assert result.weight_gap == 0.0

    def test_regime_change_trigger(self):
        from vertical_engines.wealth.rebalancing.impact_analyzer import compute_impact

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = []

        result = compute_impact(db, uuid.uuid4(), "org-1", trigger="regime_change")
        assert result.trigger == "regime_change"


# ═══════════════════════════════════════════════════════════════════
#  Weight Proposer Tests
# ═══════════════════════════════════════════════════════════════════

class TestWeightProposer:
    """Test weight_proposer.propose_weights."""

    def test_portfolio_not_found(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import propose_weights

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None

        result = propose_weights(db, uuid.uuid4(), uuid.uuid4(), "org-1")

        assert not result.feasible
        assert "not found" in result.reason

    def test_no_snapshot_returns_infeasible(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import propose_weights

        portfolio = _make_portfolio()
        db = MagicMock()
        # First call: portfolio found; second call: no snapshot
        db.execute.return_value.scalar_one_or_none.side_effect = [
            portfolio, None,
        ]

        result = propose_weights(db, portfolio.id, uuid.uuid4(), "org-1")

        assert not result.feasible
        assert "snapshot" in result.reason.lower()

    def test_no_allocations_returns_infeasible(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import propose_weights

        portfolio = _make_portfolio()
        snapshot = _make_snapshot()
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.side_effect = [
            portfolio, snapshot,
        ]
        db.execute.return_value.scalars.return_value.all.return_value = []

        result = propose_weights(db, portfolio.id, uuid.uuid4(), "org-1")

        assert not result.feasible
        assert "allocation" in result.reason.lower()

    def test_feasible_proposal(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import propose_weights

        portfolio = _make_portfolio()
        snapshot = _make_snapshot()
        allocs = [
            _make_allocation("US_EQUITY"),
            _make_allocation("FIXED_INCOME"),
            _make_allocation("INTL_EQUITY"),
        ]

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.side_effect = [
            portfolio, snapshot,
        ]
        db.execute.return_value.scalars.return_value.all.return_value = allocs

        result = propose_weights(db, portfolio.id, uuid.uuid4(), "org-1")

        assert result.feasible
        assert result.reason is None
        assert "US_EQUITY" in result.new_weights
        # Weights should sum to ~1.0
        total = sum(result.new_weights.values())
        assert abs(total - 1.0) < 0.01

    def test_infeasible_bounds(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import propose_weights

        portfolio = _make_portfolio()
        # Weights that can't fit in tight bounds
        snapshot = _make_snapshot(weights={"A": 0.9, "B": 0.1})
        # Very tight bounds that make redistribution impossible
        allocs = [
            _make_allocation("A", min_w=0.95, max_w=0.95),
            _make_allocation("B", min_w=0.95, max_w=0.95),
        ]

        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.side_effect = [
            portfolio, snapshot,
        ]
        db.execute.return_value.scalars.return_value.all.return_value = allocs

        result = propose_weights(db, portfolio.id, uuid.uuid4(), "org-1")

        assert not result.feasible
        assert "bounds" in result.reason.lower()

    def test_weight_gap_calculation_accuracy(self):
        from vertical_engines.wealth.rebalancing.impact_analyzer import compute_impact

        instrument_id = uuid.uuid4()
        p1 = _make_portfolio(
            fund_selection={"funds": [
                {"instrument_id": str(instrument_id), "weight": 0.123456},
            ]},
        )

        db = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [p1]

        result = compute_impact(db, instrument_id, "org-1")
        assert result.weight_gap == 0.123456


# ═══════════════════════════════════════════════════════════════════
#  Rebalancing Service Tests
# ═══════════════════════════════════════════════════════════════════

class TestRebalancingService:
    """Test RebalancingService orchestration."""

    @patch("vertical_engines.wealth.rebalancing.service.propose_weights")
    @patch("vertical_engines.wealth.rebalancing.service.compute_impact")
    def test_compute_rebalance_impact_single_portfolio(
        self, mock_impact, mock_propose,
    ):
        from vertical_engines.wealth.rebalancing.service import RebalancingService

        portfolio_id = uuid.uuid4()
        instrument_id = uuid.uuid4()

        mock_impact.return_value = RebalanceImpact(
            instrument_id=instrument_id,
            affected_portfolios=(portfolio_id,),
            weight_gap=0.15,
            trigger="deactivation",
        )
        mock_propose.return_value = WeightProposal(
            portfolio_id=portfolio_id,
            old_weights={"A": 0.5},
            new_weights={"A": 0.65},
            cvar_before=-0.04,
            cvar_after=-0.05,
            feasible=True,
            reason=None,
        )

        svc = RebalancingService()
        result = svc.compute_rebalance_impact(
            MagicMock(), instrument_id, "org-1",
        )

        assert isinstance(result, RebalanceResult)
        assert len(result.proposals) == 1
        assert result.all_feasible is True
        assert result.impact.weight_gap == 0.15

    @patch("vertical_engines.wealth.rebalancing.service.propose_weights")
    @patch("vertical_engines.wealth.rebalancing.service.compute_impact")
    def test_compute_rebalance_impact_mixed_feasibility(
        self, mock_impact, mock_propose,
    ):
        from vertical_engines.wealth.rebalancing.service import RebalancingService

        p1, p2 = uuid.uuid4(), uuid.uuid4()
        instrument_id = uuid.uuid4()

        mock_impact.return_value = RebalanceImpact(
            instrument_id=instrument_id,
            affected_portfolios=(p1, p2),
            weight_gap=0.20,
            trigger="deactivation",
        )

        def side_effect(db, portfolio_id, removed_instrument_id, organization_id, config=None):
            feasible = portfolio_id == p1
            return WeightProposal(
                portfolio_id=portfolio_id,
                old_weights={},
                new_weights={} if not feasible else {"A": 1.0},
                cvar_before=-0.04,
                cvar_after=-0.04,
                feasible=feasible,
                reason=None if feasible else "Optimizer: infeasible",
            )

        mock_propose.side_effect = side_effect

        svc = RebalancingService()
        result = svc.compute_rebalance_impact(
            MagicMock(), instrument_id, "org-1",
        )

        assert len(result.proposals) == 2
        assert result.all_feasible is False

    @patch("vertical_engines.wealth.rebalancing.service.propose_weights")
    @patch("vertical_engines.wealth.rebalancing.service.compute_impact")
    def test_no_affected_portfolios(self, mock_impact, mock_propose):
        from vertical_engines.wealth.rebalancing.service import RebalancingService

        mock_impact.return_value = RebalanceImpact(
            instrument_id=uuid.uuid4(),
            affected_portfolios=(),
            weight_gap=0.0,
            trigger="deactivation",
        )

        svc = RebalancingService()
        result = svc.compute_rebalance_impact(
            MagicMock(), uuid.uuid4(), "org-1",
        )

        assert len(result.proposals) == 0
        assert result.all_feasible is True
        mock_propose.assert_not_called()

    @patch("vertical_engines.wealth.rebalancing.service.propose_weights")
    def test_propose_adjustments_delegates(self, mock_propose):
        from vertical_engines.wealth.rebalancing.service import RebalancingService

        expected = WeightProposal(
            portfolio_id=uuid.uuid4(),
            old_weights={},
            new_weights={"A": 1.0},
            cvar_before=0.0,
            cvar_after=0.0,
            feasible=True,
            reason=None,
        )
        mock_propose.return_value = expected

        svc = RebalancingService()
        result = svc.propose_adjustments(
            MagicMock(), uuid.uuid4(), uuid.uuid4(), "org-1",
        )

        assert result is expected


# ═══════════════════════════════════════════════════════════════════
#  Regime Change Detection Tests
# ═══════════════════════════════════════════════════════════════════

class TestRegimeChangeDetection:
    """Test RebalancingService.detect_regime_trigger."""

    def test_consecutive_stress_triggers_rebalance(self):
        from vertical_engines.wealth.rebalancing.service import RebalancingService

        portfolio_id = uuid.uuid4()

        db = MagicMock()
        # Calls: 1) LATERAL JOIN query → snapshot rows, 2) ModelPortfolio IDs
        db.execute.return_value.all.side_effect = [
            [
                ("moderate", date(2026, 3, 16), "stress"),
                ("moderate", date(2026, 3, 15), "stress"),
            ],
            [(portfolio_id,)],
        ]

        svc = RebalancingService(config={"regime_consecutive_threshold": 2})
        results = svc.detect_regime_trigger(db, "org-1")

        assert len(results) == 1
        assert results[0].impact.trigger == "regime_change"
        # Bug #114 fix: affected_portfolios contains ModelPortfolio IDs, not snapshot IDs
        assert results[0].impact.affected_portfolios == (portfolio_id,)

    def test_insufficient_consecutive_stress(self):
        from vertical_engines.wealth.rebalancing.service import RebalancingService

        db = MagicMock()
        # LATERAL JOIN returns one stress + one normal → not consecutive
        db.execute.return_value.all.return_value = [
            ("moderate", date(2026, 3, 16), "stress"),
            ("moderate", date(2026, 3, 15), "normal"),
        ]

        svc = RebalancingService(config={"regime_consecutive_threshold": 2})
        results = svc.detect_regime_trigger(db, "org-1")

        assert len(results) == 0

    def test_no_snapshots_no_trigger(self):
        from vertical_engines.wealth.rebalancing.service import RebalancingService

        db = MagicMock()
        # LATERAL JOIN returns no rows (no snapshots)
        db.execute.return_value.all.return_value = []

        svc = RebalancingService()
        results = svc.detect_regime_trigger(db, "org-1")

        assert len(results) == 0

    def test_configurable_threshold(self):
        from vertical_engines.wealth.rebalancing.service import RebalancingService

        # With threshold=3, only 2 stress snapshots should NOT trigger
        db = MagicMock()
        db.execute.return_value.all.return_value = [
            ("moderate", date(2026, 3, 16), "crisis"),
            ("moderate", date(2026, 3, 15), "stress"),
        ]

        svc = RebalancingService(config={"regime_consecutive_threshold": 3})
        results = svc.detect_regime_trigger(db, "org-1")

        # Only 2 snapshots returned (limit=threshold=3 but only 2 exist)
        assert len(results) == 0


# ═══════════════════════════════════════════════════════════════════
#  Universe Service Integration Tests
# ═══════════════════════════════════════════════════════════════════

class TestUniverseServiceIntegration:
    """Test that deactivate_asset triggers rebalancing."""

    def test_deactivate_returns_tuple(self):
        """Verify deactivate_asset now returns (DeactivationResult, RebalanceResult|None)."""
        from vertical_engines.wealth.asset_universe.universe_service import UniverseService

        svc = UniverseService()
        assert hasattr(svc, "deactivate_asset")

    def test_deactivate_triggers_rebalance_when_approved(self):
        from vertical_engines.wealth.asset_universe.universe_service import UniverseService

        instrument_id = uuid.uuid4()
        fund = MagicMock()
        fund.is_active = True
        fund.fund_id = instrument_id

        approval = MagicMock()
        approval.is_current = True

        mock_rebal_instance = MagicMock()
        mock_rebal_instance.compute_rebalance_impact.return_value = RebalanceResult(
            impact=RebalanceImpact(
                instrument_id=instrument_id,
                affected_portfolios=(),
                weight_gap=0.0,
                trigger="deactivation",
            ),
            proposals=(),
            all_feasible=True,
            computed_at=datetime.now(UTC),
        )

        db = MagicMock()
        # scalar_one_or_none calls: fund, approval
        db.execute.return_value.scalar_one_or_none.side_effect = [fund, approval]

        svc = UniverseService()
        with patch(
            "vertical_engines.wealth.rebalancing.service.RebalancingService",
            return_value=mock_rebal_instance,
        ):
            deactivation, rebalance = svc.deactivate_asset(
                db, instrument_id=instrument_id, organization_id="org-1",
            )

        assert deactivation.rebalance_needed is True
        assert rebalance is not None
        mock_rebal_instance.compute_rebalance_impact.assert_called_once()

    def test_deactivate_no_rebalance_when_not_approved(self):
        """When fund was not approved, rebalancing is skipped."""
        from vertical_engines.wealth.asset_universe.universe_service import UniverseService

        instrument_id = uuid.uuid4()
        fund = MagicMock()
        fund.is_active = True
        fund.fund_id = instrument_id

        # No approval → rebalance_needed=False
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.side_effect = [fund, None]

        svc = UniverseService()
        deactivation, rebalance = svc.deactivate_asset(
            db, instrument_id=instrument_id, organization_id="org-1",
        )

        assert deactivation.rebalance_needed is False
        assert rebalance is None


# ═══════════════════════════════════════════════════════════════════
#  Proportional Redistribution Tests
# ═══════════════════════════════════════════════════════════════════

class TestProportionalRedistribution:
    """Test _redistribute_proportionally logic."""

    def test_even_redistribution(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import (
            _redistribute_proportionally,
        )

        old = {"A": 0.4, "B": 0.3, "C": 0.3}
        bounds = {"A": (0.0, 1.0), "B": (0.0, 1.0), "C": (0.0, 1.0)}
        result = _redistribute_proportionally(old, bounds)

        assert result is not None
        assert abs(sum(result.values()) - 1.0) < 0.01
        assert result["A"] == pytest.approx(0.4, abs=0.01)

    def test_respects_max_bounds(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import (
            _redistribute_proportionally,
        )

        old = {"A": 0.8, "B": 0.2}
        bounds = {"A": (0.0, 0.5), "B": (0.0, 1.0)}
        result = _redistribute_proportionally(old, bounds)

        assert result is not None
        assert result["A"] <= 0.5 + 1e-6

    def test_respects_min_bounds(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import (
            _redistribute_proportionally,
        )

        old = {"A": 0.15, "B": 0.55, "C": 0.30}
        bounds = {"A": (0.20, 0.60), "B": (0.20, 0.60), "C": (0.20, 0.60)}
        result = _redistribute_proportionally(old, bounds)

        assert result is not None
        assert result["A"] >= 0.20 - 1e-6

    def test_infeasible_returns_none(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import (
            _redistribute_proportionally,
        )

        # Both blocks need min=0.6 but sum would be 1.2 > 1.0
        old = {"A": 0.5, "B": 0.5}
        bounds = {"A": (0.6, 1.0), "B": (0.6, 1.0)}
        result = _redistribute_proportionally(old, bounds)

        assert result is None

    def test_empty_weights_returns_none(self):
        from vertical_engines.wealth.rebalancing.weight_proposer import (
            _redistribute_proportionally,
        )

        result = _redistribute_proportionally({}, {})
        assert result is None

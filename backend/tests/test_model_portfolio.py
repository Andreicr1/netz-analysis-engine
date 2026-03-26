"""Tests for Model Portfolio, QuantAnalyzer rewiring, and Attribution service."""

from __future__ import annotations

import uuid

import numpy as np
import pytest

from vertical_engines.wealth.model_portfolio.models import (
    BacktestResult,
    FundWeight,
    LiveNAV,
    OptimizationMeta,
    PortfolioComposition,
    StressResult,
)
from vertical_engines.wealth.model_portfolio.portfolio_builder import (
    construct,
    construct_from_optimizer,
)
from vertical_engines.wealth.model_portfolio.stress_scenarios import SCENARIOS


class TestPortfolioBuilder:
    """Test portfolio construction algorithm (fallback path)."""

    def test_construct_with_single_block(self):
        funds = [
            {"instrument_id": str(uuid.uuid4()), "fund_name": "Fund A", "block_id": "equity", "manager_score": 80},
            {"instrument_id": str(uuid.uuid4()), "fund_name": "Fund B", "block_id": "equity", "manager_score": 60},
            {"instrument_id": str(uuid.uuid4()), "fund_name": "Fund C", "block_id": "equity", "manager_score": 40},
        ]
        allocation = {"equity": 1.0}
        result = construct("moderate", funds, allocation)

        assert result.validate_weights()
        assert len(result.funds) == 3
        assert abs(result.total_weight - 1.0) < 1e-6

    def test_construct_with_multiple_blocks(self):
        funds = [
            {"instrument_id": str(uuid.uuid4()), "fund_name": "Eq A", "block_id": "equity", "manager_score": 90},
            {"instrument_id": str(uuid.uuid4()), "fund_name": "Eq B", "block_id": "equity", "manager_score": 70},
            {"instrument_id": str(uuid.uuid4()), "fund_name": "FI A", "block_id": "fixed_income", "manager_score": 85},
        ]
        allocation = {"equity": 0.6, "fixed_income": 0.4}
        result = construct("conservative", funds, allocation)

        assert result.validate_weights()
        # Check equity funds get ~60% total
        equity_weight = sum(f.weight for f in result.funds if f.block_id == "equity")
        assert abs(equity_weight - 0.6) < 0.01

    def test_construct_score_proportional(self):
        """Higher scored funds get more weight within block."""
        fid_high = str(uuid.uuid4())
        fid_low = str(uuid.uuid4())
        funds = [
            {"instrument_id": fid_high, "fund_name": "High", "block_id": "eq", "manager_score": 90},
            {"instrument_id": fid_low, "fund_name": "Low", "block_id": "eq", "manager_score": 30},
        ]
        allocation = {"eq": 1.0}
        result = construct("growth", funds, allocation)

        high_w = next(f.weight for f in result.funds if str(f.instrument_id) == fid_high)
        low_w = next(f.weight for f in result.funds if str(f.instrument_id) == fid_low)
        assert high_w > low_w

    def test_construct_respects_top_n(self):
        funds = [
            {"instrument_id": str(uuid.uuid4()), "fund_name": f"Fund {i}", "block_id": "eq", "manager_score": 100 - i * 10}
            for i in range(10)
        ]
        allocation = {"eq": 1.0}
        result = construct("moderate", funds, allocation, config={"top_n_per_block": 2})

        assert len(result.funds) == 2
        assert result.validate_weights()

    def test_construct_empty_universe(self):
        result = construct("moderate", [], {"equity": 1.0})
        assert len(result.funds) == 0
        assert result.total_weight == 0.0

    def test_construct_empty_allocation(self):
        funds = [
            {"instrument_id": str(uuid.uuid4()), "fund_name": "A", "block_id": "eq", "manager_score": 80},
        ]
        result = construct("moderate", funds, {})
        assert len(result.funds) == 0


class TestConstructFromOptimizer:
    """Test optimizer-driven portfolio construction (primary path)."""

    def test_construct_from_optimizer_weights_sum_to_one(self):
        fid1 = str(uuid.uuid4())
        fid2 = str(uuid.uuid4())
        fid3 = str(uuid.uuid4())

        fund_weights = {fid1: 0.5, fid2: 0.3, fid3: 0.2}
        fund_info = {
            fid1: {"fund_name": "Fund A", "block_id": "equity", "manager_score": 80},
            fid2: {"fund_name": "Fund B", "block_id": "equity", "manager_score": 60},
            fid3: {"fund_name": "Fund C", "block_id": "fi", "manager_score": 70},
        }
        meta = OptimizationMeta(
            expected_return=0.08, portfolio_volatility=0.12,
            sharpe_ratio=0.67, solver="CLARABEL", status="optimal",
            cvar_95=-0.05, cvar_limit=-0.08, cvar_within_limit=True,
        )

        result = construct_from_optimizer("moderate", fund_weights, fund_info, meta)

        assert result.validate_weights()
        assert len(result.funds) == 3
        assert result.optimization is not None
        assert result.optimization.cvar_95 == -0.05
        assert result.optimization.cvar_within_limit is True

    def test_construct_from_optimizer_skips_near_zero(self):
        fid1 = str(uuid.uuid4())
        fid2 = str(uuid.uuid4())

        fund_weights = {fid1: 0.9999, fid2: 0.0000001}  # near-zero
        fund_info = {
            fid1: {"fund_name": "Fund A", "block_id": "eq", "manager_score": 80},
            fid2: {"fund_name": "Fund B", "block_id": "eq", "manager_score": 60},
        }
        meta = OptimizationMeta(
            expected_return=0.1, portfolio_volatility=0.15,
            sharpe_ratio=0.7, solver="CLARABEL", status="optimal",
        )

        result = construct_from_optimizer("growth", fund_weights, fund_info, meta)
        assert len(result.funds) == 1

    def test_construct_from_optimizer_preserves_block_id(self):
        fid1 = str(uuid.uuid4())
        fid2 = str(uuid.uuid4())

        fund_weights = {fid1: 0.6, fid2: 0.4}
        fund_info = {
            fid1: {"fund_name": "Eq Fund", "block_id": "na_equity_large", "manager_score": 90},
            fid2: {"fund_name": "FI Fund", "block_id": "fi_us_aggregate", "manager_score": 75},
        }
        meta = OptimizationMeta(
            expected_return=0.07, portfolio_volatility=0.10,
            sharpe_ratio=0.6, solver="CLARABEL", status="optimal",
        )

        result = construct_from_optimizer("conservative", fund_weights, fund_info, meta)
        blocks = {f.block_id for f in result.funds}
        assert "na_equity_large" in blocks
        assert "fi_us_aggregate" in blocks


class TestFundLevelOptimizer:
    """Test fund-level CLARABEL optimizer with block-group constraints."""

    @pytest.mark.asyncio
    async def test_optimize_fund_portfolio_respects_block_bounds(self):
        from quant_engine.optimizer_service import (
            BlockConstraint,
            ProfileConstraints,
            optimize_fund_portfolio,
        )

        # 4 funds across 2 blocks
        fids = [str(uuid.uuid4()) for _ in range(4)]
        fund_blocks = {
            fids[0]: "equity", fids[1]: "equity",
            fids[2]: "fi", fids[3]: "fi",
        }

        np.random.seed(42)
        cov = np.eye(4) * 0.04
        cov[0, 1] = cov[1, 0] = 0.01
        cov[2, 3] = cov[3, 2] = 0.005
        expected = {fids[0]: 0.10, fids[1]: 0.08, fids[2]: 0.04, fids[3]: 0.03}

        constraints = ProfileConstraints(
            blocks=[
                BlockConstraint("equity", 0.40, 0.70),
                BlockConstraint("fi", 0.30, 0.60),
            ],
            cvar_limit=None,  # not testing CVaR here
            max_single_fund_weight=0.50,
        )

        result = await optimize_fund_portfolio(
            fund_ids=fids,
            fund_blocks=fund_blocks,
            expected_returns=expected,
            cov_matrix=cov,
            constraints=constraints,
        )

        assert result.status == "optimal"
        assert abs(sum(result.weights.values()) - 1.0) < 1e-4

        # Verify block bounds
        eq_sum = sum(result.weights[f] for f in fids[:2])
        fi_sum = sum(result.weights[f] for f in fids[2:])
        assert eq_sum >= 0.40 - 1e-4, f"equity sum {eq_sum} < 0.40"
        assert eq_sum <= 0.70 + 1e-4, f"equity sum {eq_sum} > 0.70"
        assert fi_sum >= 0.30 - 1e-4, f"fi sum {fi_sum} < 0.30"
        assert fi_sum <= 0.60 + 1e-4, f"fi sum {fi_sum} > 0.60"

    @pytest.mark.asyncio
    async def test_optimize_fund_portfolio_cvar_computed(self):
        from quant_engine.optimizer_service import (
            BlockConstraint,
            ProfileConstraints,
            optimize_fund_portfolio,
        )

        fids = [str(uuid.uuid4()) for _ in range(3)]
        fund_blocks = {fids[0]: "eq", fids[1]: "fi", fids[2]: "fi"}

        # Very low-volatility assets → CVaR should be within generous limit
        cov = np.diag([0.001, 0.0005, 0.0004])
        expected = {fids[0]: 0.06, fids[1]: 0.03, fids[2]: 0.025}

        constraints = ProfileConstraints(
            blocks=[
                BlockConstraint("eq", 0.2, 0.5),
                BlockConstraint("fi", 0.5, 0.8),
            ],
            cvar_limit=-0.15,  # generous limit
            max_single_fund_weight=0.60,
        )

        result = await optimize_fund_portfolio(
            fund_ids=fids,
            fund_blocks=fund_blocks,
            expected_returns=expected,
            cov_matrix=cov,
            constraints=constraints,
        )

        assert result.status == "optimal"
        assert result.cvar_95 is not None
        assert result.cvar_95 < 0  # CVaR is negative (loss convention)
        assert result.cvar_limit == -0.15
        assert result.cvar_within_limit is True
        assert result.cvar_95 >= result.cvar_limit  # e.g. -0.03 >= -0.15

    @pytest.mark.asyncio
    async def test_optimize_fund_portfolio_empty(self):
        from quant_engine.optimizer_service import (
            ProfileConstraints,
            optimize_fund_portfolio,
        )

        result = await optimize_fund_portfolio(
            fund_ids=[], fund_blocks={},
            expected_returns={}, cov_matrix=np.array([]),
            constraints=ProfileConstraints(blocks=[]),
        )
        assert result.status == "empty"

    @pytest.mark.asyncio
    async def test_optimize_fund_portfolio_cvar_enforcement_cascade(self):
        """When CVaR violates limit, optimizer re-solves with variance ceiling."""
        from quant_engine.optimizer_service import (
            BlockConstraint,
            ProfileConstraints,
            optimize_fund_portfolio,
        )

        fids = [str(uuid.uuid4()) for _ in range(4)]
        fund_blocks = {
            fids[0]: "equity", fids[1]: "equity",
            fids[2]: "fi", fids[3]: "fi",
        }

        # High-volatility equity + low-vol FI — unconstrained optimizer
        # will load equity, violating a tight CVaR limit
        cov = np.diag([0.09, 0.08, 0.01, 0.008])  # equity vol ~30%, FI ~10%
        expected = {fids[0]: 0.15, fids[1]: 0.12, fids[2]: 0.04, fids[3]: 0.03}

        # Tight CVaR limit that should force more FI allocation
        constraints = ProfileConstraints(
            blocks=[
                BlockConstraint("equity", 0.10, 0.60),
                BlockConstraint("fi", 0.40, 0.90),
            ],
            cvar_limit=-0.06,  # tight limit
            max_single_fund_weight=0.50,
        )

        result = await optimize_fund_portfolio(
            fund_ids=fids,
            fund_blocks=fund_blocks,
            expected_returns=expected,
            cov_matrix=cov,
            constraints=constraints,
        )

        # Should have re-optimized (Phase 2 or 3)
        assert result.status in (
            "optimal:cvar_constrained",
            "optimal:min_variance_fallback",
            "optimal:cvar_violated",  # worst case if all phases exhausted
        )
        assert result.cvar_95 is not None
        # The re-optimized solution should have lower volatility than unconstrained
        assert result.portfolio_volatility > 0

        # FI allocation should be higher than in unconstrained (equity-heavy) solution
        fi_weight = sum(
            result.weights.get(fids[i], 0) for i in [2, 3]
        )
        assert fi_weight >= 0.40, f"FI weight {fi_weight} below 0.40 minimum"

    @pytest.mark.asyncio
    async def test_optimize_fund_portfolio_concentration_limit(self):
        """No single fund should exceed max_single_fund_weight."""
        from quant_engine.optimizer_service import (
            BlockConstraint,
            ProfileConstraints,
            optimize_fund_portfolio,
        )

        fids = [str(uuid.uuid4()) for _ in range(3)]
        fund_blocks = {fids[0]: "eq", fids[1]: "eq", fids[2]: "eq"}

        # One fund has much higher return — optimizer would concentrate without limit
        cov = np.eye(3) * 0.04
        expected = {fids[0]: 0.20, fids[1]: 0.02, fids[2]: 0.01}

        constraints = ProfileConstraints(
            blocks=[BlockConstraint("eq", 0.9, 1.0)],
            cvar_limit=None,  # not testing CVaR here
            max_single_fund_weight=0.40,
        )

        result = await optimize_fund_portfolio(
            fund_ids=fids,
            fund_blocks=fund_blocks,
            expected_returns=expected,
            cov_matrix=cov,
            constraints=constraints,
        )

        assert result.status == "optimal"
        for fid, w in result.weights.items():
            assert w <= 0.40 + 1e-4, f"Fund {fid} weight {w} exceeds 0.40 limit"


class TestPortfolioModels:
    """Test frozen dataclasses."""

    def test_fund_weight_frozen(self):
        fw = FundWeight(instrument_id=uuid.uuid4(), fund_name="X", block_id="eq", weight=0.5, score=80.0)
        with pytest.raises(AttributeError):
            fw.weight = 0.3  # type: ignore[misc]

    def test_composition_validate_weights(self):
        comp = PortfolioComposition(profile="test", funds=[], total_weight=1.0)
        assert comp.validate_weights()

        comp2 = PortfolioComposition(profile="test", funds=[], total_weight=0.5)
        assert not comp2.validate_weights()

    def test_optimization_meta_cvar_fields(self):
        meta = OptimizationMeta(
            expected_return=0.08, portfolio_volatility=0.12,
            sharpe_ratio=0.67, solver="CLARABEL", status="optimal",
            cvar_95=-0.05, cvar_limit=-0.08, cvar_within_limit=True,
        )
        assert meta.cvar_95 == -0.05
        assert meta.cvar_limit == -0.08
        assert meta.cvar_within_limit is True

    def test_optimization_meta_defaults(self):
        meta = OptimizationMeta(
            expected_return=0.0, portfolio_volatility=0.0,
            sharpe_ratio=0.0, solver="test", status="test",
        )
        assert meta.cvar_95 is None
        assert meta.cvar_limit is None
        assert meta.cvar_within_limit is True

    def test_backtest_result_frozen(self):
        bt = BacktestResult(portfolio_id=None, lookback_days=1260)
        with pytest.raises(AttributeError):
            bt.lookback_days = 500  # type: ignore[misc]

    def test_live_nav_frozen(self):
        nav = LiveNAV(portfolio_id=uuid.uuid4(), as_of=None, nav=1000.0)
        with pytest.raises(AttributeError):
            nav.nav = 2000.0  # type: ignore[misc]

    def test_stress_result_frozen(self):
        sr = StressResult(portfolio_id=None, scenarios=[])
        with pytest.raises(AttributeError):
            sr.scenarios = []  # type: ignore[misc]


class TestStressScenarios:
    """Test stress scenario definitions."""

    def test_three_scenarios_defined(self):
        assert len(SCENARIOS) == 3

    def test_gfc_scenario(self):
        gfc = next(s for s in SCENARIOS if s.name == "2008_gfc")
        assert gfc.start_date.year == 2007
        assert gfc.end_date.year == 2009

    def test_covid_scenario(self):
        covid = next(s for s in SCENARIOS if s.name == "2020_covid")
        assert covid.start_date.year == 2020

    def test_rate_hike_scenario(self):
        rate = next(s for s in SCENARIOS if s.name == "2022_rate_hike")
        assert rate.start_date.year == 2022
        assert rate.end_date.year == 2022

    def test_scenarios_frozen(self):
        with pytest.raises(AttributeError):
            SCENARIOS[0].name = "changed"  # type: ignore[misc]


class TestAttributionService:
    """Test Brinson-Fachler attribution."""

    def test_single_period_effects_sum_to_excess(self):
        from quant_engine.attribution_service import compute_attribution

        w_p = np.array([0.6, 0.4])
        w_b = np.array([0.5, 0.5])
        r_p = np.array([0.10, 0.05])
        r_b = np.array([0.08, 0.04])

        result = compute_attribution(w_p, w_b, r_p, r_b, ["equity", "bonds"])

        # Effects should sum to excess return within tolerance
        effects_sum = result.allocation_total + result.selection_total + result.interaction_total
        assert abs(effects_sum - result.total_excess_return) < 1e-4
        assert result.benchmark_available is True

    def test_no_benchmark_returns_empty(self):
        from quant_engine.attribution_service import compute_attribution

        w_p = np.array([0.6, 0.4])
        r_p = np.array([0.10, 0.05])

        result = compute_attribution(w_p, None, r_p, None)
        assert result.benchmark_available is False
        assert len(result.sectors) == 0

    def test_identical_weights_zero_allocation(self):
        from quant_engine.attribution_service import compute_attribution

        w = np.array([0.5, 0.5])
        r_p = np.array([0.10, 0.05])
        r_b = np.array([0.08, 0.04])

        result = compute_attribution(w, w, r_p, r_b)

        # With identical weights, allocation and interaction should be zero
        assert abs(result.allocation_total) < 1e-6
        assert abs(result.interaction_total) < 1e-6

    def test_pure_function_no_io(self):
        from quant_engine.attribution_service import compute_attribution

        # Should work with pure numpy arrays, no DB needed
        result = compute_attribution(
            np.array([1.0]),
            np.array([1.0]),
            np.array([0.05]),
            np.array([0.03]),
            ["single"],
        )
        assert result.n_periods == 1

    def test_multi_period_carino_linking(self):
        from quant_engine.attribution_service import (
            compute_attribution,
            compute_multi_period_attribution,
        )

        # Two periods with simple data
        w_p = np.array([0.6, 0.4])
        w_b = np.array([0.5, 0.5])

        r_p1 = np.array([0.05, 0.02])
        r_b1 = np.array([0.04, 0.01])
        r_p2 = np.array([0.03, 0.04])
        r_b2 = np.array([0.02, 0.03])

        p1 = compute_attribution(w_p, w_b, r_p1, r_b1, ["eq", "fi"])
        p2 = compute_attribution(w_p, w_b, r_p2, r_b2, ["eq", "fi"])

        R_p1 = float(np.sum(w_p * r_p1))
        R_b1 = float(np.sum(w_b * r_b1))
        R_p2 = float(np.sum(w_p * r_p2))
        R_b2 = float(np.sum(w_b * r_b2))

        linked = compute_multi_period_attribution(
            [p1, p2], [R_p1, R_p2], [R_b1, R_b2]
        )

        assert linked.n_periods == 2
        assert linked.benchmark_available is True
        # Linked effects should approximately sum to total excess
        effects_sum = linked.allocation_total + linked.selection_total + linked.interaction_total
        assert abs(effects_sum - linked.total_excess_return) < 1e-3


class TestPortfolioMetricsService:
    """Test portfolio metrics aggregation."""

    def test_aggregate_returns(self):
        from quant_engine.portfolio_metrics_service import aggregate

        np.random.seed(42)
        returns = np.random.normal(0.0004, 0.01, 252)  # ~10% annual, 16% vol

        result = aggregate(returns)
        assert result.n_observations == 252
        assert result.sharpe_ratio is not None
        assert result.sortino_ratio is not None
        assert result.max_drawdown is not None
        assert result.max_drawdown <= 0

    def test_aggregate_empty_returns(self):
        from quant_engine.portfolio_metrics_service import aggregate

        result = aggregate(np.array([]))
        assert result.n_observations == 0
        assert result.sharpe_ratio is None

    def test_aggregate_with_benchmark(self):
        from quant_engine.portfolio_metrics_service import aggregate

        np.random.seed(42)
        returns = np.random.normal(0.0004, 0.01, 100)
        benchmark = np.random.normal(0.0003, 0.009, 100)

        result = aggregate(returns, benchmark)
        assert result.information_ratio is not None


class TestQuantAnalyzerRewired:
    """Test QuantAnalyzer is no longer a scaffold."""

    def test_quant_analyzer_not_scaffold(self):
        from vertical_engines.wealth.quant_analyzer import QuantAnalyzer

        qa = QuantAnalyzer()
        assert hasattr(qa, "analyze_portfolio")
        assert hasattr(qa, "_compute_cvar")
        assert hasattr(qa, "_compute_scoring")
        assert hasattr(qa, "_compute_peer_comparison")

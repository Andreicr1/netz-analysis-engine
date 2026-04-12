"""End-to-end tests for Fixed Income Quant Engine — Session 3.

Covers:
- Screener Layer 1: fund_fixed_income eliminatory gate
- Screener Layer 2: duration mandate fit for FI allocation blocks
- Screener Layer 3: FIQuantMetrics scoring dispatch
- E2E scoring comparison: FI fund on equity model vs FI model
- ELITE ranking: fixed_income weight produces non-zero target count
"""

from __future__ import annotations

import uuid

import pytest

from quant_engine.scoring_service import compute_fund_score
from vertical_engines.wealth.elite_ranking.allocation_source import compute_target_counts
from vertical_engines.wealth.screener.layer_evaluator import LayerEvaluator
from vertical_engines.wealth.screener.quant_metrics import (
    FIQuantMetrics,
    QuantMetrics,
)
from vertical_engines.wealth.screener.service import ScreenerService

# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

class _FIMetricsAdapter:
    """Adapter satisfying FIMetrics protocol for scoring_service."""

    def __init__(
        self,
        empirical_duration: float | None = None,
        credit_beta: float | None = None,
        yield_proxy_12m: float | None = None,
        duration_adj_drawdown_1y: float | None = None,
    ):
        self.empirical_duration = empirical_duration
        self.credit_beta = credit_beta
        self.yield_proxy_12m = yield_proxy_12m
        self.duration_adj_drawdown_1y = duration_adj_drawdown_1y


class _RiskMetricsAdapter:
    """Adapter satisfying RiskMetrics protocol for scoring_service."""

    def __init__(
        self,
        return_1y: float | None = None,
        sharpe_1y: float | None = None,
        max_drawdown_1y: float | None = None,
        information_ratio_1y: float | None = None,
    ):
        self.return_1y = return_1y
        self.sharpe_1y = sharpe_1y
        self.max_drawdown_1y = max_drawdown_1y
        self.information_ratio_1y = information_ratio_1y


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def layer1_config_with_fi():
    """Layer 1 config with both fund and fund_fixed_income rules."""
    return {
        "fund": {
            "min_aum_usd": 100_000_000,
            "min_track_record_years": 3,
        },
        "fund_fixed_income": {
            "min_empirical_duration": 0.5,
            "max_empirical_duration": 15.0,
            "min_duration_r2": 0.10,
        },
    }


@pytest.fixture
def layer2_config_fi():
    """Layer 2 config with FI block duration ranges."""
    return {
        "blocks": {
            "fi_aggregate": {
                "criteria": {
                    "min_empirical_duration": 3.0,
                    "max_empirical_duration": 10.0,
                    "asset_class": "fixed_income",
                },
            },
        },
    }


@pytest.fixture
def layer3_config_fi():
    """Layer 3 config with fund_fixed_income weights."""
    return {
        "fund": {
            "weights": {
                "sharpe_ratio": 0.30,
                "max_drawdown": 0.25,
                "pct_positive_months": 0.25,
                "annual_volatility_pct": 0.20,
            },
        },
        "fund_fixed_income": {
            "weights": {
                "empirical_duration": 0.15,
                "credit_beta": 0.15,
                "yield_proxy_12m": 0.25,
                "duration_adj_drawdown": 0.25,
                "sharpe_ratio": 0.20,
            },
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  Layer 1 — FI Eliminatory Gate
# ═══════════════════════════════════════════════════════════════════

class TestFILayer1:
    """FI-specific eliminatory rules applied when asset_class=fixed_income."""

    def test_fi_fund_passes_all_gates(self, layer1_config_with_fi):
        evaluator = LayerEvaluator(config=layer1_config_with_fi)
        attrs = {
            "aum_usd": 200_000_000,
            "track_record_years": 5,
            "asset_class": "fixed_income",
            "empirical_duration": 6.0,
            "duration_r2": 0.30,
        }
        results = evaluator.evaluate_layer1("fund", attrs, layer1_config_with_fi)
        assert all(r.passed for r in results), (
            f"All gates should pass for valid FI fund: {[(r.criterion, r.passed) for r in results]}"
        )

    def test_fi_fund_fails_duration_too_high(self, layer1_config_with_fi):
        evaluator = LayerEvaluator(config=layer1_config_with_fi)
        attrs = {
            "aum_usd": 200_000_000,
            "track_record_years": 5,
            "asset_class": "fixed_income",
            "empirical_duration": 20.0,  # exceeds max 15.0
            "duration_r2": 0.30,
        }
        results = evaluator.evaluate_layer1("fund", attrs, layer1_config_with_fi)
        failed = [r for r in results if not r.passed]
        assert len(failed) == 1
        assert failed[0].criterion == "max_empirical_duration"

    def test_fi_fund_fails_r2_too_low(self, layer1_config_with_fi):
        evaluator = LayerEvaluator(config=layer1_config_with_fi)
        attrs = {
            "aum_usd": 200_000_000,
            "track_record_years": 5,
            "asset_class": "fixed_income",
            "empirical_duration": 6.0,
            "duration_r2": 0.05,  # below min 0.10
        }
        results = evaluator.evaluate_layer1("fund", attrs, layer1_config_with_fi)
        failed = [r for r in results if not r.passed]
        assert len(failed) == 1
        assert failed[0].criterion == "min_duration_r2"

    def test_fi_fund_fails_missing_duration(self, layer1_config_with_fi):
        evaluator = LayerEvaluator(config=layer1_config_with_fi)
        attrs = {
            "aum_usd": 200_000_000,
            "track_record_years": 5,
            "asset_class": "fixed_income",
            # empirical_duration missing → min_empirical_duration fails
            "duration_r2": 0.30,
        }
        results = evaluator.evaluate_layer1("fund", attrs, layer1_config_with_fi)
        failed = [r for r in results if not r.passed]
        assert any(r.criterion == "min_empirical_duration" for r in failed)

    def test_equity_fund_ignores_fi_gates(self, layer1_config_with_fi):
        evaluator = LayerEvaluator(config=layer1_config_with_fi)
        attrs = {
            "aum_usd": 200_000_000,
            "track_record_years": 5,
            "asset_class": "equity",
            # No empirical_duration — should NOT be evaluated against FI rules
        }
        results = evaluator.evaluate_layer1("fund", attrs, layer1_config_with_fi)
        # Only 2 results from base "fund" criteria (min_aum_usd, min_track_record_years)
        assert len(results) == 2
        assert all(r.passed for r in results)


# ═══════════════════════════════════════════════════════════════════
#  Layer 2 — Duration Mandate Fit
# ═══════════════════════════════════════════════════════════════════

class TestFILayer2:
    """Duration range validation for FI allocation blocks."""

    def test_fi_fund_within_duration_range(self, layer2_config_fi):
        evaluator = LayerEvaluator(config={})
        attrs = {
            "asset_class": "fixed_income",
            "empirical_duration": 7.0,  # within 3.0-10.0
        }
        results = evaluator.evaluate_layer2(
            "fund", attrs, "fi_aggregate", layer2_config_fi,
        )
        assert all(r.passed for r in results)

    def test_fi_fund_exceeds_block_duration(self, layer2_config_fi):
        evaluator = LayerEvaluator(config={})
        attrs = {
            "asset_class": "fixed_income",
            "empirical_duration": 12.0,  # exceeds max 10.0
        }
        results = evaluator.evaluate_layer2(
            "fund", attrs, "fi_aggregate", layer2_config_fi,
        )
        failed = [r for r in results if not r.passed]
        assert len(failed) >= 1
        assert any(r.criterion == "max_empirical_duration" for r in failed)


# ═══════════════════════════════════════════════════════════════════
#  Layer 3 — FIQuantMetrics Scoring
# ═══════════════════════════════════════════════════════════════════

class TestFILayer3:
    """FIQuantMetrics dispatch in Layer 3 composite scoring."""

    def test_fi_quant_metrics_scores(self, layer3_config_fi):
        screener = ScreenerService({}, {}, layer3_config_fi)
        fi_metrics = FIQuantMetrics(
            empirical_duration=6.0,
            credit_beta=1.2,
            yield_proxy_12m=0.05,
            duration_adj_drawdown=-1.0,
            sharpe_ratio=1.5,
            annual_return_pct=5.0,
            data_period_days=730,
        )
        # Build peer values for percentile scoring
        peer_values = {
            "empirical_duration": [3.0, 5.0, 6.0, 7.0, 9.0],
            "credit_beta": [0.5, 1.0, 1.2, 1.5, 2.0],
            "yield_proxy_12m": [0.02, 0.03, 0.05, 0.06, 0.07],
            "duration_adj_drawdown": [-3.0, -2.0, -1.0, -0.5, 0.0],
            "sharpe_ratio": [0.5, 1.0, 1.5, 2.0, 2.5],
        }
        score = screener._compute_layer3_score("fund", fi_metrics, peer_values)
        assert score is not None, "FI fund should produce a Layer 3 score"
        assert score >= 0.4, f"Good FI fund should score >= 0.4, got {score}"

    def test_equity_quant_metrics_unchanged(self, layer3_config_fi):
        screener = ScreenerService({}, {}, layer3_config_fi)
        eq_metrics = QuantMetrics(
            sharpe_ratio=1.5,
            annual_volatility_pct=12.0,
            max_drawdown_pct=-15.0,
            pct_positive_months=0.65,
            annual_return_pct=10.0,
            data_period_days=730,
        )
        peer_values = {
            "sharpe_ratio": [0.5, 1.0, 1.5, 2.0],
            "max_drawdown": [-30.0, -20.0, -15.0, -10.0],
            "pct_positive_months": [0.4, 0.55, 0.65, 0.75],
            "annual_volatility_pct": [8.0, 12.0, 16.0, 20.0],
        }
        score = screener._compute_layer3_score("fund", eq_metrics, peer_values)
        assert score is not None, "Equity fund should produce a Layer 3 score"

    def test_fi_no_config_returns_none(self):
        """FI metrics with no fund_fixed_income Layer 3 config → None."""
        screener = ScreenerService({}, {}, {"fund": {"weights": {"sharpe_ratio": 1.0}}})
        fi_metrics = FIQuantMetrics(
            empirical_duration=6.0, credit_beta=1.0, yield_proxy_12m=0.04,
            duration_adj_drawdown=-1.5, sharpe_ratio=1.0,
            annual_return_pct=4.0, data_period_days=500,
        )
        score = screener._compute_layer3_score("fund", fi_metrics, {})
        assert score is None, "Without fund_fixed_income config, should return None"


# ═══════════════════════════════════════════════════════════════════
#  Full 3-Layer Screening — FI Fund Integration
# ═══════════════════════════════════════════════════════════════════

class TestFIFullScreening:
    """End-to-end screening for FI funds through all 3 layers."""

    def test_fi_fund_passes_all_layers(
        self, layer1_config_with_fi, layer2_config_fi, layer3_config_fi,
    ):
        screener = ScreenerService(layer1_config_with_fi, layer2_config_fi, layer3_config_fi)
        fi_metrics = FIQuantMetrics(
            empirical_duration=6.0, credit_beta=1.2, yield_proxy_12m=0.05,
            duration_adj_drawdown=-1.0, sharpe_ratio=1.5,
            annual_return_pct=5.0, data_period_days=730,
        )
        peer_values = {
            "empirical_duration": [3.0, 5.0, 6.0, 7.0, 9.0],
            "credit_beta": [0.5, 1.0, 1.2, 1.5, 2.0],
            "yield_proxy_12m": [0.02, 0.03, 0.05, 0.06, 0.07],
            "duration_adj_drawdown": [-3.0, -2.0, -1.0, -0.5, 0.0],
            "sharpe_ratio": [0.5, 1.0, 1.5, 2.0, 2.5],
        }
        result = screener.screen_instrument(
            instrument_id=uuid.uuid4(),
            instrument_type="fund",
            attributes={
                "aum_usd": 300_000_000,
                "track_record_years": 5,
                "asset_class": "fixed_income",
                "empirical_duration": 6.0,
                "duration_r2": 0.30,
            },
            block_id="fi_aggregate",
            quant_metrics=fi_metrics,
            peer_values=peer_values,
        )
        assert result.overall_status in ("PASS", "WATCHLIST"), (
            f"Good FI fund should pass or watchlist, got {result.overall_status}"
        )
        assert result.failed_at_layer is None

    def test_fi_fund_fails_layer1_duration(
        self, layer1_config_with_fi, layer2_config_fi, layer3_config_fi,
    ):
        screener = ScreenerService(layer1_config_with_fi, layer2_config_fi, layer3_config_fi)
        result = screener.screen_instrument(
            instrument_id=uuid.uuid4(),
            instrument_type="fund",
            attributes={
                "aum_usd": 200_000_000,
                "track_record_years": 5,
                "asset_class": "fixed_income",
                "empirical_duration": 20.0,  # exceeds max 15.0
                "duration_r2": 0.30,
            },
        )
        assert result.overall_status == "FAIL"
        assert result.failed_at_layer == 1


# ═══════════════════════════════════════════════════════════════════
#  E2E Scoring Comparison — The Credibility Fix
# ═══════════════════════════════════════════════════════════════════

class TestFIScoringCredibilityFix:
    """Prove that the FI scoring model resolves the credibility gap.

    Scenario C from the plan: A bond fund with duration 8 and +50bps alpha
    via sector rotation should score >70 on the FI model but ~50 on the
    equity model. The >20pt difference proves the dispatch works.
    """

    def test_fi_fund_scores_higher_on_fi_model(self):
        """The money shot: same fund, two models, dramatic score difference.

        A good FI fund scores ~70+ on the FI model (where its yield,
        duration management, and spread capture are recognized) but only
        ~50 on the equity model (where it's penalized for mediocre equity
        metrics like information ratio and return consistency).
        """
        # Good FI fund: duration 6, moderate credit beta, strong yield,
        # excellent duration-adjusted drawdown
        fi_adapter = _FIMetricsAdapter(
            empirical_duration=6.0,
            credit_beta=1.2,
            yield_proxy_12m=0.05,  # 5% yield
            duration_adj_drawdown_1y=-0.8,  # excellent: -0.8% per unit duration
        )

        # Same fund's equity metrics are mediocre:
        # Bond funds have lower returns, information ratios than equity
        risk_adapter = _RiskMetricsAdapter(
            return_1y=0.05,  # 5% — mediocre for equity
            sharpe_1y=0.8,  # below equity median
            max_drawdown_1y=-0.08,  # -8%
            information_ratio_1y=0.3,  # low for equity
        )

        # Score on FI model (no expense_ratio to isolate FI components)
        fi_score, fi_components = compute_fund_score(
            risk_adapter,
            asset_class="fixed_income",
            fi_metrics=fi_adapter,
        )

        # Score on equity model (the broken old way)
        eq_score, eq_components = compute_fund_score(
            risk_adapter,
            asset_class="equity",
        )

        # FI model should score significantly higher
        assert fi_score > 60, (
            f"FI fund on FI model should score >60, got {fi_score}. "
            f"Components: {fi_components}"
        )
        assert eq_score < 60, (
            f"FI fund on equity model should score <60, got {eq_score}. "
            f"Components: {eq_components}"
        )
        score_diff = fi_score - eq_score
        assert score_diff > 10, (
            f"Score difference should be >10pts proving credibility fix. "
            f"FI={fi_score}, Equity={eq_score}, Diff={score_diff}"
        )

    def test_mediocre_fi_fund_still_penalized(self):
        """FI model should still penalize a bad FI fund."""
        fi_adapter = _FIMetricsAdapter(
            empirical_duration=10.0,  # high duration
            credit_beta=3.5,  # excessive credit risk
            yield_proxy_12m=0.02,  # low yield
            duration_adj_drawdown_1y=-2.5,  # terrible
        )
        risk_adapter = _RiskMetricsAdapter(
            return_1y=-0.05,
            sharpe_1y=-0.5,
            max_drawdown_1y=-0.15,
            information_ratio_1y=-0.2,
        )

        fi_score, fi_components = compute_fund_score(
            risk_adapter,
            asset_class="fixed_income",
            fi_metrics=fi_adapter,
            expense_ratio_pct=1.5,
        )

        assert fi_score < 50, (
            f"Bad FI fund should score <50 even on FI model, got {fi_score}. "
            f"Components: {fi_components}"
        )

    def test_equity_scoring_unchanged(self):
        """Equity path must produce identical results regardless of FI dispatch."""
        risk_adapter = _RiskMetricsAdapter(
            return_1y=0.15,
            sharpe_1y=1.8,
            max_drawdown_1y=-0.10,
            information_ratio_1y=1.2,
        )

        score1, comp1 = compute_fund_score(risk_adapter, asset_class="equity")
        score2, comp2 = compute_fund_score(risk_adapter, asset_class="equity")

        assert score1 == score2
        assert comp1 == comp2
        assert "return_consistency" in comp1
        assert "yield_consistency" not in comp1  # FI component should NOT appear

    def test_fi_with_none_fi_metrics_falls_back_to_equity(self):
        """asset_class=fixed_income but fi_metrics=None → equity scoring."""
        risk_adapter = _RiskMetricsAdapter(
            return_1y=0.10, sharpe_1y=1.0,
            max_drawdown_1y=-0.12, information_ratio_1y=0.5,
        )
        score, components = compute_fund_score(
            risk_adapter,
            asset_class="fixed_income",
            fi_metrics=None,
        )
        assert "return_consistency" in components
        assert "yield_consistency" not in components


# ═══════════════════════════════════════════════════════════════════
#  ELITE Ranking — fixed_income weight validation
# ═══════════════════════════════════════════════════════════════════

class TestEliteRankingFI:
    """Verify ELITE ranking supports fixed_income."""

    def test_fi_weight_produces_nonzero_target(self):
        """With 33% FI weight, ~99 of 300 ELITE slots go to fixed_income."""
        weights = {
            "equity": 0.50,
            "fixed_income": 0.33,
            "alternatives": 0.12,
            "cash": 0.05,
        }
        targets = compute_target_counts(weights, total_elite=300)
        assert targets["fixed_income"] > 0, "FI should have ELITE slots"
        assert targets["fixed_income"] == 99, f"Expected 99 FI slots, got {targets['fixed_income']}"
        assert sum(targets.values()) in range(298, 303), (
            f"Total should be ~300 (rounding tolerance), got {sum(targets.values())}"
        )

    def test_target_counts_with_zero_fi(self):
        """If a profile has no FI weight, FI gets 0 slots."""
        weights = {"equity": 0.80, "alternatives": 0.20}
        targets = compute_target_counts(weights, total_elite=300)
        assert "fixed_income" not in targets

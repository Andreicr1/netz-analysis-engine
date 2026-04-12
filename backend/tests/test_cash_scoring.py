"""Tests for Cash/MMF Scoring Model.

Covers:
- cash_analytics_service: pure scoring computation
- scoring_service: cash dispatch via compute_fund_score
- Screener Layer 1: fund_cash eliminatory gate
- Screener Layer 3: CashQuantMetrics scoring dispatch
- E2E scoring comparison: MMF scored on cash model vs equity model
"""

from __future__ import annotations

import pytest

from quant_engine.cash_analytics_service import (
    CashAnalyticsResult,
    CashScoreResult,
    _DEFAULT_CASH_SCORING_WEIGHTS,
    compute_cash_score,
)
from quant_engine.scoring_service import (
    _DEFAULT_CASH_SCORING_WEIGHTS as SCORING_CASH_WEIGHTS,
    compute_fund_score,
    resolve_scoring_weights,
)
from vertical_engines.wealth.screener.layer_evaluator import LayerEvaluator
from vertical_engines.wealth.screener.quant_metrics import CashQuantMetrics


# ═══════════════════════════════════════════════════════════════════
#  Helpers
# ═══════════════════════════════════════════════════════════════════

class _CashMetricsAdapter:
    """Adapter satisfying CashMetrics protocol for scoring_service."""

    def __init__(
        self,
        seven_day_net_yield=None,
        fed_funds_rate_at_calc=None,
        nav_per_share_mmf=None,
        pct_weekly_liquid=None,
        weighted_avg_maturity_days=None,
    ):
        self.seven_day_net_yield = seven_day_net_yield
        self.fed_funds_rate_at_calc = fed_funds_rate_at_calc
        self.nav_per_share_mmf = nav_per_share_mmf
        self.pct_weekly_liquid = pct_weekly_liquid
        self.weighted_avg_maturity_days = weighted_avg_maturity_days


class _RiskMetricsAdapter:
    """Adapter satisfying RiskMetrics protocol for scoring_service."""

    def __init__(
        self,
        return_1y=None,
        sharpe_1y=None,
        max_drawdown_1y=None,
        information_ratio_1y=None,
    ):
        self.return_1y = return_1y
        self.sharpe_1y = sharpe_1y
        self.max_drawdown_1y = max_drawdown_1y
        self.information_ratio_1y = information_ratio_1y


# ═══════════════════════════════════════════════════════════════════
#  Fixtures
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture
def good_mmf_analytics():
    """A strong government MMF: high yield, stable NAV, high liquidity, low WAM."""
    return CashAnalyticsResult(
        seven_day_net_yield=5.30,
        fed_funds_rate=5.33,
        nav_per_share=1.0000,
        pct_weekly_liquid=85.0,
        weighted_avg_maturity=15,
    )


@pytest.fixture
def weak_mmf_analytics():
    """A weak prime MMF: lower yield, slight NAV deviation, lower liquidity, high WAM."""
    return CashAnalyticsResult(
        seven_day_net_yield=4.50,
        fed_funds_rate=5.33,
        nav_per_share=0.9995,
        pct_weekly_liquid=35.0,
        weighted_avg_maturity=55,
    )


@pytest.fixture
def layer1_config_with_cash():
    """Layer 1 config with both fund and fund_cash rules."""
    return {
        "fund": {
            "min_aum_usd": 100_000_000,
            "min_track_record_years": 3,
        },
        "fund_cash": {
            "min_pct_weekly_liquid": 30.0,
            "max_weighted_avg_maturity": 60,
            "min_net_assets": 100_000_000,
        },
    }


# ═══════════════════════════════════════════════════════════════════
#  Tests: cash_analytics_service
# ═══════════════════════════════════════════════════════════════════

class TestCashAnalyticsService:
    """Test pure cash scoring computation."""

    def test_good_mmf_scores_high(self, good_mmf_analytics):
        result = compute_cash_score(good_mmf_analytics, expense_ratio_pct=0.15)
        assert isinstance(result, CashScoreResult)
        assert result.score > 60.0, f"Strong MMF should score >60, got {result.score}"
        assert "yield_vs_risk_free" in result.components
        assert "nav_stability" in result.components
        assert "liquidity_quality" in result.components
        assert "maturity_discipline" in result.components
        assert "fee_efficiency" in result.components

    def test_weak_mmf_scores_lower(self, good_mmf_analytics, weak_mmf_analytics):
        strong = compute_cash_score(good_mmf_analytics, expense_ratio_pct=0.15)
        weak = compute_cash_score(weak_mmf_analytics, expense_ratio_pct=0.50)
        assert strong.score > weak.score, (
            f"Strong MMF ({strong.score}) should outscore weak ({weak.score})"
        )

    def test_perfect_nav_stability(self):
        analytics = CashAnalyticsResult(
            seven_day_net_yield=None,
            fed_funds_rate=None,
            nav_per_share=1.0000,
            pct_weekly_liquid=None,
            weighted_avg_maturity=None,
        )
        result = compute_cash_score(analytics)
        assert result.components["nav_stability"] == 100.0

    def test_broken_buck_nav_stability(self):
        analytics = CashAnalyticsResult(
            seven_day_net_yield=None,
            fed_funds_rate=None,
            nav_per_share=0.9990,
            pct_weekly_liquid=None,
            weighted_avg_maturity=None,
        )
        result = compute_cash_score(analytics)
        assert result.components["nav_stability"] == 0.0, "0.001 deviation should score 0"

    def test_maturity_discipline_zero_wam(self):
        analytics = CashAnalyticsResult(
            seven_day_net_yield=None,
            fed_funds_rate=None,
            nav_per_share=None,
            pct_weekly_liquid=None,
            weighted_avg_maturity=0,
        )
        result = compute_cash_score(analytics)
        assert result.components["maturity_discipline"] == 100.0

    def test_maturity_discipline_max_wam(self):
        analytics = CashAnalyticsResult(
            seven_day_net_yield=None,
            fed_funds_rate=None,
            nav_per_share=None,
            pct_weekly_liquid=None,
            weighted_avg_maturity=60,
        )
        result = compute_cash_score(analytics)
        assert result.components["maturity_discipline"] == 0.0

    def test_yield_exactly_matches_ffr(self):
        analytics = CashAnalyticsResult(
            seven_day_net_yield=5.33,
            fed_funds_rate=5.33,
            nav_per_share=None,
            pct_weekly_liquid=None,
            weighted_avg_maturity=None,
        )
        result = compute_cash_score(analytics)
        # relative_yield = 0, normalized in [-0.20, 0.20] => 50.0
        assert result.components["yield_vs_risk_free"] == 50.0

    def test_missing_data_penalty(self):
        analytics = CashAnalyticsResult(
            seven_day_net_yield=None,
            fed_funds_rate=None,
            nav_per_share=None,
            pct_weekly_liquid=None,
            weighted_avg_maturity=None,
        )
        result = compute_cash_score(analytics)
        # Most components get 40.0 (45 - 5 penalty), fee_efficiency gets 45.0 (different path)
        for key, val in result.components.items():
            if key == "fee_efficiency":
                assert val == 45.0, f"{key} should be 45.0 with no ER data, got {val}"
            else:
                assert val == 40.0, f"{key} should be 40.0 with missing data, got {val}"

    def test_default_weights_sum_to_one(self):
        total = sum(_DEFAULT_CASH_SCORING_WEIGHTS.values())
        assert abs(total - 1.0) < 0.001, f"Weights sum to {total}, should be 1.0"


# ═══════════════════════════════════════════════════════════════════
#  Tests: scoring_service cash dispatch
# ═══════════════════════════════════════════════════════════════════

class TestScoringServiceCashDispatch:
    """Test scoring_service dispatches to cash path."""

    def test_resolve_weights_cash(self):
        weights = resolve_scoring_weights(config=None, asset_class="cash")
        assert weights == SCORING_CASH_WEIGHTS

    def test_compute_fund_score_cash_dispatch(self):
        risk = _RiskMetricsAdapter(return_1y=0.05, sharpe_1y=0.5, max_drawdown_1y=-0.01)
        cash = _CashMetricsAdapter(
            seven_day_net_yield=5.30,
            fed_funds_rate_at_calc=5.33,
            nav_per_share_mmf=1.0000,
            pct_weekly_liquid=85.0,
            weighted_avg_maturity_days=15,
        )
        score, components = compute_fund_score(
            risk, asset_class="cash", cash_metrics=cash, expense_ratio_pct=0.15,
        )
        assert "yield_vs_risk_free" in components, "Cash dispatch should use cash components"
        assert "nav_stability" in components
        assert "sharpe_ratio" not in components, "Cash dispatch should NOT use equity components"

    def test_cash_fallback_to_equity_if_no_metrics(self):
        risk = _RiskMetricsAdapter(return_1y=0.05, sharpe_1y=0.5, max_drawdown_1y=-0.01)
        score, components = compute_fund_score(
            risk, asset_class="cash", cash_metrics=None,
        )
        # Should fall through to equity scoring
        assert "return_consistency" in components


# ═══════════════════════════════════════════════════════════════════
#  Tests: Screener Layer 1 cash gate
# ═══════════════════════════════════════════════════════════════════

class TestScreenerCashGate:
    """Test Layer 1 eliminatory gate for cash funds."""

    def test_cash_gate_passes_compliant_fund(self, layer1_config_with_cash):
        evaluator = LayerEvaluator(config={})
        attrs = {
            "asset_class": "cash",
            "pct_weekly_liquid": 85.0,
            "weighted_avg_maturity": 15,
            "net_assets": 500_000_000,
            "aum_usd": 500_000_000,
            "track_record_years": 5,
        }
        results = evaluator.evaluate_layer1("fund", attrs, layer1_config_with_cash)
        fails = [r for r in results if not r.passed]
        assert len(fails) == 0, f"Compliant cash fund should pass, got fails: {fails}"

    def test_cash_gate_evaluates_cash_criteria(self, layer1_config_with_cash):
        evaluator = LayerEvaluator(config={})
        attrs = {
            "asset_class": "cash",
            "pct_weekly_liquid": 20.0,  # Below 30% minimum
            "weighted_avg_maturity": 15,
            "net_assets": 500_000_000,
            "aum_usd": 500_000_000,
            "track_record_years": 5,
        }
        results = evaluator.evaluate_layer1("fund", attrs, layer1_config_with_cash)
        # Should evaluate more criteria than just "fund" rules (includes fund_cash)
        criteria_names = {r.criterion for r in results}
        assert "min_pct_weekly_liquid" in criteria_names, (
            f"Should evaluate fund_cash criteria, got: {criteria_names}"
        )


# ═══════════════════════════════════════════════════════════════════
#  Tests: CashQuantMetrics
# ═══════════════════════════════════════════════════════════════════

class TestCashQuantMetrics:
    """Test CashQuantMetrics dataclass construction."""

    def test_creates_frozen_dataclass(self):
        m = CashQuantMetrics(
            yield_vs_risk_free=65.0,
            nav_stability=100.0,
            liquidity_quality=78.0,
            maturity_discipline=75.0,
            fee_efficiency=92.5,
            data_source="mmf_filing",
        )
        assert m.yield_vs_risk_free == 65.0
        assert m.data_source == "mmf_filing"
        with pytest.raises(AttributeError):
            m.yield_vs_risk_free = 50.0  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
#  Tests: E2E scoring comparison — Cash model vs Equity model
# ═══════════════════════════════════════════════════════════════════

class TestCashVsEquityScoring:
    """Compare scoring of an MMF under cash model vs equity model.

    The key insight: MMFs with ~0.5% annualized volatility produce absurd
    Sharpe ratios (>>10) under the equity model, or get discarded entirely
    by the MIN_ANNUALIZED_VOL guard. The cash model uses fundamentally
    different metrics (yield spread, NAV stability, liquidity, maturity).
    """

    def test_mmf_on_equity_model_degrades(self):
        """MMF scored on equity model gets penalized: low drawdown control
        (near-zero drawdown saturates at 100), unstable Sharpe (near-zero vol),
        and missing information_ratio."""
        risk = _RiskMetricsAdapter(
            return_1y=0.0530,   # 5.3% return (yield)
            sharpe_1y=None,     # Discarded by MIN_ANNUALIZED_VOL guard
            max_drawdown_1y=-0.0005,  # Near-zero drawdown
            information_ratio_1y=None,
        )
        score_equity, comp_equity = compute_fund_score(
            risk, asset_class="equity",
        )
        # With None Sharpe, the equity model assigns opacity penalty
        assert comp_equity["risk_adjusted_return"] == 45.0

    def test_mmf_on_cash_model_uses_fundamentals(self):
        """Same MMF on cash model uses yield, NAV stability, liquidity, maturity."""
        risk = _RiskMetricsAdapter(return_1y=0.0530)
        cash = _CashMetricsAdapter(
            seven_day_net_yield=5.30,
            fed_funds_rate_at_calc=5.33,
            nav_per_share_mmf=1.0000,
            pct_weekly_liquid=85.0,
            weighted_avg_maturity_days=15,
        )
        score_cash, comp_cash = compute_fund_score(
            risk, asset_class="cash", cash_metrics=cash, expense_ratio_pct=0.15,
        )
        assert "yield_vs_risk_free" in comp_cash
        assert "nav_stability" in comp_cash
        assert comp_cash["nav_stability"] == 100.0  # Perfect $1.00
        assert score_cash > 50.0, f"Good MMF should score >50 on cash model, got {score_cash}"

    def test_cash_model_outperforms_equity_for_mmf(self):
        """The cash model should produce more meaningful differentiation
        between strong and weak MMFs than the equity model would."""
        risk = _RiskMetricsAdapter(return_1y=0.0530, max_drawdown_1y=-0.0005)

        # Strong MMF
        cash_strong = _CashMetricsAdapter(
            seven_day_net_yield=5.50,
            fed_funds_rate_at_calc=5.33,
            nav_per_share_mmf=1.0000,
            pct_weekly_liquid=90.0,
            weighted_avg_maturity_days=10,
        )
        # Weak MMF
        cash_weak = _CashMetricsAdapter(
            seven_day_net_yield=4.50,
            fed_funds_rate_at_calc=5.33,
            nav_per_share_mmf=0.9997,
            pct_weekly_liquid=35.0,
            weighted_avg_maturity_days=55,
        )

        score_strong, _ = compute_fund_score(
            risk, asset_class="cash", cash_metrics=cash_strong, expense_ratio_pct=0.10,
        )
        score_weak, _ = compute_fund_score(
            risk, asset_class="cash", cash_metrics=cash_weak, expense_ratio_pct=0.50,
        )

        spread = score_strong - score_weak
        assert spread > 15.0, (
            f"Cash model should differentiate strong vs weak MMF by >15pts, "
            f"got spread={spread:.1f} (strong={score_strong:.1f}, weak={score_weak:.1f})"
        )

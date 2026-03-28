"""Tests for scoring_service — fee_efficiency component and Lipper removal.

Covers:
- Default weight sum validation
- Fee efficiency linear formula (0% ER → 100, 2% ER → 0)
- Neutral default when expense_ratio_pct is None
- Insider sentiment opt-in behavior
- Lipper parameter removal verification
- Backward-compatible positional args
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from quant_engine.scoring_service import (
    _DEFAULT_SCORING_WEIGHTS,
    compute_fund_score,
)


def _make_metrics(
    return_1y: float | None = 0.10,
    sharpe_1y: float | None = 1.2,
    max_drawdown_1y: float | None = -0.08,
    information_ratio_1y: float | None = 0.6,
) -> MagicMock:
    """Factory for RiskMetrics-like mock."""
    m = MagicMock()
    m.return_1y = return_1y
    m.sharpe_1y = sharpe_1y
    m.max_drawdown_1y = max_drawdown_1y
    m.information_ratio_1y = information_ratio_1y
    return m


class TestDefaultWeights:
    def test_default_weights_sum_to_one(self):
        total = sum(_DEFAULT_SCORING_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_default_weights_has_six_components(self):
        assert len(_DEFAULT_SCORING_WEIGHTS) == 6

    def test_no_lipper_in_defaults(self):
        assert "lipper_rating" not in _DEFAULT_SCORING_WEIGHTS
        assert "lipper_score" not in _DEFAULT_SCORING_WEIGHTS


class TestFeeEfficiency:
    def test_fee_efficiency_with_low_er(self):
        """expense_ratio_pct=0.035 → fee_efficiency near 98.25."""
        metrics = _make_metrics()
        _, components = compute_fund_score(metrics, expense_ratio_pct=0.035)
        assert abs(components["fee_efficiency"] - 98.25) < 0.01

    def test_fee_efficiency_with_high_er(self):
        """expense_ratio_pct=1.52 → fee_efficiency near 24.0."""
        metrics = _make_metrics()
        _, components = compute_fund_score(metrics, expense_ratio_pct=1.52)
        assert abs(components["fee_efficiency"] - 24.0) < 0.01

    def test_fee_efficiency_none_defaults_neutral(self):
        """expense_ratio_pct=None → fee_efficiency == 50.0."""
        metrics = _make_metrics()
        _, components = compute_fund_score(metrics, expense_ratio_pct=None)
        assert components["fee_efficiency"] == 50.0

    def test_fee_efficiency_2pct_is_zero(self):
        """expense_ratio_pct=2.0 → fee_efficiency == 0.0."""
        metrics = _make_metrics()
        _, components = compute_fund_score(metrics, expense_ratio_pct=2.0)
        assert components["fee_efficiency"] == 0.0

    def test_fee_efficiency_zero_er_is_100(self):
        """expense_ratio_pct=0.0 → fee_efficiency == 100.0."""
        metrics = _make_metrics()
        _, components = compute_fund_score(metrics, expense_ratio_pct=0.0)
        assert components["fee_efficiency"] == 100.0

    def test_fee_efficiency_above_2pct_clamped_to_zero(self):
        """expense_ratio_pct=3.0 → fee_efficiency == 0.0 (clamped by max(0, ...))."""
        metrics = _make_metrics()
        _, components = compute_fund_score(metrics, expense_ratio_pct=3.0)
        assert components["fee_efficiency"] == 0.0


class TestInsiderSentiment:
    def test_insider_sentiment_opt_in_only(self):
        """Without insider_sentiment weight in config, param is ignored."""
        metrics = _make_metrics()
        _, components = compute_fund_score(
            metrics, insider_sentiment_score=80.0,
        )
        assert "insider_sentiment" not in components

    def test_insider_sentiment_with_weight(self):
        """Config with insider_sentiment weight → component included."""
        metrics = _make_metrics()
        config = {
            "scoring_weights": {
                "return_consistency": 0.20,
                "risk_adjusted_return": 0.25,
                "drawdown_control": 0.15,
                "information_ratio": 0.15,
                "flows_momentum": 0.10,
                "fee_efficiency": 0.10,
                "insider_sentiment": 0.05,
            },
        }
        _, components = compute_fund_score(
            metrics, config=config, insider_sentiment_score=80.0,
        )
        assert "insider_sentiment" in components
        assert components["insider_sentiment"] == 80.0

    def test_insider_sentiment_none_ignored_even_with_weight(self):
        """insider_sentiment_score=None → not in components even if weight exists."""
        metrics = _make_metrics()
        config = {
            "scoring_weights": {
                "return_consistency": 0.20,
                "risk_adjusted_return": 0.25,
                "drawdown_control": 0.15,
                "information_ratio": 0.15,
                "flows_momentum": 0.10,
                "fee_efficiency": 0.10,
                "insider_sentiment": 0.05,
            },
        }
        _, components = compute_fund_score(
            metrics, config=config, insider_sentiment_score=None,
        )
        assert "insider_sentiment" not in components


class TestLipperRemoval:
    def test_no_lipper_parameter(self):
        """Verify lipper_score is NOT a parameter of compute_fund_score."""
        sig = inspect.signature(compute_fund_score)
        assert "lipper_score" not in sig.parameters

    def test_no_lipper_rating_parameter(self):
        sig = inspect.signature(compute_fund_score)
        assert "lipper_rating" not in sig.parameters


class TestBackwardCompat:
    def test_positional_flows_momentum(self):
        """compute_fund_score(metrics, 50.0, None) still works."""
        metrics = _make_metrics()
        score, components = compute_fund_score(metrics, 50.0, None)
        assert isinstance(score, float)
        assert "flows_momentum" in components
        assert components["flows_momentum"] == 50.0

    def test_score_range(self):
        """Score is between 0 and 100."""
        metrics = _make_metrics()
        score, _ = compute_fund_score(metrics)
        assert 0.0 <= score <= 100.0

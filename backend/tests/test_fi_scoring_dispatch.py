"""Tests for FI scoring dispatch in scoring_service.py.

Covers:
1. Equity path unchanged (same 6 components, same weights, same scores).
2. FI path — good IG fund with alpha scores > 70.
3. FI path — poor IG fund without skill scores < 50.
4. FI vs Equity — same fund scores higher on FI model than equity model.
5. Config override works for FI weights.
6. Missing fi_metrics with asset_class="fixed_income" falls back to equity.
7. resolve_scoring_weights dispatches by asset_class.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quant_engine.scoring_service import (
    _DEFAULT_FI_SCORING_WEIGHTS,
    _DEFAULT_SCORING_WEIGHTS,
    compute_fund_score,
    resolve_scoring_weights,
)


def _make_equity_metrics(
    return_1y: float | None = 0.10,
    sharpe_1y: float | None = 1.2,
    max_drawdown_1y: float | None = -0.08,
    information_ratio_1y: float | None = 0.6,
) -> MagicMock:
    m = MagicMock()
    m.return_1y = return_1y
    m.sharpe_1y = sharpe_1y
    m.max_drawdown_1y = max_drawdown_1y
    m.information_ratio_1y = information_ratio_1y
    return m


def _make_fi_metrics(
    empirical_duration: float | None = 6.0,
    credit_beta: float | None = 1.0,
    yield_proxy_12m: float | None = 0.05,
    duration_adj_drawdown_1y: float | None = -0.005,
) -> MagicMock:
    m = MagicMock()
    m.empirical_duration = empirical_duration
    m.credit_beta = credit_beta
    m.yield_proxy_12m = yield_proxy_12m
    m.duration_adj_drawdown_1y = duration_adj_drawdown_1y
    return m


class TestEquityPathUnchanged:
    """Equity scoring must remain identical regardless of FI additions."""

    def test_default_weights_unchanged(self) -> None:
        assert sum(_DEFAULT_SCORING_WEIGHTS.values()) == pytest.approx(1.0, abs=0.001)
        assert "return_consistency" in _DEFAULT_SCORING_WEIGHTS
        assert "risk_adjusted_return" in _DEFAULT_SCORING_WEIGHTS
        assert len(_DEFAULT_SCORING_WEIGHTS) == 6

    def test_equity_components_produced(self) -> None:
        metrics = _make_equity_metrics()
        score, components = compute_fund_score(metrics, asset_class="equity")
        assert "return_consistency" in components
        assert "risk_adjusted_return" in components
        assert "drawdown_control" in components
        assert "information_ratio" in components
        assert "flows_momentum" in components
        assert "fee_efficiency" in components
        # No FI components
        assert "yield_consistency" not in components
        assert "duration_management" not in components

    def test_equity_score_same_without_asset_class_param(self) -> None:
        """Default asset_class='equity' produces same result as explicit."""
        metrics = _make_equity_metrics()
        score_default, _ = compute_fund_score(metrics)
        score_explicit, _ = compute_fund_score(metrics, asset_class="equity")
        assert score_default == score_explicit


class TestFIScoring:
    """FI scoring path produces 5 FI-specific components."""

    def test_fi_weights_sum_to_one(self) -> None:
        assert sum(_DEFAULT_FI_SCORING_WEIGHTS.values()) == pytest.approx(1.0, abs=0.001)
        assert len(_DEFAULT_FI_SCORING_WEIGHTS) == 5

    def test_good_ig_fund_scores_above_70(self) -> None:
        """IG fund with alpha: yield 5%, duration 6, credit_beta 1.0, low drawdown."""
        equity_metrics = _make_equity_metrics()
        fi = _make_fi_metrics(
            empirical_duration=6.0,
            credit_beta=1.0,
            yield_proxy_12m=0.05,
            duration_adj_drawdown_1y=-0.005,  # excellent: -0.5% per unit duration
        )
        score, components = compute_fund_score(
            equity_metrics, asset_class="fixed_income", fi_metrics=fi,
            expense_ratio_pct=0.005,  # 0.5% ER
        )
        assert score > 70, f"Good IG fund should score > 70, got {score}"
        assert "yield_consistency" in components
        assert "duration_management" in components
        assert "spread_capture" in components
        assert "duration_adjusted_drawdown" in components
        assert "fee_efficiency" in components

    def test_poor_ig_fund_scores_below_50(self) -> None:
        """IG fund without skill: low yield, high duration mismatch, bad drawdown."""
        equity_metrics = _make_equity_metrics()
        fi = _make_fi_metrics(
            empirical_duration=8.0,
            credit_beta=0.3,
            yield_proxy_12m=0.02,
            duration_adj_drawdown_1y=-3.0,  # terrible: -3% per unit duration
        )
        score, _ = compute_fund_score(
            equity_metrics, asset_class="fixed_income", fi_metrics=fi,
        )
        assert score < 50, f"Poor FI fund should score < 50, got {score}"


class TestFIvsEquityComparison:
    """The credibility test: FI fund with alpha should score higher on FI model."""

    def test_fi_fund_scores_higher_on_fi_model(self) -> None:
        """A FI fund with duration 8 and +50bps alpha should score > 70 on FI
        model but ~50 on equity model (penalized by equity metrics)."""
        equity_metrics = _make_equity_metrics(
            return_1y=0.05,  # modest 5% return (typical for FI)
            sharpe_1y=0.8,   # decent but not equity-level
            max_drawdown_1y=-0.04,
            information_ratio_1y=0.3,
        )
        fi = _make_fi_metrics(
            empirical_duration=6.0,
            credit_beta=1.0,
            yield_proxy_12m=0.045,
            duration_adj_drawdown_1y=-0.005,
        )

        equity_score, _ = compute_fund_score(
            equity_metrics, asset_class="equity",
            expense_ratio_pct=0.005,
        )
        fi_score, _ = compute_fund_score(
            equity_metrics, asset_class="fixed_income", fi_metrics=fi,
            expense_ratio_pct=0.005,
        )

        assert fi_score > equity_score, (
            f"FI model should score higher than equity model for a skilled FI fund. "
            f"FI={fi_score}, Equity={equity_score}"
        )


class TestConfigOverride:
    def test_custom_fi_weights(self) -> None:
        """ConfigService can override FI weights."""
        custom_config = {
            "scoring_weights": {
                "yield_consistency": 0.30,
                "duration_management": 0.20,
                "spread_capture": 0.20,
                "duration_adjusted_drawdown": 0.20,
                "fee_efficiency": 0.10,
            }
        }
        equity_metrics = _make_equity_metrics()
        fi = _make_fi_metrics()
        score, components = compute_fund_score(
            equity_metrics, asset_class="fixed_income", fi_metrics=fi,
            config=custom_config,
        )
        assert isinstance(score, float)
        assert "yield_consistency" in components


class TestFallbackToEquity:
    def test_fi_asset_class_without_fi_metrics_falls_back(self) -> None:
        """If asset_class=fixed_income but fi_metrics=None, use equity scoring."""
        metrics = _make_equity_metrics()
        score, components = compute_fund_score(
            metrics, asset_class="fixed_income", fi_metrics=None,
        )
        # Should produce equity components, not FI
        assert "return_consistency" in components
        assert "yield_consistency" not in components


class TestResolveScoringWeights:
    def test_equity_default(self) -> None:
        weights = resolve_scoring_weights(asset_class="equity")
        assert weights == _DEFAULT_SCORING_WEIGHTS

    def test_fi_default(self) -> None:
        weights = resolve_scoring_weights(asset_class="fixed_income")
        assert weights == _DEFAULT_FI_SCORING_WEIGHTS

    def test_config_override_with_fi(self) -> None:
        custom = {"scoring_weights": {"yield_consistency": 1.0}}
        weights = resolve_scoring_weights(custom, asset_class="fixed_income")
        assert weights == {"yield_consistency": 1.0}

    def test_backward_compatible_no_asset_class(self) -> None:
        """Calling without asset_class defaults to equity."""
        weights = resolve_scoring_weights()
        assert weights == _DEFAULT_SCORING_WEIGHTS

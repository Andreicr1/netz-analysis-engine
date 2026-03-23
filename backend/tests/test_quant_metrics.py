"""Tests for vertical_engines.wealth.screener.quant_metrics — quant computation."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from vertical_engines.wealth.screener.quant_metrics import (
    BondQuantMetrics,
    QuantMetrics,
    composite_score,
    compute_bond_metrics,
    compute_quant_metrics,
)

# ── Helpers ──────────────────────────────────────────────────────


def _make_price_history(
    days: int = 500,
    start_price: float = 100.0,
    daily_return: float = 0.0003,
    volatility: float = 0.01,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic daily price data."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(end="2026-03-01", periods=days)
    n = len(dates)
    returns = rng.normal(daily_return, volatility, n)
    prices = start_price * np.cumprod(1 + returns)
    return pd.DataFrame({"Close": prices}, index=dates)


# ── compute_quant_metrics ────────────────────────────────────────


class TestComputeQuantMetrics:
    def test_basic_metrics(self):
        history = _make_price_history(days=500)
        result = compute_quant_metrics(history)
        assert result is not None
        assert isinstance(result, QuantMetrics)
        assert not math.isnan(result.sharpe_ratio)
        assert result.annual_volatility_pct > 0
        assert result.max_drawdown_pct <= 0  # drawdown is negative
        assert 0 <= result.pct_positive_months <= 1
        assert result.data_period_days > 0

    def test_none_history_returns_none(self):
        assert compute_quant_metrics(None) is None

    def test_empty_dataframe_returns_none(self):
        assert compute_quant_metrics(pd.DataFrame()) is None

    def test_no_close_column_returns_none(self):
        df = pd.DataFrame({"Volume": [100, 200]}, index=pd.bdate_range("2026-01-01", periods=2))
        assert compute_quant_metrics(df) is None

    def test_insufficient_data_returns_none(self):
        # Less than 60 data points
        history = _make_price_history(days=30)
        assert compute_quant_metrics(history) is None

    def test_flat_series_returns_none(self):
        dates = pd.bdate_range(end="2026-03-01", periods=100)
        history = pd.DataFrame({"Close": [100.0] * len(dates)}, index=dates)
        assert compute_quant_metrics(history) is None

    def test_adj_close_column_supported(self):
        history = _make_price_history(days=200)
        history = history.rename(columns={"Close": "Adj Close"})
        result = compute_quant_metrics(history)
        assert result is not None

    def test_positive_returns_have_positive_sharpe(self):
        # High positive daily return
        history = _make_price_history(days=500, daily_return=0.001, volatility=0.005)
        result = compute_quant_metrics(history)
        assert result is not None
        assert result.sharpe_ratio > 0
        assert result.annual_return_pct > 0

    def test_custom_risk_free_rate(self):
        history = _make_price_history(days=500)
        result_low_rf = compute_quant_metrics(history, risk_free_rate_annual=0.01)
        result_high_rf = compute_quant_metrics(history, risk_free_rate_annual=0.10)
        assert result_low_rf is not None and result_high_rf is not None
        # Higher risk-free rate → lower Sharpe
        assert result_low_rf.sharpe_ratio > result_high_rf.sharpe_ratio

    def test_results_are_rounded(self):
        history = _make_price_history(days=500)
        result = compute_quant_metrics(history)
        assert result is not None
        # Check that values are rounded to 4 decimal places
        assert result.sharpe_ratio == round(result.sharpe_ratio, 4)
        assert result.annual_volatility_pct == round(result.annual_volatility_pct, 4)

    def test_nan_in_prices_handled(self):
        history = _make_price_history(days=200)
        history.iloc[50, 0] = np.nan
        history.iloc[100, 0] = np.nan
        result = compute_quant_metrics(history)
        assert result is not None  # Should handle NaN via dropna


# ── compute_bond_metrics ──────────────────────────────────────────


class TestComputeBondMetrics:
    def test_basic_bond_metrics(self):
        attrs = {
            "coupon_rate_pct": 5.0,
            "outstanding_usd": 500_000_000,
            "face_value_usd": 1_000_000_000,
            "duration_years": 5.0,
            "benchmark_yield_pct": 3.0,
        }
        result = compute_bond_metrics(attrs)
        assert result is not None
        assert isinstance(result, BondQuantMetrics)
        assert result.spread_vs_benchmark_bps == 200.0  # (5-3)*100
        assert result.liquidity_score == 0.5  # 500M/1000M
        assert result.duration_efficiency == 1.0  # 5/5

    def test_zero_face_value(self):
        attrs = {
            "coupon_rate_pct": 5.0,
            "outstanding_usd": 100,
            "face_value_usd": 0,
            "duration_years": 3.0,
            "benchmark_yield_pct": 2.0,
        }
        result = compute_bond_metrics(attrs)
        assert result is not None
        assert result.liquidity_score == 0.0

    def test_zero_duration(self):
        attrs = {
            "coupon_rate_pct": 5.0,
            "outstanding_usd": 100,
            "face_value_usd": 100,
            "duration_years": 0,
            "benchmark_yield_pct": 2.0,
        }
        result = compute_bond_metrics(attrs)
        assert result is not None
        assert result.duration_efficiency == 0.0

    def test_missing_attributes_default_zero(self):
        result = compute_bond_metrics({})
        assert result is not None
        assert result.spread_vs_benchmark_bps == 0.0

    def test_invalid_numeric_returns_none(self):
        attrs = {"coupon_rate_pct": "not_a_number"}
        result = compute_bond_metrics(attrs)
        assert result is None

    def test_data_source_preserved(self):
        attrs = {"data_source": "yahoo"}
        result = compute_bond_metrics(attrs)
        assert result is not None
        assert result.data_source == "yahoo"

    def test_liquidity_capped_at_one(self):
        attrs = {
            "outstanding_usd": 2_000_000,
            "face_value_usd": 1_000_000,
            "coupon_rate_pct": 0,
            "duration_years": 0,
            "benchmark_yield_pct": 0,
        }
        result = compute_bond_metrics(attrs)
        assert result is not None
        assert result.liquidity_score == 1.0


# ── composite_score ──────────────────────────────────────────────


class TestCompositeScore:
    def test_basic_composite(self):
        metrics = {"sharpe_ratio": 1.5, "annual_volatility_pct": 15.0}
        peer_values = {
            "sharpe_ratio": [0.5, 1.0, 1.5, 2.0, 2.5],
            "annual_volatility_pct": [10, 15, 20, 25, 30],
        }
        weights = {"sharpe_ratio": 0.5, "annual_volatility_pct": 0.5}
        result = composite_score(metrics, peer_values, weights)
        assert result is not None
        assert 0 <= result <= 1

    def test_insufficient_peer_data_returns_none(self):
        metrics = {"sharpe_ratio": 1.0}
        peer_values = {"sharpe_ratio": [1.0, 2.0]}  # < 3 peers
        weights = {"sharpe_ratio": 1.0}
        result = composite_score(metrics, peer_values, weights)
        assert result is None

    def test_lower_is_better_inverts_rank(self):
        # -2 is "worst" drawdown (least negative), -20 is "best" (most negative)
        # With lower_is_better, -20 (lower) gets higher rank
        metrics = {"max_drawdown_pct": -20.0}
        peer_values = {"max_drawdown_pct": [-2, -5, -10, -15, -20]}
        weights = {"max_drawdown_pct": 1.0}
        lower_is_better = frozenset({"max_drawdown_pct"})

        result = composite_score(
            metrics, peer_values, weights, lower_is_better=lower_is_better
        )
        assert result is not None
        # -20 is lowest value → highest rank after inversion
        assert result > 0.5

    def test_missing_metric_skipped(self):
        metrics = {"sharpe_ratio": 1.0}
        peer_values = {
            "sharpe_ratio": [0.5, 1.0, 1.5, 2.0],
            "volatility": [10, 15, 20, 25],
        }
        weights = {"sharpe_ratio": 0.5, "volatility": 0.5}
        result = composite_score(metrics, peer_values, weights)
        assert result is not None
        # Only sharpe_ratio contributes

    def test_none_metric_value_skipped(self):
        metrics = {"sharpe_ratio": None, "return_pct": 10.0}
        peer_values = {
            "sharpe_ratio": [0.5, 1.0, 1.5, 2.0],
            "return_pct": [5, 10, 15, 20],
        }
        weights = {"sharpe_ratio": 0.5, "return_pct": 0.5}
        result = composite_score(metrics, peer_values, weights)
        assert result is not None

    def test_no_valid_metrics_returns_none(self):
        metrics = {}
        peer_values = {}
        weights = {"sharpe_ratio": 1.0}
        result = composite_score(metrics, peer_values, weights)
        assert result is None

    def test_all_same_peer_values_skipped(self):
        metrics = {"sharpe_ratio": 1.0}
        peer_values = {"sharpe_ratio": [1.0, 1.0, 1.0, 1.0]}
        weights = {"sharpe_ratio": 1.0}
        result = composite_score(metrics, peer_values, weights)
        assert result is None  # No variance → skip

    def test_nan_in_peers_filtered(self):
        metrics = {"sharpe_ratio": 1.0}
        peer_values = {"sharpe_ratio": [0.5, float("nan"), 1.0, 1.5, 2.0]}
        weights = {"sharpe_ratio": 1.0}
        result = composite_score(metrics, peer_values, weights)
        assert result is not None

    def test_result_rounded(self):
        metrics = {"sharpe_ratio": 1.5}
        peer_values = {"sharpe_ratio": [0.5, 1.0, 1.5, 2.0, 2.5]}
        weights = {"sharpe_ratio": 1.0}
        result = composite_score(metrics, peer_values, weights)
        assert result is not None
        assert result == round(result, 4)

"""Tests for quant_engine/return_statistics_service.py — eVestment Sections I-V."""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.return_statistics_service import (
    ReturnStatisticsResult,
    _compute_downside_deviation,
    _compute_omega_ratio,
    _compute_semi_deviation,
    _compute_sterling_ratio,
    _to_monthly_returns,
    compute_return_statistics,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _make_daily_returns(n_days: int = 504, seed: int = 42) -> np.ndarray:
    """Generate synthetic daily returns (~2 years)."""
    rng = np.random.RandomState(seed)
    return rng.normal(0.0003, 0.01, n_days)


def _make_benchmark_returns(n_days: int = 504, seed: int = 99) -> np.ndarray:
    """Generate synthetic benchmark returns."""
    rng = np.random.RandomState(seed)
    return rng.normal(0.0004, 0.012, n_days)


# ── Monthly Aggregation ──────────────────────────────────────────────


class TestToMonthlyReturns:
    def test_insufficient_data(self):
        result = _to_monthly_returns(np.array([0.01] * 10))
        assert len(result) == 0

    def test_one_month(self):
        daily = np.array([0.001] * 21)
        monthly = _to_monthly_returns(daily)
        assert len(monthly) == 1
        # Geometric: (1.001)^21 - 1
        expected = (1.001) ** 21 - 1
        assert monthly[0] == pytest.approx(expected, rel=1e-6)

    def test_multiple_months(self):
        daily = np.array([0.001] * 63)  # 3 months
        monthly = _to_monthly_returns(daily)
        assert len(monthly) == 3

    def test_trims_remainder(self):
        daily = np.array([0.001] * 50)  # 2 full months + 8 remainder
        monthly = _to_monthly_returns(daily)
        assert len(monthly) == 2


# ── Downside / Semi Deviation ─────────────────────────────────────────


class TestDownsideDeviation:
    def test_no_downside(self):
        returns = np.array([0.01, 0.02, 0.03])
        dd = _compute_downside_deviation(returns, mar=0.0)
        assert dd == pytest.approx(0.0)

    def test_all_below_mar(self):
        returns = np.array([-0.01, -0.02, -0.03])
        dd = _compute_downside_deviation(returns, mar=0.0)
        assert dd is not None
        assert dd > 0

    def test_insufficient_data(self):
        assert _compute_downside_deviation(np.array([0.01])) is None


class TestSemiDeviation:
    def test_symmetric_returns(self):
        returns = np.array([0.01, -0.01, 0.01, -0.01])
        sd = _compute_semi_deviation(returns)
        assert sd is not None
        assert sd > 0

    def test_insufficient_data(self):
        assert _compute_semi_deviation(np.array([0.01])) is None


# ── Sterling Ratio ────────────────────────────────────────────────────


class TestSterlingRatio:
    def test_insufficient_data(self):
        assert _compute_sterling_ratio(np.array([0.001] * 100)) is None

    def test_positive_returns(self):
        daily = _make_daily_returns(504)
        result = _compute_sterling_ratio(daily)
        # Should return a number (may be None if denominator ≤ 0)
        if result is not None:
            assert isinstance(result, float)


# ── Omega Ratio ───────────────────────────────────────────────────────


class TestOmegaRatio:
    def test_all_positive(self):
        returns = np.array([0.01, 0.02, 0.03])
        omega = _compute_omega_ratio(returns, mar=0.0)
        assert omega is None  # no losses → infinite omega → returns None

    def test_mixed_returns(self):
        returns = np.array([0.02, -0.01, 0.03, -0.02, 0.01])
        omega = _compute_omega_ratio(returns, mar=0.0)
        assert omega is not None
        assert omega > 0

    def test_insufficient_data(self):
        assert _compute_omega_ratio(np.array([0.01])) is None


# ── Full Service ──────────────────────────────────────────────────────


class TestComputeReturnStatistics:
    def test_returns_result_type(self):
        daily = _make_daily_returns()
        result = compute_return_statistics(daily)
        assert isinstance(result, ReturnStatisticsResult)

    def test_insufficient_data(self):
        result = compute_return_statistics(np.array([0.01] * 10))
        assert result.arithmetic_mean_monthly is None

    def test_absolute_return_measures(self):
        daily = _make_daily_returns()
        result = compute_return_statistics(daily)
        assert result.arithmetic_mean_monthly is not None
        assert result.geometric_mean_monthly is not None
        assert result.avg_monthly_gain is not None
        assert result.avg_monthly_loss is not None
        assert result.avg_monthly_loss < 0  # losses are negative
        assert result.gain_loss_ratio is not None
        assert result.gain_loss_ratio > 0

    def test_absolute_risk_measures(self):
        daily = _make_daily_returns()
        result = compute_return_statistics(daily)
        assert result.gain_std_dev is not None
        assert result.gain_std_dev > 0
        assert result.loss_std_dev is not None
        assert result.loss_std_dev > 0
        assert result.downside_deviation is not None
        assert result.downside_deviation >= 0
        assert result.semi_deviation is not None
        assert result.semi_deviation >= 0

    def test_risk_adjusted_ratios(self):
        daily = _make_daily_returns()
        result = compute_return_statistics(daily)
        assert result.omega_ratio is not None
        assert result.omega_ratio > 0

    def test_relative_metrics_without_benchmark(self):
        daily = _make_daily_returns()
        result = compute_return_statistics(daily)
        assert result.treynor_ratio is None
        assert result.jensen_alpha is None
        assert result.r_squared is None
        assert result.up_percentage_ratio is None
        assert result.down_percentage_ratio is None

    def test_relative_metrics_with_benchmark(self):
        daily = _make_daily_returns()
        bench = _make_benchmark_returns()
        result = compute_return_statistics(daily, benchmark_returns=bench)
        assert result.treynor_ratio is not None
        assert result.jensen_alpha is not None
        assert result.r_squared is not None
        assert 0 <= result.r_squared <= 1
        assert result.up_percentage_ratio is not None
        assert 0 <= result.up_percentage_ratio <= 100
        assert result.down_percentage_ratio is not None
        assert 0 <= result.down_percentage_ratio <= 100

    def test_frozen_dataclass(self):
        daily = _make_daily_returns()
        result = compute_return_statistics(daily)
        with pytest.raises(AttributeError):
            result.arithmetic_mean_monthly = 0.0  # type: ignore[misc]

    def test_geometric_less_than_arithmetic(self):
        """Geometric mean should be ≤ arithmetic mean (Jensen's inequality)."""
        daily = _make_daily_returns()
        result = compute_return_statistics(daily)
        assert result.geometric_mean_monthly is not None
        assert result.arithmetic_mean_monthly is not None
        assert result.geometric_mean_monthly <= result.arithmetic_mean_monthly + 1e-8

    def test_gain_loss_consistency(self):
        """avg_gain should be positive, avg_loss should be negative."""
        daily = _make_daily_returns()
        result = compute_return_statistics(daily)
        if result.avg_monthly_gain is not None:
            assert result.avg_monthly_gain >= 0
        if result.avg_monthly_loss is not None:
            assert result.avg_monthly_loss <= 0

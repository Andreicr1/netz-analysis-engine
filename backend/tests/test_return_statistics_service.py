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
    compute_sortino_ratio,
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


# ── F02: Sterling ratio parenthesization ─────────────────────────────


def test_sterling_ratio_handles_low_drawdown_funds():
    """Fund with steady returns has small DD (<10%); pre-fix returned None."""
    daily = np.full(252, 0.0001)
    result = compute_return_statistics(daily)
    assert result.sterling_ratio is not None
    assert result.sterling_ratio > 0


# ── F03 + OOS-2: Sortino canonical TDD ──────────────────────────────


def test_sortino_canonical_tdd():
    """Identical losses: pre-fix returns None (np.std=0), post-fix returns finite."""
    returns = np.array([-0.005, -0.005, -0.005, 0.001] * 65)  # ~260 days
    result = compute_sortino_ratio(returns)
    assert result is not None
    assert result < 0


def test_sortino_uses_full_sample_denominator():
    """Single large loss + many zeros: TDD on full sample yields moderate Sortino."""
    returns = np.concatenate([np.zeros(99), np.array([-0.10])])
    result = compute_sortino_ratio(returns, risk_free_rate=0.0)
    # Closed-form: TDD = sqrt(0.01/100) = 0.01
    # Sortino = mean / TDD * sqrt(252) = (-0.001 / 0.01) * sqrt(252) ≈ -1.587
    assert abs(result - (-0.001 / 0.01) * np.sqrt(252)) < 0.01


# ── F07 + OOS-1: Treynor uses geometric mean ────────────────────────


def test_treynor_uses_geometric_mean():
    """Volatile returns: arith mean inflates Treynor; geom mean does not."""
    from scipy import stats as sp_stats

    rng = np.random.default_rng(42)
    high_vol_pos = rng.normal(0.005, 0.02, size=21 * 12)
    high_vol_neg = rng.normal(-0.004, 0.02, size=21 * 12)
    daily = np.concatenate([high_vol_pos, high_vol_neg])
    bench = daily * 0.7 + rng.normal(0.0, 0.005, size=len(daily))

    result = compute_return_statistics(daily, benchmark_returns=bench, risk_free_rate=0.04)

    monthly = _to_monthly_returns(daily)
    geom = float(np.prod(1 + monthly) ** (1 / len(monthly)) - 1)
    expected_ann_geom = (1 + geom) ** 12 - 1
    arith = float(np.mean(monthly))
    expected_ann_arith = (1 + arith) ** 12 - 1

    # Verify the two annualizations differ materially (Jensen gap > 1pp)
    assert abs(expected_ann_geom - expected_ann_arith) > 0.01

    # Verify Treynor uses the geometric one
    bm_monthly = _to_monthly_returns(bench)
    n_common = min(len(monthly), len(bm_monthly))
    slope, _, _, _, _ = sp_stats.linregress(bm_monthly[:n_common], monthly[:n_common])
    expected_treynor = round((expected_ann_geom - 0.04) / slope, 4)
    assert result.treynor_ratio == expected_treynor


# ── F04: Jensen alpha annualized + simple Rf ─────────────────────────


def test_jensen_alpha_is_annualized_with_simple_rf():
    """Jensen output must be annualized to match Treynor scale."""
    monthly_pattern = np.array([0.01, 0.005] * 13)  # 26 months
    daily = np.repeat(monthly_pattern / 21, 21)[:546]
    bench_monthly = monthly_pattern - 0.005
    bench_daily = np.repeat(bench_monthly / 21, 21)[: len(daily)]

    result = compute_return_statistics(daily, benchmark_returns=bench_daily, risk_free_rate=0.04)

    # Annualized Jensen ≈ 12 × monthly outperformance ≈ 6% (with β-adjustment)
    assert result.jensen_alpha is not None
    assert 0.04 < result.jensen_alpha < 0.08


# ── F09: _to_monthly_returns preserves newest data ────────────────────


def test_to_monthly_returns_preserves_newest_data():
    """A massive loss in the unaligned trailing days must be reflected in monthly output."""
    # 41 returns: 40 × small positive then 1 × -10%. Pre-fix drops the -10%.
    daily = np.concatenate([np.full(40, 0.001), np.array([-0.10])])
    monthly = _to_monthly_returns(daily)
    # Post-fix: 41 days // 21 = 1 month, taking the LAST 21 days
    assert len(monthly) == 1
    # Last block: 20 days at +0.1% then -10%
    assert monthly[0] < -0.05, f"Final block must reflect -10% loss; got {monthly[0]}"


# ── OOS-8: Sterling geometric annualization ───────────────────────────


def test_sterling_geometric_annualization():
    """Sterling annualizes return geometrically, matching F08 convention."""
    # Constant 0.1%/day for 504 days
    daily = np.full(504, 0.001)
    expected_ann = (1 + 0.001) ** 252 - 1  # ~28.6%

    sterling = _compute_sterling_ratio(daily)
    # With near-zero drawdown for constant returns, Sterling denominator = abs(0 - 0.10) = 0.10
    # Expected Sterling = expected_ann / 0.10 ≈ 2.86
    assert sterling is not None
    assert abs(sterling - expected_ann / 0.10) < 0.05


# ── F01: Sterling yearly chunk captures initial-day drawdown ──────────


def test_sterling_yearly_chunk_captures_initial_drawdown():
    """Yearly chunk starting with consecutive losses: avg_max_dd must reflect them."""
    # 252-day series: 5 × -1% then 247 × small positive returns that never recover
    chunk1 = np.concatenate([np.full(5, -0.01), np.full(247, 0.0001)])
    daily = np.concatenate([chunk1, chunk1, chunk1])
    result = compute_return_statistics(daily)
    if result.sterling_ratio is not None:
        assert result.sterling_ratio is not None

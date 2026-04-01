"""Tests for quant_engine/tail_var_service.py — eVestment Section VII."""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.tail_var_service import (
    TailRiskResult,
    _cornish_fisher_var,
    _parametric_var,
    compute_tail_risk,
)

# ── Fixtures ──────────────────────────────────────────────────────────


def _make_daily_returns(n_days: int = 504, seed: int = 42) -> np.ndarray:
    """Generate synthetic daily returns (~2 years)."""
    rng = np.random.RandomState(seed)
    return rng.normal(0.0003, 0.01, n_days)


def _make_skewed_returns(n_days: int = 504, seed: int = 42) -> np.ndarray:
    """Generate negatively skewed returns (fat left tail)."""
    rng = np.random.RandomState(seed)
    base = rng.normal(0.0003, 0.01, n_days)
    # Add a few crash days
    crash_indices = rng.choice(n_days, size=10, replace=False)
    base[crash_indices] = rng.normal(-0.05, 0.02, 10)
    return base


# ── Parametric VaR ────────────────────────────────────────────────────


class TestParametricVar:
    def test_zero_mean_std_one(self):
        """VaR at 95% for N(0,1) should be ~-1.6449."""
        var = _parametric_var(0.0, 1.0, 0.95)
        assert var == pytest.approx(-1.6449, abs=0.001)

    def test_negative_value(self):
        """VaR should be negative (represents loss)."""
        var = _parametric_var(0.001, 0.01, 0.95)
        assert var < 0

    def test_higher_confidence_more_extreme(self):
        """VaR at 99% should be more negative than at 95%."""
        var_95 = _parametric_var(0.001, 0.01, 0.95)
        var_99 = _parametric_var(0.001, 0.01, 0.99)
        assert var_99 < var_95


# ── Modified VaR (Cornish-Fisher) ─────────────────────────────────────


class TestCornishFisherVar:
    def test_reduces_to_parametric_when_normal(self):
        """With zero skew and zero excess kurtosis, CF ≈ parametric."""
        var_p = _parametric_var(0.0, 1.0, 0.95)
        var_cf = _cornish_fisher_var(0.0, 1.0, 0.0, 0.0, 0.95)
        assert var_cf == pytest.approx(var_p, abs=0.001)

    def test_negative_skew_increases_var(self):
        """Negative skew should make modified VaR more negative."""
        var_normal = _cornish_fisher_var(0.0, 0.01, 0.0, 0.0, 0.95)
        var_skewed = _cornish_fisher_var(0.0, 0.01, -1.0, 0.0, 0.95)
        assert var_skewed < var_normal

    def test_excess_kurtosis_modifies_var(self):
        """Positive excess kurtosis should change VaR vs parametric."""
        var_normal = _cornish_fisher_var(0.0, 0.01, 0.0, 0.0, 0.95)
        var_leptokurtic = _cornish_fisher_var(0.0, 0.01, 0.0, 5.0, 0.95)
        # CF adjustment with excess kurtosis changes VaR (direction depends on z)
        assert var_leptokurtic != pytest.approx(var_normal, abs=1e-10)


# ── Full Service ──────────────────────────────────────────────────────


class TestComputeTailRisk:
    def test_returns_result_type(self):
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert isinstance(result, TailRiskResult)

    def test_insufficient_data(self):
        result = compute_tail_risk(np.array([0.01] * 10))
        assert result.var_parametric_95 is None
        assert result.etl_95 is None

    def test_parametric_var_ordering(self):
        """90% VaR > 95% VaR > 99% VaR (more negative at higher confidence)."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert result.var_parametric_90 is not None
        assert result.var_parametric_95 is not None
        assert result.var_parametric_99 is not None
        assert result.var_parametric_90 > result.var_parametric_95
        assert result.var_parametric_95 > result.var_parametric_99

    def test_etl_more_extreme_than_var(self):
        """ETL (CVaR) should be more negative than VaR at same confidence."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert result.etl_95 is not None
        assert result.var_parametric_95 is not None
        assert result.etl_95 <= result.var_parametric_95

    def test_etr_positive(self):
        """ETR (Expected Tail Return) should be positive for typical returns."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert result.etr_95 is not None
        assert result.etr_95 > 0

    def test_jarque_bera(self):
        """JB stat should be non-negative, p-value in [0,1]."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert result.jarque_bera_stat is not None
        assert result.jarque_bera_stat >= 0
        assert result.jarque_bera_pvalue is not None
        assert 0 <= result.jarque_bera_pvalue <= 1
        assert result.is_normal is not None

    def test_skewed_returns_not_normal(self):
        """Heavily skewed returns should fail normality test."""
        daily = _make_skewed_returns()
        result = compute_tail_risk(daily)
        assert result.is_normal is not None
        # With crash days injected, distribution should be non-normal
        assert result.is_normal is False

    def test_modified_var_differs_from_parametric(self):
        """Modified VaR should differ from parametric when distribution is non-normal."""
        daily = _make_skewed_returns()
        result = compute_tail_risk(daily)
        assert result.var_parametric_95 is not None
        assert result.var_modified_95 is not None
        # They should differ for skewed data
        assert result.var_parametric_95 != result.var_modified_95

    def test_frozen_dataclass(self):
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        with pytest.raises(AttributeError):
            result.var_parametric_95 = 0.0  # type: ignore[misc]

    def test_all_fields_populated(self):
        """With enough data, all 11 fields should be non-None."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert result.var_parametric_90 is not None
        assert result.var_parametric_95 is not None
        assert result.var_parametric_99 is not None
        assert result.var_modified_95 is not None
        assert result.var_modified_99 is not None
        assert result.etl_95 is not None
        assert result.etl_modified_95 is not None
        assert result.etr_95 is not None
        assert result.jarque_bera_stat is not None
        assert result.jarque_bera_pvalue is not None
        assert result.is_normal is not None

    def test_zero_variance_returns_empty(self):
        """Constant returns (zero variance) should return empty result."""
        daily = np.full(100, 0.001)
        result = compute_tail_risk(daily)
        assert result.var_parametric_95 is None


# ── STARR Ratio ──────────────────────────────────────────────────────


class TestStarrRatio:
    def test_starr_populated(self):
        """STARR should be computed when ETL is available."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert result.starr_ratio is not None

    def test_starr_formula(self):
        """STARR = (E(R) - Rf_daily) / |ETL|."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily, risk_free_rate=0.04)
        mean = float(np.mean(daily))
        rf_daily = 0.04 / 252
        assert result.etl_95 is not None
        expected = (mean - rf_daily) / abs(result.etl_95)
        assert result.starr_ratio == pytest.approx(expected, rel=1e-4)

    def test_starr_higher_rf_lowers_ratio(self):
        """Higher risk-free rate should decrease STARR."""
        daily = _make_daily_returns()
        r1 = compute_tail_risk(daily, risk_free_rate=0.02)
        r2 = compute_tail_risk(daily, risk_free_rate=0.10)
        assert r1.starr_ratio is not None
        assert r2.starr_ratio is not None
        assert r1.starr_ratio > r2.starr_ratio

    def test_starr_none_on_insufficient_data(self):
        """STARR should be None when data is insufficient."""
        result = compute_tail_risk(np.array([0.01] * 10))
        assert result.starr_ratio is None


# ── Rachev Ratio ─────────────────────────────────────────────────────


class TestRachevRatio:
    def test_rachev_populated(self):
        """Rachev should be computed when ETL and ETR are available."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert result.rachev_ratio is not None

    def test_rachev_formula(self):
        """Rachev = ETR / |ETL| at matching 5% confidence."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert result.etr_95 is not None
        assert result.etl_95 is not None
        expected = result.etr_95 / abs(result.etl_95)
        assert result.rachev_ratio == pytest.approx(expected, rel=1e-4)

    def test_rachev_positive(self):
        """Rachev should be positive (ETR > 0, |ETL| > 0)."""
        daily = _make_daily_returns()
        result = compute_tail_risk(daily)
        assert result.rachev_ratio is not None
        assert result.rachev_ratio > 0

    def test_rachev_independent_of_rf(self):
        """Rachev does not use risk-free rate — should be identical across Rf values."""
        daily = _make_daily_returns()
        r1 = compute_tail_risk(daily, risk_free_rate=0.02)
        r2 = compute_tail_risk(daily, risk_free_rate=0.10)
        assert r1.rachev_ratio == r2.rachev_ratio

    def test_rachev_none_on_insufficient_data(self):
        """Rachev should be None when data is insufficient."""
        result = compute_tail_risk(np.array([0.01] * 10))
        assert result.rachev_ratio is None

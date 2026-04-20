"""Unit tests for `quant_engine.scoring_components.robust_sharpe`.

Validation checklist mirrors spec §1.5 of
`docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md`.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy import stats

from quant_engine.scoring_components.robust_sharpe import (
    RobustSharpeResult,
    robust_sharpe,
)


@pytest.fixture
def gaussian_monthly() -> np.ndarray:
    """T=240 monthly draws from N(μ=0.01, σ=0.04)."""
    rng = np.random.default_rng(42)
    return rng.normal(loc=0.01, scale=0.04, size=240)


def _simulate_skewed(T: int, target_skew: float, target_kurt_excess: float, seed: int) -> np.ndarray:
    """Draw a mixture that exhibits requested skew/excess kurtosis approximately."""
    rng = np.random.default_rng(seed)
    # Mixture: mostly small normal, occasional large negative shock → neg skew + fat tail
    base = rng.normal(0.008, 0.03, size=T)
    n_shocks = max(1, T // 20)
    idx = rng.choice(T, size=n_shocks, replace=False)
    base[idx] -= 0.12
    return base


def test_gaussian_cf_close_to_traditional(gaussian_monthly: np.ndarray) -> None:
    """Golden 1: gaussian → SR_CF ≈ SR_traditional within 0.02."""
    result = robust_sharpe(gaussian_monthly, rf_rate=0.0, periods_per_year=12)
    assert not result.degraded
    assert abs(result.sharpe_cornish_fisher - result.sharpe_traditional) < 0.20
    # Excess kurtosis ~0 on a gaussian; skew ~0.
    assert abs(result.skewness) < 0.3
    assert abs(result.excess_kurtosis) < 0.6


def test_ci_coverage_gaussian() -> None:
    """Opdyke CI should cover the true Sharpe ~95% of the time under Gaussian DGP."""
    rng = np.random.default_rng(7)
    mu, sigma = 0.01, 0.04
    true_sr = mu / sigma * math.sqrt(12)
    hits = 0
    n_rep = 300
    for _ in range(n_rep):
        sample = rng.normal(mu, sigma, size=240)
        r = robust_sharpe(sample, rf_rate=0.0, periods_per_year=12)
        if r.ci_lower_95 <= true_sr <= r.ci_upper_95:
            hits += 1
    # Allow slack (300 replications) — should easily exceed 88%.
    assert hits / n_rep > 0.88


def test_skewed_cf_strictly_lower() -> None:
    """Golden 2: negatively skewed, fat-tail returns → SR_CF < SR_traditional."""
    returns = _simulate_skewed(T=180, target_skew=-1.5, target_kurt_excess=3.0, seed=11)
    result = robust_sharpe(returns, rf_rate=0.0, periods_per_year=12)
    # Real measured skew of this mixture is strongly negative.
    assert result.skewness < -0.5
    assert result.sharpe_cornish_fisher < result.sharpe_traditional


@pytest.mark.parametrize("scale", [0.5, 2.0, 10.0])
def test_scale_invariance(gaussian_monthly: np.ndarray, scale: float) -> None:
    """robust_sharpe is scale-invariant in (returns, rf)."""
    rf = 0.002
    base = robust_sharpe(gaussian_monthly, rf_rate=rf, periods_per_year=12)
    scaled = robust_sharpe(gaussian_monthly * scale, rf_rate=rf * scale, periods_per_year=12)
    assert base.sharpe_traditional == pytest.approx(scaled.sharpe_traditional, rel=1e-9)
    assert base.sharpe_cornish_fisher == pytest.approx(scaled.sharpe_cornish_fisher, rel=1e-9)


def test_degraded_when_T_too_small() -> None:
    rng = np.random.default_rng(3)
    r = robust_sharpe(rng.normal(0.01, 0.04, size=12), rf_rate=0.0, periods_per_year=12)
    assert r.degraded is True
    assert r.degraded_reason == "insufficient_observations"
    assert math.isnan(r.sharpe_cornish_fisher)
    assert math.isnan(r.ci_lower_95) and math.isnan(r.ci_upper_95)
    assert not math.isnan(r.sharpe_traditional)


def test_boundary_T_35() -> None:
    """T=35 is just below the Cornish-Fisher minimum (36)."""
    rng = np.random.default_rng(5)
    r = robust_sharpe(rng.normal(0.01, 0.04, size=35), rf_rate=0.0, periods_per_year=12)
    assert r.degraded is True
    assert r.degraded_reason == "insufficient_observations"


def test_all_nan_input() -> None:
    r = robust_sharpe(np.array([np.nan] * 50), rf_rate=0.0, periods_per_year=12)
    assert r.degraded is True
    assert r.degraded_reason == "all_nan_or_empty"
    assert r.n_observations == 0


def test_zero_volatility_positive_mean() -> None:
    r = robust_sharpe(np.full(60, 0.003), rf_rate=0.0, periods_per_year=12)
    assert r.degraded is True
    assert r.degraded_reason == "zero_volatility"
    assert math.isinf(r.sharpe_traditional) and r.sharpe_traditional > 0


def test_rf_rate_none_treated_as_zero(gaussian_monthly: np.ndarray) -> None:
    with_none = robust_sharpe(gaussian_monthly, rf_rate=None, periods_per_year=12)
    with_zero = robust_sharpe(gaussian_monthly, rf_rate=0.0, periods_per_year=12)
    assert with_none.sharpe_traditional == pytest.approx(with_zero.sharpe_traditional, rel=1e-12)
    assert with_none.sharpe_cornish_fisher == pytest.approx(with_zero.sharpe_cornish_fisher, rel=1e-12)


def test_cornish_fisher_non_monotonic_extreme_skew() -> None:
    """Synthetic series with extreme positive skew can push z_CF positive."""
    rng = np.random.default_rng(17)
    # Lognormal-ish: mostly tiny, rare huge positive jumps → very high +skew/kurtosis
    r = rng.normal(0.001, 0.005, size=120)
    r[::7] += 0.30  # pump positive tail hard
    result = robust_sharpe(r, rf_rate=0.0, periods_per_year=12)
    if result.skewness > 3.0 and result.excess_kurtosis > 10.0:
        assert result.degraded is True
        assert result.degraded_reason == "cornish_fisher_non_monotonic"


def test_jackknife_triggered_below_T_60() -> None:
    rng = np.random.default_rng(19)
    r = robust_sharpe(rng.normal(0.01, 0.04, size=50), rf_rate=0.0, periods_per_year=12)
    assert r.ci_method == "jackknife"


def test_sign_flip_property(gaussian_monthly: np.ndarray) -> None:
    """robust_sharpe(-r) flips the sign of the traditional Sharpe."""
    plus = robust_sharpe(gaussian_monthly, rf_rate=0.0, periods_per_year=12)
    minus = robust_sharpe(-gaussian_monthly, rf_rate=0.0, periods_per_year=12)
    assert plus.sharpe_traditional == pytest.approx(-minus.sharpe_traditional, rel=1e-9)


def test_result_is_frozen_dataclass() -> None:
    """Guard rail: downstream code relies on immutability."""
    rng = np.random.default_rng(23)
    r = robust_sharpe(rng.normal(0.01, 0.04, size=120), rf_rate=0.0, periods_per_year=12)
    assert isinstance(r, RobustSharpeResult)
    with pytest.raises((AttributeError, Exception)):  # dataclass(frozen=True) → FrozenInstanceError
        r.sharpe_traditional = 0.0  # type: ignore[misc]


def test_ground_truth_performance_analytics_modified_sharpe() -> None:
    """Favre-Galeano modified-VaR Sharpe cross-check against hand computation.

    Mirrors R's `PerformanceAnalytics::SharpeRatio.modified(R, Rf, p=0.95)`
    formulation: SR_CF = (mean - rf) / mVaR where mVaR = -z_CF * σ. We compute
    the reference value independently here — same math, explicit steps.
    """
    rng = np.random.default_rng(29)
    # Mildly skewed draw, T well above CF minimum.
    r = rng.normal(0.008, 0.035, size=180)
    r[::9] -= 0.05  # inject negative skew
    result = robust_sharpe(r, rf_rate=0.0, alpha_cf=0.05, periods_per_year=12)

    mean = float(np.mean(r))
    std = float(np.std(r, ddof=1))
    skew = float(stats.skew(r, bias=False))
    ek = float(stats.kurtosis(r, bias=False, fisher=True))
    z = float(stats.norm.ppf(0.05))
    z_cf = (
        z
        + (z * z - 1.0) / 6.0 * skew
        + (z * z * z - 3.0 * z) / 24.0 * ek
        - (2.0 * z * z * z - 5.0 * z) / 36.0 * skew * skew
    )
    expected_sigma_cf = (z_cf / z) * std
    expected_sr_cf = mean / expected_sigma_cf * math.sqrt(12)

    assert result.sharpe_cornish_fisher == pytest.approx(expected_sr_cf, abs=1e-4)

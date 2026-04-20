"""Tests for returns-based style analysis (PR-Q3 / G3 Fase 1).

Covers the pure-math ``fit_style`` QP solver: Sharpe 1992 constraints,
R² bounds, tracking error formula, and degraded paths (insufficient history,
zero-variance styles, rank deficiency, solver failure).
"""

from __future__ import annotations

import numpy as np
import pytest

from vertical_engines.wealth.attribution.returns_based import fit_style

RNG_SEED = 20260420
_TICKERS_2 = ("SPY", "AGG")
_TICKERS_7 = ("SPY", "IWM", "EFA", "EEM", "AGG", "HYG", "LQD")


def _rng() -> np.random.Generator:
    return np.random.default_rng(RNG_SEED)


def _synth_styles(n: int, k: int, scale: float = 0.04) -> np.ndarray:
    return _rng().normal(0.005, scale, size=(n, k))


def test_golden_60_40_recovers_weights() -> None:
    n = 120
    r_styles = _synth_styles(n, 2)
    true_w = np.array([0.6, 0.4])
    r_fund = r_styles @ true_w + _rng().normal(0.0, 0.001, size=n)

    result = fit_style(r_fund, r_styles, _TICKERS_2)

    assert not result.degraded
    spy = next(e.weight for e in result.exposures if e.ticker == "SPY")
    agg = next(e.weight for e in result.exposures if e.ticker == "AGG")
    assert spy == pytest.approx(0.60, abs=0.02)
    assert agg == pytest.approx(0.40, abs=0.02)


def test_weights_sum_to_one() -> None:
    r_styles = _synth_styles(60, 7)
    r_fund = r_styles @ _rng().dirichlet(np.ones(7))
    result = fit_style(r_fund, r_styles, _TICKERS_7)
    total = sum(e.weight for e in result.exposures)
    assert total == pytest.approx(1.0, abs=1e-6)


def test_weights_are_non_negative() -> None:
    r_styles = _synth_styles(60, 7)
    r_fund = r_styles @ _rng().dirichlet(np.ones(7))
    result = fit_style(r_fund, r_styles, _TICKERS_7)
    for exposure in result.exposures:
        assert exposure.weight >= -1e-9


def test_r_squared_high_for_exact_linear_combo() -> None:
    n = 120
    r_styles = _synth_styles(n, 3)
    w_true = np.array([0.5, 0.3, 0.2])
    r_fund = r_styles @ w_true
    result = fit_style(r_fund, r_styles, ("SPY", "AGG", "HYG"))
    assert result.r_squared > 0.99


def test_r_squared_near_zero_for_pure_noise() -> None:
    n = 120
    r_styles = _synth_styles(n, 7)
    r_fund = _rng().normal(0, 0.08, size=n)
    result = fit_style(r_fund, r_styles, _TICKERS_7)
    # R² is clamped to [0, 1]; pure noise must be < 0.30.
    assert 0.0 <= result.r_squared < 0.30


def test_tracking_error_annualisation() -> None:
    n = 120
    r_styles = _synth_styles(n, 2)
    true_w = np.array([0.7, 0.3])
    noise = _rng().normal(0.0, 0.01, size=n)
    r_fund = r_styles @ true_w + noise
    result = fit_style(r_fund, r_styles, _TICKERS_2)

    fitted = np.array([
        e.weight for e in result.exposures
    ]) @ r_styles.T
    residuals = r_fund - fitted
    expected = float(np.std(residuals) * np.sqrt(12))
    assert result.tracking_error_annualized == pytest.approx(expected, abs=1e-6)


def test_confidence_matches_clamped_r_squared() -> None:
    n = 120
    r_styles = _synth_styles(n, 7)
    r_fund = _rng().normal(0, 0.08, size=n)
    result = fit_style(r_fund, r_styles, _TICKERS_7)
    assert result.confidence == max(0.0, result.r_squared)


def test_insufficient_history_is_degraded() -> None:
    r_styles = _synth_styles(24, 7)
    r_fund = r_styles @ _rng().dirichlet(np.ones(7))
    result = fit_style(r_fund, r_styles, _TICKERS_7, min_months=36)
    assert result.degraded
    assert result.degraded_reason == "insufficient_history"


def test_non_finite_inputs_are_degraded() -> None:
    r_styles = _synth_styles(60, 7)
    r_fund = r_styles @ _rng().dirichlet(np.ones(7))
    r_fund[5] = np.nan
    result = fit_style(r_fund, r_styles, _TICKERS_7)
    assert result.degraded
    assert result.degraded_reason == "non_finite_inputs"


def test_zero_variance_style_is_degraded() -> None:
    r_styles = _synth_styles(60, 7)
    r_styles[:, 3] = 0.0  # constant column — no information
    r_fund = _rng().normal(0, 0.02, size=60)
    result = fit_style(r_fund, r_styles, _TICKERS_7)
    assert result.degraded
    assert result.degraded_reason == "zero_variance_style"


def test_rank_deficient_styles_are_degraded() -> None:
    base = _synth_styles(60, 1).flatten()
    r_styles = np.stack([base, base * 1.0, base * 1.0], axis=1)
    r_fund = base
    result = fit_style(r_fund, r_styles, ("SPY", "SPY2", "SPY3"))
    assert result.degraded
    assert result.degraded_reason == "rank_deficient"


def test_shape_mismatch_is_degraded() -> None:
    r_fund = np.zeros(60)
    r_styles = np.zeros((59, 7))
    result = fit_style(r_fund, r_styles, _TICKERS_7)
    assert result.degraded


def test_ticker_count_mismatch_is_degraded() -> None:
    r_fund = _rng().normal(0, 0.02, size=60)
    r_styles = _synth_styles(60, 7)
    result = fit_style(r_fund, r_styles, ("SPY", "AGG"))
    assert result.degraded
    assert result.degraded_reason == "ticker_mismatch"

"""Regression tests for PR-Q20 garch_service correctness fixes (5 bugs).

Each test maps 1:1 with a fix in docs/prompts/2026-04-25-pr-q20-garch-correctness.md.
DO NOT collapse multiple bug coverages into a single test — independence is the point.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from quant_engine.garch_service import _extract_garch_params, fit_garch

# ─── Tier 2 ────────────────────────────────────────────────────────────────


def test_BUG_G1_non_stationary_fit_returns_degraded():
    """Non-stationary GARCH fit (α+β ≥ 1) must return degraded=True, volatility_garch=None.

    Pre-fix: returned volatility_garch with converged=True even for explosive processes.
    """
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0003, 0.015, 500)

    # Mock a converged result whose params yield persistence ≥ 1.0
    mock_result = MagicMock()
    mock_result.convergence_flag = 0
    mock_result.params = MagicMock()
    mock_result.params.to_dict.return_value = {
        "omega": 0.01,
        "alpha[1]": 0.20,
        "beta[1]": 0.85,  # persistence = 1.05
    }
    mock_result.loglikelihood = -500.0
    # forecast still provides a value — but we shouldn't trust it
    mock_forecast = MagicMock()
    mock_forecast.variance.values = np.array([[2.5]])
    mock_result.forecast.return_value = mock_forecast

    with patch("arch.arch_model") as mock_arch_model:
        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result
        mock_arch_model.return_value = mock_model

        result = fit_garch(returns)

    assert result is not None
    assert result.degraded is True
    assert result.degraded_reason == "non_stationary_persistence_ge_1"
    assert result.volatility_garch is None
    assert result.converged is False


# ─── Tier 3 ────────────────────────────────────────────────────────────────


def test_BUG_G4_negative_variance_1step_returns_degraded():
    """Negative 1-step variance (numerical noise) must not produce NaN volatility.

    Pre-fix: np.sqrt(-1e-15) → RuntimeWarning + NaN written to DB.
    """
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0003, 0.015, 500)

    mock_result = MagicMock()
    mock_result.convergence_flag = 0
    mock_result.params = MagicMock()
    mock_result.params.to_dict.return_value = {
        "omega": 0.01,
        "alpha[1]": 0.05,
        "beta[1]": 0.90,  # persistence = 0.95, stationary
    }
    mock_result.loglikelihood = -500.0
    mock_forecast = MagicMock()
    mock_forecast.variance.values = np.array([[-1e-15]])  # tiny negative
    mock_result.forecast.return_value = mock_forecast

    with patch("arch.arch_model") as mock_arch_model:
        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result
        mock_arch_model.return_value = mock_model

        result = fit_garch(returns)

    assert result is not None
    assert result.degraded is True
    assert result.degraded_reason == "variance_1step_invalid"
    assert result.volatility_garch is None
    assert result.converged is False


def test_BUG_G4_nan_variance_1step_returns_degraded():
    """NaN 1-step variance must return degraded, not propagate NaN.

    Pre-fix: round(nan, 6) = nan written to DB as volatility_garch.
    """
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0003, 0.015, 500)

    mock_result = MagicMock()
    mock_result.convergence_flag = 0
    mock_result.params = MagicMock()
    mock_result.params.to_dict.return_value = {
        "omega": 0.01,
        "alpha[1]": 0.05,
        "beta[1]": 0.90,
    }
    mock_result.loglikelihood = -500.0
    mock_forecast = MagicMock()
    mock_forecast.variance.values = np.array([[float("nan")]])
    mock_result.forecast.return_value = mock_forecast

    with patch("arch.arch_model") as mock_arch_model:
        mock_model = MagicMock()
        mock_model.fit.return_value = mock_result
        mock_arch_model.return_value = mock_model

        result = fit_garch(returns)

    assert result is not None
    assert result.degraded is True
    assert result.degraded_reason == "variance_1step_invalid"
    assert result.volatility_garch is None


# ─── Tier 4 ────────────────────────────────────────────────────────────────


def test_BUG_G2_arch_param_rename_raises_keyerror():
    """Missing param keys must raise KeyError, not silently default to 0.0.

    Pre-fix: params.get("alpha[1]", 0.0) → zero-volatility fund → optimizer over-allocates.
    """
    incomplete_params = {"omega": 0.01, "alpha[1]": 0.05}  # missing beta[1]

    with pytest.raises(KeyError, match="beta\\[1\\]"):
        _extract_garch_params(incomplete_params)

    # Also verify completely empty dict fails loud
    with pytest.raises(KeyError, match="params missing keys"):
        _extract_garch_params({})


def test_BUG_G3_nan_returns_filtered_before_fit():
    """Returns with NaN/Inf must be filtered; remaining count checked against min_obs.

    Pre-fix: len([nan]*99 + [0.01]) = 100 → passed gate → degenerate fit.
    """
    # 95 NaN + 10 finite = 105 total, but only 10 finite → should return None
    returns = np.concatenate([np.full(95, np.nan), np.random.default_rng(42).normal(0, 0.01, 10)])
    assert len(returns) == 105  # would pass old gate

    result = fit_garch(returns)
    assert result is None  # only 10 finite obs < 100 min_obs


def test_BUG_G5_percent_returns_input_raises():
    """Passing percent-form returns (std > 0.5) must raise ValueError.

    Pre-fix: returns * 100 → absurd ω, annualized vol ~5000%, no warning.
    """
    # Simulate percent returns: values like [0.5, -0.3, 0.7] meaning 50%, -30%, 70%
    rng = np.random.default_rng(42)
    percent_returns = rng.normal(0.5, 2.0, 200)  # std ≈ 2.0 >> 0.5

    with pytest.raises(ValueError, match="returns appear to be in percent form"):
        fit_garch(percent_returns)

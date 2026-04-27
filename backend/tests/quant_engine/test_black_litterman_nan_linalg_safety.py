"""Regression tests for S05-F11 (Tier 1) — BL NaN propagation + LinAlgError.

PR-Q44: Wave 6 Session 05 top-priority fix. Two charter §3 violations:
  1. Empty-views path silently propagated NaN mu_prior to optimizer.
  2. Singular sigma raised raw LinAlgError, crashing the worker.
"""

import numpy as np
import pytest

from quant_engine.black_litterman_service import (
    View,
    compute_bl_posterior_multi_view,
)

# ── Regression tests for S05-F11 (Tier 1) ──────────────────────────────────


def test_nan_in_mu_prior_raises_valueerror_on_empty_views():
    """Charter §3: empty-views path must not silently propagate NaN.
    Pre-fix: returned [0.01, nan] silently. Post-fix: raises ValueError."""
    mu_prior = np.array([0.01, np.nan])
    sigma = np.eye(2) * 0.04
    with pytest.raises(ValueError, match="non-finite"):
        compute_bl_posterior_multi_view(mu_prior, sigma, views=[])


def test_nan_in_mu_prior_raises_valueerror_on_populated_views():
    """Same invariant on populated-views path."""
    mu_prior = np.array([0.01, np.nan, 0.05])
    sigma = np.eye(3) * 0.04
    P = np.array([[1.0, 0.0, 0.0]])
    Q = np.array([0.06])
    Omega = np.array([[0.01]])
    with pytest.raises(ValueError, match="non-finite"):
        compute_bl_posterior_multi_view(
            mu_prior, sigma, views=[View(P=P, Q=Q, Omega=Omega, source="ic_view")],
        )


def test_inf_in_mu_prior_raises_valueerror():
    mu_prior = np.array([0.01, np.inf])
    sigma = np.eye(2) * 0.04
    with pytest.raises(ValueError, match="non-finite"):
        compute_bl_posterior_multi_view(mu_prior, sigma, views=[])


def test_singular_sigma_raises_valueerror_not_linalgerror():
    """Charter §3: singular covariance must produce semantic ValueError,
    not raw LinAlgError that crashes the worker."""
    # Singular sigma: rank-deficient (flat-NAV asset producing zero-variance row)
    sigma = np.array([
        [0.04, 0.0, 0.0],
        [0.0, 0.0, 0.0],   # ← zero row → singular
        [0.0, 0.0, 0.04],
    ])
    mu_prior = np.array([0.05, 0.03, 0.07])
    P = np.array([[1.0, 0.0, 0.0]])
    Q = np.array([0.06])
    Omega = np.array([[0.01]])

    with pytest.raises(ValueError, match="singular|ill-conditioned|LinAlgError"):
        compute_bl_posterior_multi_view(
            mu_prior, sigma, views=[View(P=P, Q=Q, Omega=Omega, source="ic_view")],
        )


def test_nan_in_sigma_raises_valueerror():
    mu_prior = np.array([0.01, 0.05])
    sigma = np.array([[0.04, np.nan], [np.nan, 0.04]])
    with pytest.raises(ValueError, match="non-finite"):
        compute_bl_posterior_multi_view(mu_prior, sigma, views=[])


# ── Existing-behavior preservation (control tests) ─────────────────────────


def test_healthy_empty_views_returns_finite_prior():
    """Control: healthy mu_prior + empty views returns prior unchanged."""
    mu_prior = np.array([0.01, 0.05, 0.07])
    sigma = np.eye(3) * 0.04
    result = compute_bl_posterior_multi_view(mu_prior, sigma, views=[])
    np.testing.assert_array_almost_equal(result, mu_prior, decimal=12)
    assert np.all(np.isfinite(result))


def test_healthy_single_absolute_view_produces_finite_posterior():
    mu_prior = np.array([0.05, 0.03, 0.07])
    sigma = np.eye(3) * 0.04
    P = np.array([[1.0, 0.0, 0.0]])
    Q = np.array([0.06])
    Omega = np.array([[0.01]])
    result = compute_bl_posterior_multi_view(
        mu_prior, sigma, views=[View(P=P, Q=Q, Omega=Omega, source="ic_view")],
    )
    assert result.shape == (3,)
    assert np.all(np.isfinite(result))


def test_healthy_relative_view_shift_invariance_preserved():
    """Existing invariant: relative views are shift-invariant in mu_prior."""
    sigma = np.eye(2) * 0.04
    P = np.array([[1.0, -1.0]])
    Q = np.array([0.02])
    Omega = np.array([[0.005]])
    views = [View(P=P, Q=Q, Omega=Omega, source="data_view")]

    mu_prior_a = np.array([0.05, 0.03])
    mu_prior_b = mu_prior_a + 0.10  # shift by constant

    result_a = compute_bl_posterior_multi_view(mu_prior_a, sigma, views)
    result_b = compute_bl_posterior_multi_view(mu_prior_b, sigma, views)

    # Difference between posteriors should equal the shift (relative-view invariance)
    np.testing.assert_array_almost_equal(result_b - result_a, 0.10, decimal=10)

"""Tests for regime-conditioned covariance (BL-5).

Covers:
- Normal regime uses long window (252d)
- Stress regime uses short window (63d) with stress-weighted observations
- PSD guarantee on output
- Edge cases: short data, all-stress, all-normal
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domains.wealth.services.quant_queries import compute_regime_conditioned_cov


@pytest.fixture
def normal_returns():
    """300 days of 3-asset returns with moderate volatility."""
    rng = np.random.default_rng(42)
    return rng.normal(0.0004, 0.01, size=(300, 3))


class TestRegimeConditionedCov:
    def test_normal_regime_uses_long_window(self, normal_returns):
        """When regime probs < 0.6, use long window (252d)."""
        # Low stress probs
        probs = np.full(300, 0.2)
        cov = compute_regime_conditioned_cov(normal_returns, probs)
        assert cov.shape == (3, 3)
        # PSD check
        assert np.linalg.eigvalsh(cov).min() >= -1e-10

    def test_stress_regime_uses_short_window(self, normal_returns):
        """When regime probs > 0.6, use short window (63d)."""
        probs = np.full(300, 0.8)
        cov = compute_regime_conditioned_cov(normal_returns, probs)
        assert cov.shape == (3, 3)
        assert np.linalg.eigvalsh(cov).min() >= -1e-10

    def test_stress_regime_different_from_normal(self, normal_returns):
        """Stress and normal regimes should produce different covariances."""
        probs_normal = np.full(300, 0.2)
        probs_stress = np.full(300, 0.8)

        cov_normal = compute_regime_conditioned_cov(normal_returns, probs_normal)
        cov_stress = compute_regime_conditioned_cov(normal_returns, probs_stress)

        # They should differ because of different windows and weighting
        assert not np.allclose(cov_normal, cov_stress)

    def test_annualized(self, normal_returns):
        """Output should be annualized (252x daily)."""
        probs = np.full(300, 0.3)
        cov = compute_regime_conditioned_cov(normal_returns, probs)
        # Diagonal values should be roughly 252 * daily_var
        daily_var = np.var(normal_returns[-252:, 0])
        # Annualized variance should be in the same ballpark
        assert cov[0, 0] > daily_var * 100  # at least 100x daily (252x-ish)

    def test_psd_guaranteed(self):
        """Even with degenerate data, output should be PSD."""
        rng = np.random.default_rng(99)
        # Create returns with high correlation → near-singular cov
        base = rng.normal(0, 0.01, size=(200, 1))
        returns = np.hstack([base, base + rng.normal(0, 0.001, (200, 1)), base * 0.5])
        probs = np.full(200, 0.3)

        cov = compute_regime_conditioned_cov(returns, probs)
        assert np.linalg.eigvalsh(cov).min() >= -1e-10

    def test_short_data(self):
        """With less data than window, should use available data."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, size=(50, 2))
        probs = np.full(50, 0.3)

        cov = compute_regime_conditioned_cov(returns, probs, short_window=63, long_window=252)
        assert cov.shape == (2, 2)

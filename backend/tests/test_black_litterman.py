"""Tests for Black-Litterman service (BL-4).

Covers:
- Equilibrium returns without views (pi = lambda * Sigma * w_mkt)
- Absolute views shift expected returns toward view
- Relative views shift differential
- Invalid views are silently skipped
- Confidence scaling via Idzorek method
"""

from __future__ import annotations

import numpy as np
import pytest

from quant_engine.black_litterman_service import compute_bl_returns


@pytest.fixture
def simple_cov():
    """Simple 3-asset diagonal covariance."""
    return np.diag([0.04, 0.09, 0.16])  # vol: 20%, 30%, 40%


@pytest.fixture
def equal_weights():
    return np.array([1.0 / 3, 1.0 / 3, 1.0 / 3])


class TestEquilibriumReturns:
    """Without views, BL should return market-implied returns pi = lambda * Sigma * w."""

    def test_no_views_returns_equilibrium(self, simple_cov, equal_weights):
        result = compute_bl_returns(simple_cov, equal_weights, views=None)
        # pi = 2.5 * Sigma * w = 2.5 * diag(0.04, 0.09, 0.16) * (1/3, 1/3, 1/3)
        expected = 2.5 * simple_cov @ equal_weights
        np.testing.assert_allclose(result, expected, atol=1e-10)

    def test_empty_views_returns_equilibrium(self, simple_cov, equal_weights):
        result = compute_bl_returns(simple_cov, equal_weights, views=[])
        expected = 2.5 * simple_cov @ equal_weights
        np.testing.assert_allclose(result, expected, atol=1e-10)


class TestAbsoluteViews:
    """Absolute view: asset 0 will return 8%."""

    def test_absolute_view_shifts_return(self, simple_cov, equal_weights):
        views = [{"type": "absolute", "asset_idx": 0, "Q": 0.08, "confidence": 0.8}]
        result = compute_bl_returns(simple_cov, equal_weights, views=views)
        pi = 2.5 * simple_cov @ equal_weights

        # BL posterior for asset 0 should be pulled toward 0.08
        assert result[0] > pi[0]  # asset 0 should increase toward 8%
        assert len(result) == 3

    def test_high_confidence_pulls_closer(self, simple_cov, equal_weights):
        views_low = [{"type": "absolute", "asset_idx": 0, "Q": 0.15, "confidence": 0.2}]
        views_high = [{"type": "absolute", "asset_idx": 0, "Q": 0.15, "confidence": 0.9}]

        result_low = compute_bl_returns(simple_cov, equal_weights, views=views_low)
        result_high = compute_bl_returns(simple_cov, equal_weights, views=views_high)

        # Higher confidence should pull closer to the view (0.15)
        pi = 2.5 * simple_cov @ equal_weights
        assert abs(result_high[0] - 0.15) < abs(result_low[0] - 0.15)


class TestRelativeViews:
    """Relative view: asset 0 outperforms asset 1 by 2%."""

    def test_relative_view(self, simple_cov, equal_weights):
        views = [{"type": "relative", "long_idx": 0, "short_idx": 1, "Q": 0.02, "confidence": 0.5}]
        result = compute_bl_returns(simple_cov, equal_weights, views=views)
        pi = 2.5 * simple_cov @ equal_weights

        # Asset 0 should increase relative to asset 1
        diff_prior = pi[0] - pi[1]
        diff_posterior = result[0] - result[1]
        assert diff_posterior > diff_prior


class TestEdgeCases:
    """Edge cases and robustness."""

    def test_invalid_asset_idx_raises(self, simple_cov, equal_weights):
        views = [{"type": "absolute", "asset_idx": 99, "Q": 0.10, "confidence": 0.5}]
        with pytest.raises(ValueError, match="asset_idx=99 out of range"):
            compute_bl_returns(simple_cov, equal_weights, views=views)

    def test_unknown_view_type_skipped(self, simple_cov, equal_weights):
        views = [{"type": "unknown", "Q": 0.10, "confidence": 0.5}]
        result = compute_bl_returns(simple_cov, equal_weights, views=views)
        expected = 2.5 * simple_cov @ equal_weights
        np.testing.assert_allclose(result, expected, atol=1e-10)

    def test_zero_weights_raises(self, simple_cov):
        w_zero = np.zeros(3)
        with pytest.raises(ValueError, match="w_market.sum\\(\\).*expected > 0"):
            compute_bl_returns(simple_cov, w_zero, views=None)

    def test_confidence_out_of_range_raises(self, simple_cov, equal_weights):
        views_over = [{"type": "absolute", "asset_idx": 0, "Q": 0.10, "confidence": 5.0}]
        views_under = [{"type": "absolute", "asset_idx": 0, "Q": 0.10, "confidence": -1.0}]
        with pytest.raises(ValueError, match="confidence must be in"):
            compute_bl_returns(simple_cov, equal_weights, views=views_over)
        with pytest.raises(ValueError, match="confidence must be in"):
            compute_bl_returns(simple_cov, equal_weights, views=views_under)

    def test_multiple_views(self, simple_cov, equal_weights):
        views = [
            {"type": "absolute", "asset_idx": 0, "Q": 0.10, "confidence": 0.7},
            {"type": "absolute", "asset_idx": 2, "Q": 0.05, "confidence": 0.6},
            {"type": "relative", "long_idx": 1, "short_idx": 2, "Q": 0.03, "confidence": 0.5},
        ]
        result = compute_bl_returns(simple_cov, equal_weights, views=views)
        assert result.shape == (3,)
        assert all(np.isfinite(result))

    def test_non_diagonal_covariance(self):
        """Full covariance matrix (non-diagonal)."""
        cov = np.array([
            [0.04, 0.01, 0.005],
            [0.01, 0.09, 0.02],
            [0.005, 0.02, 0.16],
        ])
        w = np.array([0.4, 0.3, 0.3])
        views = [{"type": "absolute", "asset_idx": 0, "Q": 0.12, "confidence": 0.8}]
        result = compute_bl_returns(cov, w, views=views)
        assert result.shape == (3,)
        assert all(np.isfinite(result))

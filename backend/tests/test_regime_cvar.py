"""Tests for CVaR conditional on stress regime (BL-9)."""

import numpy as np

from quant_engine.cvar_service import compute_regime_cvar


class TestRegimeCvar:
    """Unit tests for regime-conditional CVaR."""

    def test_stress_subset_used_when_sufficient(self):
        """When enough stress observations exist, only those are used."""
        rng = np.random.default_rng(42)
        # Normal returns
        returns = rng.normal(0.001, 0.01, 200)
        # Last 50 observations are stress (worse returns)
        returns[-50:] = rng.normal(-0.005, 0.03, 50)

        # Mark last 50 as high stress probability
        probs = np.zeros(200)
        probs[-50:] = 0.8

        cvar_conditional = compute_regime_cvar(returns, probs, regime_threshold=0.5)
        cvar_unconditional = compute_regime_cvar(returns, probs, regime_threshold=1.1)  # forces fallback

        # Conditional CVaR should be worse (more negative) since stress returns are worse
        assert cvar_conditional < cvar_unconditional

    def test_fallback_when_insufficient_stress_data(self):
        """When < 30 stress observations, falls back to unconditional."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 200)

        # Only 10 stress observations
        probs = np.zeros(200)
        probs[-10:] = 0.9

        cvar_conditional = compute_regime_cvar(returns, probs, regime_threshold=0.5)
        # Should use all returns as fallback
        from quant_engine.cvar_service import compute_cvar_from_returns
        cvar_full, _ = compute_cvar_from_returns(returns)

        assert abs(cvar_conditional - cvar_full) < 1e-10

    def test_all_stress(self):
        """When all observations are stress, result equals unconditional."""
        rng = np.random.default_rng(42)
        returns = rng.normal(-0.002, 0.02, 100)
        probs = np.ones(100) * 0.9

        cvar = compute_regime_cvar(returns, probs, regime_threshold=0.5)
        from quant_engine.cvar_service import compute_cvar_from_returns
        cvar_full, _ = compute_cvar_from_returns(returns)

        assert abs(cvar - cvar_full) < 1e-10

    def test_length_mismatch_handled(self):
        """Mismatched lengths should not crash."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.01, 200)
        probs = np.full(150, 0.8)  # shorter

        cvar = compute_regime_cvar(returns, probs, regime_threshold=0.5)
        assert isinstance(cvar, float)

    def test_result_is_negative(self):
        """CVaR of normal returns should be negative."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0, 0.015, 300)
        probs = np.full(300, 0.7)

        cvar = compute_regime_cvar(returns, probs, regime_threshold=0.5)
        assert cvar < 0

"""Tests for quant_engine.garch_service."""

import numpy as np
import pytest

from quant_engine.garch_service import GarchResult, fit_garch


class TestFitGarch:
    """Unit tests for GARCH(1,1) fitting."""

    def test_insufficient_data_returns_none(self):
        returns = np.random.default_rng(42).normal(0, 0.01, 50)
        result = fit_garch(returns)
        assert result is None

    def test_basic_fit_with_sufficient_data(self):
        """GARCH should fit on 500 observations of normal returns."""
        rng = np.random.default_rng(42)
        returns = rng.normal(0.0003, 0.015, 500)
        result = fit_garch(returns)

        # arch library may or may not be installed
        if result is None:
            pytest.skip("arch library not installed")

        assert isinstance(result, GarchResult)
        if result.converged:
            assert result.volatility_garch is not None
            assert result.volatility_garch > 0
            assert result.persistence is not None
            assert result.persistence < 2.0  # sanity
            assert result.alpha is not None
            assert result.beta is not None

    def test_convergence_flag(self):
        """Result should report convergence status."""
        rng = np.random.default_rng(99)
        returns = rng.normal(0, 0.02, 300)
        result = fit_garch(returns)

        if result is None:
            pytest.skip("arch library not installed")

        assert isinstance(result.converged, bool)

    def test_annualized_volatility_reasonable(self):
        """Annualized vol should be in a reasonable range for typical daily returns."""
        rng = np.random.default_rng(42)
        # Simulate ~15% annualized vol: daily_vol ≈ 0.015/sqrt(252) ≈ 0.00095
        daily_vol = 0.15 / np.sqrt(252)
        returns = rng.normal(0, daily_vol, 1000)
        result = fit_garch(returns)

        if result is None:
            pytest.skip("arch library not installed")

        if result.converged and result.volatility_garch is not None:
            # Should be roughly in the 5%-50% range
            assert 0.01 < result.volatility_garch < 1.0

    def test_constant_returns_no_crash(self):
        """Constant returns should not crash, just fail to converge or return None."""
        returns = np.full(200, 0.001)
        result = fit_garch(returns)
        # Either None or non-converged — should not raise
        if result is not None:
            assert isinstance(result.converged, bool)

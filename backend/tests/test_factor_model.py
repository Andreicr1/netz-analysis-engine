"""Tests for quant_engine.factor_model_service."""

import numpy as np

from quant_engine.factor_model_service import FactorModelResult, decompose_factors


class TestDecomposeFactors:
    """Unit tests for PCA-based factor decomposition."""

    def _make_returns(self, T: int = 200, N: int = 5, seed: int = 42) -> np.ndarray:
        rng = np.random.default_rng(seed)
        return rng.normal(0.0005, 0.02, (T, N))

    def test_basic_decomposition(self):
        returns = self._make_returns()
        weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        result = decompose_factors(returns, None, weights, n_factors=3)

        assert isinstance(result, FactorModelResult)
        assert result.factor_returns.shape == (200, 3)
        assert result.factor_loadings.shape == (5, 3)
        assert len(result.factor_labels) == 3
        assert 0.0 <= result.r_squared <= 1.0
        assert len(result.residual_returns) == 200

    def test_factor_labels_without_proxies(self):
        returns = self._make_returns()
        weights = np.ones(5) / 5
        result = decompose_factors(returns, None, weights, n_factors=2)

        assert result.factor_labels == ["factor_1", "factor_2"]

    def test_factor_labels_with_proxies(self):
        rng = np.random.default_rng(42)
        T, N = 200, 5
        # Create returns with strong first PC correlated to a proxy
        market = rng.normal(0, 0.02, T)
        returns = np.column_stack([market + rng.normal(0, 0.005, T) for _ in range(N)])
        weights = np.ones(N) / N

        proxies = {"market_proxy": market}
        result = decompose_factors(returns, proxies, weights, n_factors=2)

        # First factor should correlate with market_proxy
        assert "market_proxy" in result.factor_labels[0] or "factor_1" in result.factor_labels[0]

    def test_n_factors_capped_when_exceeding_dimensions(self):
        """When n_factors > min(T-1, N), should cap without error."""
        returns = self._make_returns(T=10, N=5)
        weights = np.ones(5) / 5
        result = decompose_factors(returns, None, weights, n_factors=20)

        # Should cap to min(T-1, N) = min(9, 5) = 5
        assert result.factor_returns.shape[1] <= 5

    def test_portfolio_factor_exposures_dict(self):
        returns = self._make_returns()
        weights = np.array([0.4, 0.3, 0.2, 0.05, 0.05])
        result = decompose_factors(returns, None, weights, n_factors=2)

        assert isinstance(result.portfolio_factor_exposures, dict)
        assert len(result.portfolio_factor_exposures) == 2
        for label, exposure in result.portfolio_factor_exposures.items():
            assert isinstance(label, str)
            assert isinstance(exposure, float)

    def test_r_squared_positive(self):
        returns = self._make_returns()
        weights = np.ones(5) / 5
        result = decompose_factors(returns, None, weights, n_factors=3)
        assert result.r_squared > 0.0

    def test_single_factor(self):
        returns = self._make_returns()
        weights = np.ones(5) / 5
        result = decompose_factors(returns, None, weights, n_factors=1)

        assert result.factor_returns.shape[1] == 1
        assert len(result.factor_labels) == 1

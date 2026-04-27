"""PR-Q36 F09: compute_residual_pca T<2 guard."""
from __future__ import annotations

import numpy as np

from quant_engine.factor_model_pca import PCADiagnostic, compute_residual_pca


class TestResidualPcaTGuard:
    """F09: T=1 returns empty diagnostic instead of dividing by zero."""

    def test_single_observation_returns_empty_diagnostic(self):
        """T=1 → zero variance ratios, no top_loadings."""
        residuals = np.random.default_rng(42).normal(0.0, 0.01, size=(1, 10))

        result = compute_residual_pca(residuals)

        assert isinstance(result, PCADiagnostic)
        assert np.all(result.explained_variance_ratio == 0.0)
        assert result.cumulative_variance == 0.0
        assert result.top_loadings == []
        assert len(result.explained_variance_ratio) == 3  # default n_components

    def test_single_observation_custom_components(self):
        """T=1 with n_components=5 → 5-element zero array."""
        residuals = np.ones((1, 8))

        result = compute_residual_pca(residuals, n_components=5)

        assert len(result.explained_variance_ratio) == 5
        assert result.cumulative_variance == 0.0

    def test_normal_case_unchanged(self):
        """T >= 2 produces real PCA diagnostics."""
        residuals = np.random.default_rng(42).normal(0.0, 0.01, size=(252, 10))

        result = compute_residual_pca(residuals, n_components=3)

        assert len(result.explained_variance_ratio) == 3
        assert result.cumulative_variance > 0
        assert len(result.top_loadings) == 3

    def test_t_equals_2_boundary(self):
        """T=2 should work normally (not hit the guard)."""
        residuals = np.random.default_rng(42).normal(0.0, 0.01, size=(2, 5))

        result = compute_residual_pca(residuals, n_components=3)

        # T=2 → n_comp = min(3, 1, 5) = 1
        assert len(result.explained_variance_ratio) == 1
        assert len(result.top_loadings) == 1

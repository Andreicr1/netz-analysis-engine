"""Residual PCA diagnostic for the fundamental factor model.

Kept in a separate module from ``factor_model_service`` so that
``assemble_factor_covariance`` cannot accidentally accept a ``PCADiagnostic``
instance at the type level (enforced by mypy / ``typing.assert_type``).

The residual PCA is a pure diagnostic — it never feeds back into covariance
estimation. The gate enforcement lives in
``backend/tests/quant_engine/test_assemble_factor_covariance_types.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt


@dataclass(frozen=True)
class PCADiagnostic:
    """Diagnostic PCA results for the fundamental factor model residuals."""

    explained_variance_ratio: npt.NDArray[np.float64]
    cumulative_variance: float
    top_loadings: list[dict[str, Any]]


def compute_residual_pca(
    residual_series: npt.NDArray[np.float64],
    n_components: int = 3,
) -> PCADiagnostic:
    """Compute PCA on residuals for diagnostic purposes.

    Diagnostic only — never feeds back into covariance estimation.
    """
    T, N = residual_series.shape
    n_comp = min(n_components, T - 1, N)

    # Demean residuals
    centered = residual_series - residual_series.mean(axis=0)

    # SVD
    _, S, Vt = np.linalg.svd(centered, full_matrices=False)

    explained_variance = S**2 / (T - 1)
    total_var = explained_variance.sum()
    explained_variance_ratio = (
        explained_variance[:n_comp] / total_var
        if total_var > 0
        else np.zeros(n_comp, dtype=np.float64)
    )

    top_loadings: list[dict[str, Any]] = []
    for k in range(n_comp):
        loading_k = Vt[k]
        top_idx = np.argsort(np.abs(loading_k))[-5:][::-1]
        top_loadings.append(
            {
                "component": k + 1,
                "explained_variance_ratio": float(explained_variance_ratio[k]),
                "top_contributors": [
                    {"fund_index": int(i), "weight": float(loading_k[i])}
                    for i in top_idx
                ],
            }
        )

    return PCADiagnostic(
        explained_variance_ratio=explained_variance_ratio,
        cumulative_variance=float(np.sum(explained_variance_ratio)),
        top_loadings=top_loadings,
    )

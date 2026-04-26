"""IPCA gamma drift monitor."""
from __future__ import annotations

import numpy as np
import numpy.typing as npt
import structlog

logger = structlog.get_logger()

_DRIFT_THRESHOLD = 0.25


def compute_gamma_drift(
    gamma_old: npt.NDArray[np.float64],
    gamma_new: npt.NDArray[np.float64],
) -> float:
    """Compute Procrustes-aligned relative Frobenius norm drift between two gamma matrices.

    PR-Q35 F01: IPCA factor loadings (Γ) are identified only up to an orthogonal
    rotation (Kelly-Pruitt-Su 2019). The ALS solver may converge to different
    rotations or sign flips across re-estimations. To measure true drift in the
    spanned factor space, we apply orthogonal Procrustes alignment (Schönemann
    1966) before computing the Frobenius norm.

    Without this alignment, the previous code falsely flagged drift=2.0 for a
    pure sign flip (gamma_new = -gamma_old), which is a valid IPCA equivalence
    and should produce drift=0.0.

    Reference: Wave 6 Session 03 F01, audit-validation-session03.md.
    """
    if gamma_old.shape != gamma_new.shape:
        raise ValueError(
            f"Shape mismatch: gamma_old {gamma_old.shape} != gamma_new {gamma_new.shape}"
        )

    norm_old = np.linalg.norm(gamma_old, ord="fro")
    if norm_old < 1e-12:
        return 0.0

    # PR-Q35 F01: orthogonal Procrustes alignment.
    # Find rotation R minimizing ||gamma_new @ R - gamma_old||_F.
    # Solution: R = U @ V^T where U Σ V^T = SVD(gamma_old^T @ gamma_new).
    U, _, Vt = np.linalg.svd(gamma_old.T @ gamma_new)
    R = U @ Vt
    gamma_new_aligned = gamma_new @ R.T

    diff = gamma_new_aligned - gamma_old
    drift = float(np.linalg.norm(diff, ord="fro") / norm_old)

    if drift > _DRIFT_THRESHOLD:
        logger.warning(
            "ipca_gamma_drift_alert",
            drift=drift,
            threshold=_DRIFT_THRESHOLD,
        )

    return drift

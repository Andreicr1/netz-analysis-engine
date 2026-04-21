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
    """Compute relative Frobenius norm drift between two gamma matrices."""
    if gamma_old.shape != gamma_new.shape:
        raise ValueError(
            f"Shape mismatch: gamma_old {gamma_old.shape} != gamma_new {gamma_new.shape}"
        )
    
    norm_old = np.linalg.norm(gamma_old, ord="fro")
    if norm_old < 1e-12:
        return 0.0

    diff = gamma_new - gamma_old
    drift = float(np.linalg.norm(diff, ord="fro") / norm_old)
    
    if drift > _DRIFT_THRESHOLD:
        logger.warning(
            "ipca_gamma_drift_alert",
            drift=drift,
            threshold=_DRIFT_THRESHOLD,
        )
    
    return drift

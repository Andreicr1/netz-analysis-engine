"""IPCA fitting logic.

Wraps ipca==0.6.7's InstrumentedPCA for Kelly-Pruitt-Su factor model.
Single-column return contract; multi-column inputs raise ValueError.

Convergence detection parses stdout (no public API in 0.6.7); when no
'Step N:' lines are observed, fit returns degraded=True. Pin ipca version.

OOS R² is NOT computed here — see factor_model_ipca_service for the
CV-based model selection that populates that field. fit_ipca always
returns oos_r_squared=None.

Library version assumption: ipca==0.6.7
  - reg.Factors shape: (K, T)  — this code asserts and transposes if violated
  - reg.Gamma shape: (L, K)    — characteristic loadings
  - stdout format: 'Step N: ...' per ALS iteration
"""
from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from datetime import date

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog
from ipca import InstrumentedPCA

logger = structlog.get_logger()


@dataclass(frozen=True)
class IPCAFit:
    """Result of IPCA model fit.

    Notes:
      - oos_r_squared is computed only by the model-selection service
        (factor_model_ipca_service) via expanding-window cross-validation
        — not by the final fit. Per PR-Q9 / Wave 5 audit decision, embedding
        OOS computation in fit_ipca's hot path would conflate model
        selection with final estimation. fit_ipca always returns
        oos_r_squared=None; callers obtain OOS via the CV orchestrator.
      - degraded=True when convergence detection failed. r_squared and
        gamma are still populated but should be treated with caution.
      - gamma and factor_returns are returned as read-only ndarrays
        (writeable=False); deepcopy if mutation is required.
      - factor_returns shape is (K, T) where T = len(dates).
    """

    gamma: npt.NDArray[np.float64]
    factor_returns: npt.NDArray[np.float64]
    K: int
    intercept: bool
    r_squared: float
    oos_r_squared: float | None  # ALWAYS None from fit_ipca; populated by CV layer.
    converged: bool
    n_iterations: int
    dates: pd.DatetimeIndex | None = None
    degraded: bool = False
    degraded_reason: str | None = None

    def factor_returns_for_period(
        self, period_start: date | None, period_end: date | None
    ) -> npt.NDArray[np.float64]:
        """Return factor returns matrix subset for the given period."""
        if self.dates is None:
            # Fallback if dates were not stored
            return self.factor_returns

        mask = np.ones(len(self.dates), dtype=bool)
        if period_start is not None:
            mask &= (self.dates.date >= period_start)
        if period_end is not None:
            mask &= (self.dates.date <= period_end)

        return self.factor_returns[:, mask]


def _detect_convergence_from_stdout(
    output: str, max_iter: int, K: int
) -> tuple[bool, int, bool, str | None]:
    """Parse stdout to detect IPCA convergence.

    Returns:
        (converged, n_iterations, degraded, degraded_reason)
    """
    n_iterations = output.count("Step ")

    if n_iterations == 0:
        # Library produced no recognizable convergence trace.
        return False, 0, True, (
            "ipca_convergence_undetectable: no 'Step N:' lines in stdout. "
            "Verify ipca version (expected 0.6.7)."
        )

    converged = n_iterations < max_iter
    if not converged:
        logger.warning(
            "ipca_fit_did_not_converge",
            K=K,
            max_iter=max_iter,
            n_iterations=n_iterations,
        )
    return converged, n_iterations, False, None


def fit_ipca(
    panel_returns: pd.DataFrame,
    characteristics: pd.DataFrame,
    K: int,
    intercept: bool = False,
    max_iter: int = 200,
    tolerance: float = 1e-6,
) -> IPCAFit:
    """Fit Kelly-Pruitt-Su IPCA model."""
    # Ensure MultiIndex alignment
    aligned_returns, aligned_chars = panel_returns.align(characteristics, join="inner", axis=0)

    # Missing characteristic column edge case handled implicitly by pandas alignment,
    # but we can explicitly check:
    if aligned_chars.empty:
        raise ValueError("No matching characteristics for panel_returns")

    # BUG-T2a-MASK: enforce single-column return contract
    if aligned_returns.shape[1] != 1:
        raise ValueError(
            f"fit_ipca expects single-column returns; got shape {aligned_returns.shape}. "
            "Reshape to (n_obs, 1) — multi-output IPCA is not supported."
        )

    # Handle missing values — full-row notna on both chars and returns
    mask = aligned_chars.notna().all(axis=1) & aligned_returns.notna().all(axis=1)
    aligned_chars = aligned_chars[mask]
    aligned_returns = aligned_returns[mask]

    reg = InstrumentedPCA(
        n_factors=K, intercept=intercept, max_iter=max_iter, iter_tol=tolerance
    )

    X = aligned_chars.values
    y = aligned_returns.values

    # Single column guaranteed by validation above
    y = y.flatten()

    # Capture stdout to parse iteration count — ipca==0.6.7 prints
    # "Step N: ..." per ALS iteration but exposes no converged attribute.
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        reg.fit(X=X, y=y, indices=aligned_chars.index)
    output = buf.getvalue()

    # Forward non-Step output lines to logger (preserve library warnings)
    for line in output.splitlines():
        line_stripped = line.strip()
        if line_stripped and not line_stripped.startswith("Step "):
            logger.info("ipca_library_message", line=line_stripped)

    # BUG-T2b-CONVERGENCE: detect convergence with degraded flag
    converged, n_iterations, degraded, degraded_reason = _detect_convergence_from_stdout(
        output, max_iter, K
    )

    gamma = np.asarray(reg.Gamma, dtype=np.float64)
    factor_returns = np.asarray(reg.Factors, dtype=np.float64)

    # BUG-T2b-FACTORSHAPE: assert factor_returns shape is (K_eff, T)
    # When intercept=True, ipca returns K+1 factors (extra intercept factor)
    K_eff = K + 1 if intercept else K
    if factor_returns.shape[0] != K_eff:
        if factor_returns.ndim == 2 and factor_returns.shape[1] == K_eff:
            factor_returns = factor_returns.T
            logger.info("ipca_factors_transposed_to_KxT", original_shape=reg.Factors.shape)
        else:
            raise RuntimeError(
                f"fit_ipca: unexpected reg.Factors shape {factor_returns.shape}; "
                f"expected ({K_eff}, T) per ipca==0.6.7 contract."
            )

    r_squared_total = reg.score(X=X, y=y, indices=aligned_chars.index)

    # BUG-T2a-DATEINDEX: extract dates by name, positional fallback with type check
    dates = None
    if isinstance(aligned_chars.index, pd.MultiIndex):
        if "date" in aligned_chars.index.names:
            raw_dates = aligned_chars.index.get_level_values("date")
        elif "month" in aligned_chars.index.names:
            raw_dates = aligned_chars.index.get_level_values("month")
        else:
            # Positional fallback with type assertion
            raw_dates = aligned_chars.index.get_level_values(1)
            if not pd.api.types.is_datetime64_any_dtype(pd.Index(raw_dates)):
                raise ValueError(
                    "fit_ipca: MultiIndex level 1 must be dates when 'date'/'month' name is absent. "
                    "Pass a named MultiIndex with 'date' level."
                )
        dates = pd.DatetimeIndex(np.unique(raw_dates))

    # BUG-T3-IMMUTABLE: make arrays read-only to prevent silent corruption
    gamma.flags.writeable = False
    factor_returns.flags.writeable = False

    return IPCAFit(
        gamma=gamma,
        factor_returns=factor_returns,
        K=K,
        intercept=intercept,
        r_squared=float(r_squared_total),
        oos_r_squared=None,
        converged=converged,
        n_iterations=n_iterations,
        dates=dates,
        degraded=degraded,
        degraded_reason=degraded_reason,
    )

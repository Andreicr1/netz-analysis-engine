"""Factor model IPCA service."""
from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import pandas as pd
import structlog

from quant_engine.factor_model_service import FactorModelResult
from quant_engine.ipca.fit import IPCAFit, fit_ipca
from quant_engine.ipca.preprocessing import rank_transform

logger = structlog.get_logger()


@dataclass(frozen=True)
class IPCAConfig:
    """Config for IPCA."""

    K: int | None = None
    max_factors: int = 6


def _detect_convergence(
    reg: object, captured_stdout: str
) -> tuple[bool, int]:
    """Detect convergence from IPCA regressor.

    Uses package attribute when available; falls back to stdout
    'Step ' count for ipca==0.6.7 which exposes no converged attribute.
    """
    # Preferred: package attribute (newer ipca versions)
    if hasattr(reg, "n_iter_") and reg.n_iter_ is not None:
        n_iter = int(reg.n_iter_)
        max_iter = getattr(reg, "max_iter", 1000)
        return n_iter < max_iter, n_iter
    # Fallback: stdout step count
    n_iter = captured_stdout.count("Step ")
    max_iter = getattr(reg, "max_iter", 1000)
    return n_iter < max_iter, n_iter


def fit_universe(
    panel: pd.DataFrame,
    characteristics: pd.DataFrame,
    max_k: int = 6,
    max_iter: int = 200,
) -> IPCAFit:
    """Fit IPCA universe with walk-forward CV to select optimal K."""
    aligned_returns, aligned_chars = panel.align(characteristics, join="inner", axis=0)

    if aligned_returns.empty or aligned_chars.empty:
        raise ValueError("No matching characteristics for panel_returns")

    mask = aligned_chars.notna().all(axis=1)
    if isinstance(aligned_returns, pd.DataFrame):
        mask = mask & aligned_returns.notna().iloc[:, 0]
    else:
        mask = mask & aligned_returns.notna()
    aligned_chars = aligned_chars[mask]
    aligned_returns = aligned_returns[mask]

    if aligned_chars.empty:
        raise ValueError(
            "fit_universe: no observations remain after NaN-filtering. "
            "Caller must provide a panel with at least 1 valid (instrument, date) pair."
        )

    # KP-S 2019: cross-sectional rank transform before any IPCA fit.
    # Applied once on the full panel — groupby(level=1) ensures each
    # time period is ranked independently, so train/test splits by date
    # are leakage-free.
    aligned_chars = rank_transform(aligned_chars)

    dates = pd.DatetimeIndex(np.unique(aligned_chars.index.get_level_values(1))).sort_values()

    # Fix 10 (BUG-I10): guard empty dates after NaN filtering
    if len(dates) == 0:
        raise ValueError(
            "fit_universe: no observations remain after NaN-filtering. "
            "Caller must provide a panel with at least 1 valid (instrument, date) pair."
        )

    # Fix 1 (BUG-I1): insufficient panel gets degraded flag
    if len(dates) < 72:
        # Not enough data for 60m train + 12m test. Just fit K=3 and return
        fit = fit_ipca(aligned_returns, aligned_chars, K=3, max_iter=max_iter)
        return IPCAFit(
            gamma=fit.gamma,
            factor_returns=fit.factor_returns,
            K=3,
            intercept=fit.intercept,
            r_squared=fit.r_squared,
            oos_r_squared=0.0,
            converged=fit.converged,
            n_iterations=fit.n_iterations,
            dates=dates,
            degraded=True,
            degraded_reason=f"insufficient_dates_{len(dates)}_lt_72",
        )

    # Fix 4 (BUG-I3): track which K's had at least one valid fold
    k_results: dict[int, list[float]] = {}

    for k in range(1, max_k + 1):
        oos_r2_scores: list[float] = []
        # Walk-forward: train 60m, test 12m, slide annually (12m)
        # Fix 2 (BUG-I2): inclusive bound — at len(dates)==72, run exactly one fold
        n_folds = (len(dates) - 72) // 12 + 1
        for fold_idx in range(n_folds):
            i = fold_idx * 12
            train_dates = dates[i:i+60]
            test_dates = dates[i+60:i+72]

            # Select train data
            train_mask = aligned_chars.index.get_level_values(1).isin(train_dates)
            train_X = aligned_chars[train_mask]
            train_y = aligned_returns[train_mask]

            if train_X.empty:
                continue

            # Select test data
            test_mask = aligned_chars.index.get_level_values(1).isin(test_dates)
            test_X = aligned_chars[test_mask]
            test_y = aligned_returns[test_mask]

            if test_X.empty:
                continue

            from ipca import InstrumentedPCA
            # Fix 8 (BUG-I6): pass max_iter to CV fold constructors
            reg_oos = InstrumentedPCA(
                n_factors=k, intercept=False, iter_tol=1e-6, max_iter=max_iter,
            )
            buf = io.StringIO()
            try:
                with contextlib.redirect_stdout(buf):
                    reg_oos.fit(X=train_X.values, y=train_y.values.flatten(), indices=train_X.index)
            except Exception as exc:
                logger.warning("ipca_cv_fit_failed", K=k, start=train_dates[0], exc=str(exc))
                continue
            # Fix 6 (BUG-I5): use convergence helper instead of fragile inline parsing
            converged_fold, n_iter_fold = _detect_convergence(reg_oos, buf.getvalue())
            if not converged_fold:
                continue  # skip non-converged folds

            try:
                if hasattr(reg_oos, "predictOOS"):
                    pred = reg_oos.predictOOS(X=test_X.values, y=test_y.values.flatten(), indices=test_X.index)
                    mse = np.sum((test_y.values.flatten() - pred)**2)
                    var = np.sum(test_y.values.flatten()**2)
                    score = 1.0 - mse / var
                else:
                    # Manual OOS calculation (Kelly Pruitt Su formulation)
                    gamma = reg_oos.Gamma
                    mse = 0.0
                    var = 0.0
                    for dt in test_dates:
                        mask_dt = test_X.index.get_level_values(1) == dt
                        X_t = test_X[mask_dt].values
                        y_t = test_y[mask_dt].values.flatten()
                        if len(y_t) > 0:
                            denom = gamma.T @ X_t.T @ X_t @ gamma
                            if np.linalg.cond(denom) > 1e12:
                                continue
                            # Fix 9 (BUG-I7): solve linear system directly instead of inv
                            rhs = gamma.T @ X_t.T @ y_t
                            f_t = np.linalg.solve(denom, rhs)
                            pred_t = X_t @ gamma @ f_t
                            mse += np.sum((y_t - pred_t)**2)
                            var += np.sum(y_t**2)

                    if var > 0:
                        score = 1.0 - mse / var
                    else:
                        score = 0.0

                oos_r2_scores.append(score)
            except Exception as e:
                logger.warning("ipca_cv_predict_failed", K=k, exc=str(e))
                continue

        k_results[k] = oos_r2_scores

    # Fix 4 (BUG-I3): all K's had zero valid folds = structurally bad panel
    if all(len(scores) == 0 for scores in k_results.values()):
        raise ValueError(
            f"IPCA walk-forward CV could not validate any K in [1, {max_k}]: "
            f"all folds failed (likely numerical instability or insufficient data)"
        )

    # Pick best K from those that had at least one valid fold
    candidates = {
        k: float(np.mean(scores))
        for k, scores in k_results.items()
        if scores
    }
    best_k = max(candidates, key=lambda k: candidates[k])
    best_oos_r2 = candidates[best_k]

    # Final fit on all data with best K
    final_fit = fit_ipca(aligned_returns, aligned_chars, K=best_k, max_iter=max_iter)

    # Fix 5 (BUG-I4): stop clamping oos_r2 at 0 — pass-through raw value
    # Fix 7 (BUG-I9): non-converged final fit also marks degraded
    is_degraded = (best_oos_r2 <= 0.0) or not final_fit.converged
    degraded_reason = None
    if best_oos_r2 <= 0.0:
        degraded_reason = "oos_r2_negative_useless_fit"
    elif not final_fit.converged:
        degraded_reason = "final_fit_did_not_converge"

    return IPCAFit(
        gamma=final_fit.gamma,
        factor_returns=final_fit.factor_returns,
        K=best_k,
        intercept=final_fit.intercept,
        r_squared=final_fit.r_squared,
        oos_r_squared=float(best_oos_r2),
        converged=final_fit.converged,
        n_iterations=final_fit.n_iterations,
        dates=dates,
        degraded=is_degraded,
        degraded_reason=degraded_reason,
    )


# Fix 3 (BUG-I8): decompose_portfolio raises NotImplementedError
def decompose_portfolio(
    returns_matrix: npt.NDArray[np.float64],
    config: IPCAConfig,
) -> FactorModelResult:
    """Compatibility interface for decompose_portfolio.

    Currently NOT implemented — raises NotImplementedError to fail-fast
    callers that expected a working decomposition. The fundamental
    decomposition path (factor_model_service.decompose_factors) is the
    canonical PCA route until this IPCA-portfolio path is built out.
    """
    raise NotImplementedError(
        "decompose_portfolio is not yet implemented. Use "
        "factor_model_service.decompose_factors for PCA-based portfolio "
        "decomposition, or compute IPCA factor exposures via "
        "ipca_rail.run_ipca_rail for IPCA attribution."
    )

"""GARCH(1,1) conditional volatility service.

Fits a GARCH(1,1) model to daily returns and forecasts 1-step-ahead
conditional volatility. Falls back to sample volatility if the model
does not converge or the `arch` library is not installed.

Pure sync. Zero I/O. Config via parameter.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class GarchResult:
    """Result of GARCH(1,1) fit.

    Exposes BOTH the conditional (1-step-ahead) annualised volatility
    — which is what risk dashboards want for tail-of-the-day headlines —
    and the unconditional long-run volatility
    ``σ_∞ = sqrt(ω / (1 − α − β))``, which is what strategic allocation,
    long-horizon scoring and model-portfolio construction should consume.

    Penalising a fund on its last-week conditional volatility makes sense
    for a VaR report; it does not make sense for a 5-year strategic view.
    Callers now get to choose which regime applies to their horizon.
    """

    volatility_garch: float | None  # annualized 1-step-ahead conditional vol
    volatility_long_run: float | None  # annualized unconditional vol (σ_∞)
    omega: float | None
    alpha: float | None
    beta: float | None
    persistence: float | None  # alpha + beta (< 1 for stationarity)
    log_likelihood: float | None
    converged: bool
    vol_model: str
    degraded: bool = False
    degraded_reason: str | None = None


def _extract_garch_params(params: dict) -> tuple[float, float, float]:
    """Extract (omega, alpha, beta) from arch fit. Raises if any key is missing."""
    expected = {"omega", "alpha[1]", "beta[1]"}
    missing = expected - set(params.keys())
    if missing:
        raise KeyError(
            f"arch GARCH(1,1) params missing keys: {sorted(missing)}. "
            f"Available: {sorted(params.keys())}. "
            f"This usually means the arch package version is incompatible — "
            f"check pip show arch and update _extract_garch_params if needed."
        )
    return (
        float(params["omega"]),
        float(params["alpha[1]"]),
        float(params["beta[1]"]),
    )


def fit_garch(
    returns: np.ndarray,
    trading_days_per_year: int = 252,
) -> GarchResult | None:
    """Fit GARCH(1,1) to daily returns and return conditional volatility forecast.

    Parameters
    ----------
    returns : np.ndarray
        (T,) daily returns (log or arithmetic) in **decimal** form
        (e.g. 0.005 for +0.5%). This function multiplies by 100 internally
        to match the ``arch`` package convention.
    trading_days_per_year : int
        Annualization factor.

    Returns
    -------
    GarchResult | None
        None if `arch` library is not installed or returns are too short.

    """
    # ── Fix 4 (BUG-G3): filter NaN/Inf before length check ──────────
    returns_arr = np.asarray(returns, dtype=np.float64)
    finite_mask = np.isfinite(returns_arr)
    if not finite_mask.all():
        n_dropped = int((~finite_mask).sum())
        returns_arr = returns_arr[finite_mask]
        logger.info(
            "garch_dropped_non_finite_observations",
            n_dropped=n_dropped,
            n_remaining=int(len(returns_arr)),
        )

    if len(returns_arr) < 100:
        logger.debug("garch_insufficient_data", n_obs=len(returns_arr))
        return None

    # ── Fix 5 (BUG-G5): reject percent-form returns ─────────���────────
    returns_std = float(np.std(returns_arr))
    if returns_std > 0.5:
        raise ValueError(
            f"fit_garch: returns appear to be in percent form (std={returns_std:.4f}). "
            f"Pass returns as decimals (e.g., 0.005 for 0.5% daily move), not percents. "
            f"This function multiplies by 100 internally to match arch package convention."
        )

    try:
        from arch import arch_model
    except ImportError:
        logger.warning("arch_library_not_installed_garch_unavailable")
        return None

    try:
        # Scale returns to percentage for numerical stability (arch convention)
        returns_pct = returns_arr * 100.0

        model = arch_model(
            returns_pct,
            vol="GARCH",
            p=1,
            q=1,
            mean="Zero",
            rescale=False,
        )
        result = model.fit(disp="off", show_warning=False)

        if result.convergence_flag != 0:
            logger.warning("garch_did_not_converge", flag=result.convergence_flag)
            return GarchResult(
                volatility_garch=None,
                volatility_long_run=None,
                omega=None,
                alpha=None,
                beta=None,
                persistence=None,
                log_likelihood=None,
                converged=False,
                vol_model="EWMA_0.94",
                degraded=True,
                degraded_reason="garch_did_not_converge",
            )

        # ── Fix 3 (BUG-G2): fail loud on missing param keys ──────────
        omega, alpha, beta = _extract_garch_params(result.params.to_dict())
        persistence = alpha + beta

        # 1-step-ahead forecast (in percentage^2)
        forecast = result.forecast(horizon=1)
        variance_1step = float(forecast.variance.values[-1, 0])

        # ── Fix 2 (BUG-G4): guard NaN/negative variance ─────────────
        if not np.isfinite(variance_1step) or variance_1step < 0:
            logger.warning(
                "garch_variance_1step_invalid",
                variance_1step=(
                    float(variance_1step)
                    if np.isfinite(variance_1step)
                    else "nan_or_inf"
                ),
            )
            return GarchResult(
                volatility_garch=None,
                volatility_long_run=None,
                omega=round(omega, 8),
                alpha=round(alpha, 6),
                beta=round(beta, 6),
                persistence=round(persistence, 6),
                log_likelihood=round(float(result.loglikelihood), 2),
                converged=False,
                vol_model="EWMA_0.94",
                degraded=True,
                degraded_reason="variance_1step_invalid",
            )

        # Convert back from pct^2 to decimal and annualize
        daily_vol = np.sqrt(max(variance_1step, 0.0)) / 100.0
        annual_vol = daily_vol * np.sqrt(trading_days_per_year)

        # ── Fix 1 (BUG-G1): reject non-stationary fits ──────────────
        is_stationary = persistence < 1.0 - 1e-6

        if not is_stationary:
            logger.warning(
                "garch_non_stationary_fit",
                alpha=round(alpha, 6),
                beta=round(beta, 6),
                persistence=round(persistence, 6),
            )
            return GarchResult(
                volatility_garch=None,
                volatility_long_run=None,
                omega=round(omega, 8),
                alpha=round(alpha, 6),
                beta=round(beta, 6),
                persistence=round(persistence, 6),
                log_likelihood=round(float(result.loglikelihood), 2),
                converged=False,
                vol_model="EWMA_0.94",
                degraded=True,
                degraded_reason="non_stationary_persistence_ge_1",
            )

        # ── Long-run (unconditional) volatility ───────────────────────
        # σ²_∞ = ω / (1 − α − β), annualized same as conditional vol.
        stationary_gap = 1.0 - persistence
        long_run_daily_var_pct = omega / stationary_gap
        long_run_daily_vol = np.sqrt(max(long_run_daily_var_pct, 0.0)) / 100.0
        long_run_annual_vol = long_run_daily_vol * np.sqrt(trading_days_per_year)
        long_run_vol = round(float(long_run_annual_vol), 6)

        return GarchResult(
            volatility_garch=round(float(annual_vol), 6),
            volatility_long_run=long_run_vol,
            omega=round(omega, 8),
            alpha=round(alpha, 6),
            beta=round(beta, 6),
            persistence=round(persistence, 6),
            log_likelihood=round(float(result.loglikelihood), 2),
            converged=True,
            vol_model="GARCH(1,1)",
        )

    except Exception as e:
        logger.warning("garch_fit_failed", error=str(e))
        return GarchResult(
            volatility_garch=None,
            volatility_long_run=None,
            omega=None,
            alpha=None,
            beta=None,
            persistence=None,
            log_likelihood=None,
            converged=False,
            vol_model="EWMA_0.94",
            degraded=True,
            degraded_reason="garch_fit_failed",
        )

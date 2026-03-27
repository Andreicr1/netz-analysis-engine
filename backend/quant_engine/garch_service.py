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
    """Result of GARCH(1,1) fit."""

    volatility_garch: float | None  # annualized 1-step-ahead conditional vol
    omega: float | None
    alpha: float | None
    beta: float | None
    persistence: float | None  # alpha + beta (< 1 for stationarity)
    log_likelihood: float | None
    converged: bool


def fit_garch(
    returns: np.ndarray,
    trading_days_per_year: int = 252,
) -> GarchResult | None:
    """Fit GARCH(1,1) to daily returns and return conditional volatility forecast.

    Parameters
    ----------
    returns : np.ndarray
        (T,) daily returns (log or arithmetic).
    trading_days_per_year : int
        Annualization factor.

    Returns
    -------
    GarchResult | None
        None if `arch` library is not installed or returns are too short.

    """
    if len(returns) < 100:
        logger.debug("garch_insufficient_data", n_obs=len(returns))
        return None

    try:
        from arch import arch_model
    except ImportError:
        logger.warning("arch_library_not_installed_garch_unavailable")
        return None

    try:
        # Scale returns to percentage for numerical stability (arch convention)
        returns_pct = returns * 100.0

        model = arch_model(
            returns_pct,
            vol="Garch",
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
                omega=None,
                alpha=None,
                beta=None,
                persistence=None,
                log_likelihood=None,
                converged=False,
            )

        params = result.params
        omega = float(params.get("omega", 0.0))
        alpha = float(params.get("alpha[1]", 0.0))
        beta = float(params.get("beta[1]", 0.0))
        persistence = alpha + beta

        # 1-step-ahead forecast (in percentage^2)
        forecast = result.forecast(horizon=1)
        variance_1step = float(forecast.variance.values[-1, 0])

        # Convert back from pct^2 to decimal and annualize
        daily_vol = np.sqrt(variance_1step) / 100.0
        annual_vol = daily_vol * np.sqrt(trading_days_per_year)

        return GarchResult(
            volatility_garch=round(float(annual_vol), 6),
            omega=round(omega, 8),
            alpha=round(alpha, 6),
            beta=round(beta, 6),
            persistence=round(persistence, 6),
            log_likelihood=round(float(result.loglikelihood), 2),
            converged=True,
        )

    except Exception as e:
        logger.warning("garch_fit_failed", error=str(e))
        return GarchResult(
            volatility_garch=None,
            omega=None,
            alpha=None,
            beta=None,
            persistence=None,
            log_likelihood=None,
            converged=False,
        )

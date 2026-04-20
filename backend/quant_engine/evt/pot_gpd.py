"""POT (Peaks-Over-Threshold) and GPD (Generalized Pareto Distribution) fitting.

Implementation of Extreme Value Theory (EVT) for extreme VaR/CVaR estimation.
Reference: EDHEC Gaps Quant Math Spec §4.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import structlog
from scipy.stats import genpareto

logger = structlog.get_logger()

import importlib.util

LMOMENTS_AVAILABLE = importlib.util.find_spec("lmoments3") is not None
if LMOMENTS_AVAILABLE:
    from lmoments3 import distr
else:
    logger.warning("lmoments3_not_installed_evt_fallback_disabled")


@dataclass(frozen=True)
class GPDFit:
    xi: float          # shape
    beta: float        # scale
    u: float           # threshold
    n_exceedances: int
    method: Literal["mle", "lmoments", "fallback_normal"]
    converged: bool


@dataclass(frozen=True)
class ExtremeVaRResult:
    var_99: float
    var_995: float
    var_999: float
    cvar_99: float
    cvar_995: float
    cvar_999: float
    fit: GPDFit
    degraded: bool
    degraded_reason: str | None


def compute_hill_estimator(losses: np.ndarray, k: int) -> float:
    """Compute Hill estimator for the shape parameter xi.

    Uses the top k largest losses.
    """
    if k <= 1 or len(losses) < k:
        return 0.0
    top_losses = np.sort(losses)[-k:]
    # Hill estimator: 1/(k-1) * sum_{i=1}^{k-1} log(X_{(i)} / X_{(k)})
    # where X_{(1)} >= X_{(2)} >= ... >= X_{(k)}
    # Here top_losses is sorted ascending, so X_{(k)} is top_losses[0]
    u = top_losses[0]
    if u <= 0:
        return 0.0
    excesses = top_losses[1:]
    if len(excesses) == 0:
        return 0.0
    return float(np.mean(np.log(excesses / u)))


def extreme_var_evt(
    returns: np.ndarray,
    quantiles: tuple[float, ...] = (0.99, 0.995, 0.999),
    threshold_method: Literal["quantile_90", "quantile_85"] = "quantile_90",
) -> ExtremeVaRResult:
    """Estimate extreme VaR and CVaR using POT + GPD.

    Follows the 11-step pipeline for institutional asset/wealth management.
    """
    # 1. Clean data
    clean_returns = returns[~np.isnan(returns)]
    if len(clean_returns) == 0:
        return _degraded_result(0.0, "no_data")

    # Total number of observations for unconditional probability
    N_total = len(clean_returns)

    # 2. Work with losses (positive numbers = negative returns)
    # We follow the convention: losses = -returns
    all_losses = -clean_returns
    
    # Filter for actually negative returns to focus on the loss tail
    losses = all_losses[all_losses > 0]
    if len(losses) < 15:
        return _fallback_to_normal(clean_returns, quantiles, 0.0, "insufficient_losses")

    # 3. Threshold selection
    q_threshold = 0.90 if threshold_method == "quantile_90" else 0.85
    u = float(np.quantile(losses, q_threshold))
    
    # Exceedances above threshold u
    excesses = losses[losses > u] - u
    n_u = len(excesses)

    # 4. Handle insufficient exceedances
    if n_u < 20 and threshold_method == "quantile_90":
        # Retry with 85%
        return extreme_var_evt(returns, quantiles, threshold_method="quantile_85")

    if n_u < 15:
        return _fallback_to_normal(clean_returns, quantiles, u, "insufficient_exceedances")

    # 5. Fit GPD via MLE
    xi, beta, converged = _fit_gpd_mle(excesses)

    method: Literal["mle", "lmoments", "fallback_normal"] = "mle"

    # 6. L-moments fallback if MLE failed or unstable
    # Spec: Trigger when MLE does not converge OR CI of xi crosses 1.
    # Simplified trigger: xi >= 0.9 or not converged
    if (not converged or xi >= 0.9) and LMOMENTS_AVAILABLE:
        xi_lm, beta_lm = _fit_gpd_lmoments(excesses)
        if xi_lm < 1.0:
            xi, beta = xi_lm, beta_lm
            method = "lmoments"
            converged = True

    # 7. Sanity check: Hill estimator
    k_hill = max(15, int(0.10 * len(losses)))
    xi_hill = compute_hill_estimator(losses, k_hill)
    
    degraded = not converged
    reason = None
    
    if abs(xi_hill - xi) > 2 * abs(xi) and xi > 0.1:
         degraded = True
         reason = "hill_estimator_divergence"

    # 8. Compute Extreme VaR/CVaR
    results = {}
    
    if xi >= 1.0:
        # Infinite mean tail - CVaR undefined
        degraded = True
        reason = "infinite_mean_tail"

    for q in quantiles:
        # P(Loss > VaR_q) = 1 - q
        # (n_u / N_total) * (1 + xi * (VaR_q - u) / beta)^(-1/xi) = 1 - q
        # VaR_q = u + (beta / xi) * [ ((N_total / n_u) * (1 - q))^(-xi) - 1 ]
        
        if abs(xi) < 1e-6:
             # Exponential limit
             var_q = u + beta * np.log((n_u / N_total) / (1 - q))
             cvar_q = var_q + beta
        else:
             prob_ratio = (n_u / N_total) / (1 - q)
             if prob_ratio <= 0:
                 var_q = u # Should not happen with q=0.99
                 cvar_q = u
             else:
                 term = prob_ratio ** xi
                 var_q = u + (beta / xi) * (term - 1)
                 if xi < 1.0:
                     # CVaR formula from spec §4.4
                     cvar_q = var_q / (1 - xi) + (beta - xi * u) / (1 - xi)
                 else:
                     cvar_q = np.nan

        results[f"var_{int(q*1000)}"] = float(var_q)
        results[f"cvar_{int(q*1000)}"] = float(cvar_q)

    fit = GPDFit(
        xi=float(xi),
        beta=float(beta),
        u=float(u),
        n_exceedances=int(n_u),
        method=method,
        converged=converged,
    )

    return ExtremeVaRResult(
        var_99=results.get("var_990", 0.0),
        var_995=results.get("var_995", 0.0),
        var_999=results.get("var_999", 0.0),
        cvar_99=results.get("cvar_990", 0.0),
        cvar_995=results.get("cvar_995", 0.0),
        cvar_999=results.get("cvar_999", 0.0),
        fit=fit,
        degraded=degraded,
        degraded_reason=reason,
    )


def _fit_gpd_mle(excesses: np.ndarray) -> tuple[float, float, bool]:
    """Fit GPD using Maximum Likelihood Estimation."""
    try:
        # genpareto.fit returns (c, loc, scale)
        # c = xi, loc = 0 (fixed), scale = beta
        params = genpareto.fit(excesses, floc=0)
        xi, _, beta = params
        return float(xi), float(beta), True
    except Exception as e:
        logger.warning("gpd_mle_fit_failed", error=str(e))
        return 0.0, float(np.std(excesses)), False


def _fit_gpd_lmoments(excesses: np.ndarray) -> tuple[float, float]:
    """Fit GPD using Method of L-moments."""
    try:
        paras = distr.gpa.lmom_fit(excesses)
        return float(paras['c']), float(paras['scale'])
    except Exception as e:
        logger.warning("gpd_lmoments_fit_failed", error=str(e))
        return 0.0, float(np.std(excesses))


def _fallback_to_normal(
    returns: np.ndarray,
    quantiles: tuple[float, ...],
    u: float,
    reason: str,
) -> ExtremeVaRResult:
    """Fallback to parametric normal VaR when EVT fit is impossible."""
    mu = np.mean(returns)
    sigma = np.std(returns)

    results = {}
    from scipy.stats import norm
    for q in quantiles:
        # VaR_q is the (1-q) quantile of returns
        # var_q = -(mu + sigma * norm.ppf(1-q))
        z = norm.ppf(1 - q)
        var_q = -(mu + z * sigma)
        
        # CVaR_normal = -mu + sigma * phi(z) / (1-q)
        phi_z = norm.pdf(z)
        cvar_q = -mu + sigma * phi_z / (1 - q)

        results[f"var_{int(q*1000)}"] = float(var_q)
        results[f"cvar_{int(q*1000)}"] = float(cvar_q)

    fit = GPDFit(
        xi=0.0,
        beta=0.0,
        u=u,
        n_exceedances=0,
        method="fallback_normal",
        converged=False,
    )

    return ExtremeVaRResult(
        var_99=results.get("var_990", 0.0),
        var_995=results.get("var_995", 0.0),
        var_999=results.get("var_999", 0.0),
        cvar_99=results.get("cvar_990", 0.0),
        cvar_995=results.get("cvar_995", 0.0),
        cvar_999=results.get("cvar_999", 0.0),
        fit=fit,
        degraded=True,
        degraded_reason=reason,
    )


def _degraded_result(u: float, reason: str) -> ExtremeVaRResult:
    """Return a zeroed result with degraded flag."""
    fit = GPDFit(
        xi=0.0,
        beta=0.0,
        u=u,
        n_exceedances=0,
        method="fallback_normal",
        converged=False,
    )
    return ExtremeVaRResult(
        var_99=0.0, var_995=0.0, var_999=0.0,
        cvar_99=0.0, cvar_995=0.0, cvar_999=0.0,
        fit=fit,
        degraded=True,
        degraded_reason=reason,
    )

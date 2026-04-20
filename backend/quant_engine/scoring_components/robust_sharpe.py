"""Robust Sharpe Ratio (Cornish-Fisher + Opdyke CI).

Implements EDHEC Gap G1 per `docs/superpowers/specs/2026-04-19-edhec-gaps-quant-math.md` §1.

References:
- Favre, L. & Galeano, J.-A. (2002) "Mean-Modified Value-at-Risk Optimization with
  Hedge Funds", JAI.
- Gregoriou, G. & Gueyie, J.-P. (2003) "Risk-Adjusted Performance of Funds of
  Hedge Funds Using a Modified Sharpe Ratio", JWM.
- Opdyke, J. (2007) "Comparing Sharpe Ratios: So Where Are the p-Values?", JFIM.

Pure function — no DB, no async, no I/O. Deterministic given inputs. Safe to
call from sync workers and async entry points alike.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
from scipy import stats

__all__ = ["RobustSharpeResult", "robust_sharpe"]


# T<36 degrades; jackknife trigger below T<60 or |skew|>1.5.
_MIN_OBS_TRADITIONAL = 12
_MIN_OBS_CORNISH_FISHER = 36
_JACKKNIFE_T_THRESHOLD = 60
_JACKKNIFE_SKEW_THRESHOLD = 1.5
_CI_Z_95 = 1.959963984540054  # stats.norm.ppf(0.975)


@dataclass(frozen=True)
class RobustSharpeResult:
    """Robust Sharpe output with Cornish-Fisher adjustment + Opdyke CI."""

    sharpe_traditional: float
    sharpe_cornish_fisher: float
    ci_lower_95: float
    ci_upper_95: float
    skewness: float
    excess_kurtosis: float
    n_observations: int
    ci_method: Literal["closed_form", "jackknife"]
    degraded: bool
    degraded_reason: str | None


def _nan_result(
    *,
    n: int,
    reason: str,
    sharpe_traditional: float = float("nan"),
    skewness: float = float("nan"),
    excess_kurtosis: float = float("nan"),
) -> RobustSharpeResult:
    return RobustSharpeResult(
        sharpe_traditional=sharpe_traditional,
        sharpe_cornish_fisher=float("nan"),
        ci_lower_95=float("nan"),
        ci_upper_95=float("nan"),
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
        n_observations=n,
        ci_method="closed_form",
        degraded=True,
        degraded_reason=reason,
    )


def _cornish_fisher_z(z: float, skew: float, excess_kurt: float) -> float:
    """Cornish-Fisher expansion of normal quantile `z`.

    $z_{CF} = z + \\tfrac{1}{6}(z^2 - 1)S + \\tfrac{1}{24}(z^3 - 3z)K
              - \\tfrac{1}{36}(2z^3 - 5z)S^2$
    """
    return (
        z
        + (z * z - 1.0) / 6.0 * skew
        + (z * z * z - 3.0 * z) / 24.0 * excess_kurt
        - (2.0 * z * z * z - 5.0 * z) / 36.0 * (skew * skew)
    )


def _opdyke_variance(sr_period: float, skew: float, excess_kurt: float, T: int) -> float:
    """Opdyke (2007) closed-form asymptotic variance of the period Sharpe estimator.

    Uses *period* SR (not annualized). Excess kurtosis $K$ is already
    $K_{\\text{full}} - 3$, so the spec's $(K-3)/4 \\cdot SR^2$ term becomes
    $K_{\\text{excess}}/4 \\cdot SR^2$.
    """
    return (
        1.0
        + 0.5 * sr_period * sr_period
        - skew * sr_period
        + (excess_kurt / 4.0) * sr_period * sr_period
    ) / T


def _jackknife_se(excess_returns: "np.ndarray[tuple[int, ...], np.dtype[np.float64]]", periods_per_year: int) -> float:
    """Leave-one-out jackknife standard error for the *annualized* Sharpe ratio."""
    T = excess_returns.size
    sum_all = float(excess_returns.sum())
    sumsq_all = float(np.square(excess_returns).sum())
    sqrt_ann = float(np.sqrt(periods_per_year))
    loo = np.empty(T)
    for i in range(T):
        n = T - 1
        s = sum_all - float(excess_returns[i])
        ss = sumsq_all - float(excess_returns[i]) ** 2
        mean_i = s / n
        # sample variance with ddof=1
        var_i = (ss - n * mean_i * mean_i) / (n - 1)
        if var_i <= 0.0:
            loo[i] = float("nan")
        else:
            loo[i] = mean_i / float(np.sqrt(var_i)) * sqrt_ann
    loo = loo[np.isfinite(loo)]
    if loo.size < 3:
        return float("nan")
    var_pop = float(np.var(loo, ddof=0))
    # Prompt convention (spec §1 hint): SE = sqrt((T-1)/T * var_pop).
    return float(np.sqrt((T - 1) / T * var_pop))


def robust_sharpe(
    returns: "np.ndarray[tuple[int, ...], np.dtype[np.float64]] | np.ndarray",  # type: ignore[type-arg]
    rf_rate: float | None,
    ci_method: str = "closed_form",
    alpha_cf: float = 0.05,
    periods_per_year: int = 12,
) -> RobustSharpeResult:
    """Compute robust (Cornish-Fisher adjusted) Sharpe Ratio with 95% CI.

    Args:
        returns: Periodic (typically monthly) return series. NaNs are stripped.
        rf_rate: Per-period risk-free rate. ``None`` is treated as 0 (spec §1.3).
        ci_method: ``"closed_form"`` (default) or ``"jackknife"``. Closed form
            auto-falls-back to jackknife when ``T < 60`` or ``|skew| > 1.5``.
        alpha_cf: Tail probability for the Cornish-Fisher quantile. Default 0.05.
        periods_per_year: Annualization factor (12 monthly, 252 daily).

    Returns:
        `RobustSharpeResult` populated with traditional + robust values,
        degradation flags, and CI bounds.
    """
    arr = np.asarray(returns, dtype=float).ravel()
    # Strip NaNs per §1.3.
    arr = arr[np.isfinite(arr)]
    T = int(arr.size)
    rf = 0.0 if rf_rate is None else float(rf_rate)

    if T < _MIN_OBS_TRADITIONAL:
        if T == 0:
            return _nan_result(n=0, reason="all_nan_or_empty")
        # T<12 still tries to emit traditional Sharpe on a best-effort basis.
        excess = arr - rf
        mean = float(np.mean(excess))
        std = float(np.std(arr, ddof=1)) if T > 1 else 0.0
        sqrt_ann = float(np.sqrt(periods_per_year))
        sr_trad = (mean / std * sqrt_ann) if std > 0 else float("nan")
        return _nan_result(
            n=T,
            reason="insufficient_observations",
            sharpe_traditional=sr_trad,
        )

    excess = arr - rf
    mean = float(np.mean(excess))
    std_returns = float(np.std(arr, ddof=1))
    sqrt_ann = float(np.sqrt(periods_per_year))

    if std_returns == 0.0 or not np.isfinite(std_returns):
        signed = float("inf") if mean > 0 else (float("-inf") if mean < 0 else float("nan"))
        return _nan_result(
            n=T,
            reason="zero_volatility",
            sharpe_traditional=signed,
            skewness=0.0,
            excess_kurtosis=0.0,
        )

    sr_period = mean / std_returns  # per-period Sharpe (not annualized)
    sr_traditional = sr_period * sqrt_ann

    # Unbiased sample moments.
    skew = float(stats.skew(arr, bias=False))
    excess_kurt = float(stats.kurtosis(arr, bias=False, fisher=True))

    if T < _MIN_OBS_CORNISH_FISHER:
        return _nan_result(
            n=T,
            reason="insufficient_observations",
            sharpe_traditional=sr_traditional,
            skewness=skew,
            excess_kurtosis=excess_kurt,
        )

    # Cornish-Fisher adjusted Sharpe via modified-VaR scaling of σ (spec §1.1).
    z = float(stats.norm.ppf(alpha_cf))
    z_cf = _cornish_fisher_z(z, skew, excess_kurt)

    # z (left tail) is negative; z_cf must remain negative for the CF σ to be
    # positive. If extreme skew/kurtosis pushes it positive, the quantile
    # expansion is non-monotonic — clamp and flag.
    cf_non_monotonic = z_cf >= 0.0
    sigma_cf: float
    sr_cf: float
    if cf_non_monotonic:
        # Clamp per §1.3 (z_cf floor at -0.01 · z to keep SR_CF finite).
        z_cf_clamped = -0.01 * abs(z)
        sigma_cf = (z_cf_clamped / z) * std_returns
        sr_cf = mean / sigma_cf * sqrt_ann
    else:
        sigma_cf = (z_cf / z) * std_returns
        sr_cf = mean / sigma_cf * sqrt_ann

    # CI method selection / fallback.
    requested = ci_method if ci_method in {"closed_form", "jackknife"} else "closed_form"
    use_jackknife = (
        requested == "jackknife"
        or T < _JACKKNIFE_T_THRESHOLD
        or abs(skew) > _JACKKNIFE_SKEW_THRESHOLD
    )

    if use_jackknife:
        se_ann = _jackknife_se(excess, periods_per_year)
        method: Literal["closed_form", "jackknife"] = "jackknife"
    else:
        var_period = _opdyke_variance(sr_period, skew, excess_kurt, T)
        if var_period <= 0.0 or not np.isfinite(var_period):
            se_ann = float("nan")
        else:
            se_ann = float(np.sqrt(var_period)) * sqrt_ann
        method = "closed_form"

    if np.isfinite(se_ann):
        ci_lower = sr_traditional - _CI_Z_95 * se_ann
        ci_upper = sr_traditional + _CI_Z_95 * se_ann
    else:
        ci_lower = float("nan")
        ci_upper = float("nan")

    degraded = cf_non_monotonic or not np.isfinite(se_ann)
    reason: str | None
    if cf_non_monotonic:
        reason = "cornish_fisher_non_monotonic"
    elif not np.isfinite(se_ann):
        reason = "ci_unavailable"
    else:
        reason = None

    return RobustSharpeResult(
        sharpe_traditional=sr_traditional,
        sharpe_cornish_fisher=sr_cf,
        ci_lower_95=ci_lower,
        ci_upper_95=ci_upper,
        skewness=skew,
        excess_kurtosis=excess_kurt,
        n_observations=T,
        ci_method=method,
        degraded=degraded,
        degraded_reason=reason,
    )

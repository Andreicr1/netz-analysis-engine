"""Tail risk service — eVestment Section VII.

Pure sync computation — no I/O, no DB access.  Computes:

Parametric VaR:   Normal-distribution VaR at 90/95/99% confidence
Modified VaR:     Cornish-Fisher expansion (skewness + kurtosis adjustment)
ETL/CVaR:         Expected Tail Loss at 95% (historical)
Modified ETL:     ETL using modified VaR threshold
ETR:              Expected Tail Return at 95% (right tail)
Normality:        Jarque-Bera test statistic and p-value

Reusable across entity_analytics, DD reports, risk dashboards.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats as sp_stats


@dataclass(frozen=True, slots=True)
class TailRiskResult:
    """eVestment Section VII tail risk measures."""

    # Parametric VaR (Normal distribution)
    var_parametric_90: float | None = None
    var_parametric_95: float | None = None
    var_parametric_99: float | None = None

    # Modified VaR (Cornish-Fisher adjustment)
    var_modified_95: float | None = None
    var_modified_99: float | None = None

    # ETL / CVaR
    etl_95: float | None = None  # Expected Tail Loss (same as CVaR)
    etl_modified_95: float | None = None  # Modified ETL using mVaR

    # ETR (right tail)
    etr_95: float | None = None  # Expected Tail Return

    # Risk-adjusted tail metrics (eVestment Section VI)
    starr_ratio: float | None = None  # (E(R) - Rf) / |ETL|
    rachev_ratio: float | None = None  # ETR / |ETL|

    # Normality tests
    jarque_bera_stat: float | None = None
    jarque_bera_pvalue: float | None = None
    is_normal: bool | None = None  # p > 0.05


def _parametric_var(
    mean: float, std: float, confidence: float,
) -> float:
    """Parametric VaR assuming normal distribution.

    VaR = E(R) + Z_c * sigma, where Z_c is the lower-tail quantile.
    Returns a negative number (loss).
    """
    z = sp_stats.norm.ppf(1 - confidence)
    return float(mean + z * std)


def _cornish_fisher_var(
    mean: float, std: float, skew: float, excess_kurt: float, confidence: float,
) -> float:
    """Modified VaR via Cornish-Fisher expansion.

    Adjusts the normal quantile for skewness and excess kurtosis:
      z_cf = z + (z^2 - 1)/6 * S + (z^3 - 3z)/24 * K - (2z^3 - 5z)/36 * S^2

    Returns VaR = mean + z_cf * std (negative = loss).
    """
    z = sp_stats.norm.ppf(1 - confidence)
    z_cf = (
        z
        + (z**2 - 1) / 6 * skew
        + (z**3 - 3 * z) / 24 * excess_kurt
        - (2 * z**3 - 5 * z) / 36 * skew**2
    )
    return float(mean + z_cf * std)


def compute_tail_risk(
    daily_returns: np.ndarray,
    confidence_levels: list[float] | None = None,
    risk_free_rate: float = 0.04,
) -> TailRiskResult:
    """Compute eVestment Section VII tail risk measures.

    Parameters
    ----------
    daily_returns : np.ndarray
        (T,) daily returns.
    confidence_levels : list[float] | None
        Confidence levels for VaR (default [0.90, 0.95, 0.99]).
    risk_free_rate : float
        Annualized risk-free rate for STARR computation (default 4%).

    """
    if len(daily_returns) < 30:
        return TailRiskResult()

    if confidence_levels is None:
        confidence_levels = [0.90, 0.95, 0.99]

    returns = daily_returns.copy()
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    skew = float(sp_stats.skew(returns))
    excess_kurt = float(sp_stats.kurtosis(returns))  # excess kurtosis

    if std < 1e-12:
        return TailRiskResult()

    # ── Parametric VaR (Normal) ───────────────────────────────────────
    var_p90 = _parametric_var(mean, std, 0.90)
    var_p95 = _parametric_var(mean, std, 0.95)
    var_p99 = _parametric_var(mean, std, 0.99)

    # ── Modified VaR (Cornish-Fisher) ─────────────────────────────────
    var_m95 = _cornish_fisher_var(mean, std, skew, excess_kurt, 0.95)
    var_m99 = _cornish_fisher_var(mean, std, skew, excess_kurt, 0.99)

    # ── ETL / CVaR (Historical) ───────────────────────────────────────
    sorted_returns = np.sort(returns)
    cutoff_95 = int(len(sorted_returns) * 0.05)
    cutoff_95 = max(cutoff_95, 1)

    etl_95 = float(np.mean(sorted_returns[:cutoff_95]))

    # Modified ETL: mean of returns below modified VaR threshold
    below_mvar = returns[returns <= var_m95]
    etl_m95 = float(np.mean(below_mvar)) if len(below_mvar) > 0 else etl_95

    # ── ETR (Expected Tail Return — right tail) ──────────────────────
    upper_cutoff = int(len(sorted_returns) * 0.95)
    upper_cutoff = min(upper_cutoff, len(sorted_returns) - 1)
    etr_95 = float(np.mean(sorted_returns[upper_cutoff:]))

    # ── Jarque-Bera Normality Test ────────────────────────────────────
    n = len(returns)
    jb_stat = float(n * (skew**2 / 6 + excess_kurt**2 / 24))
    jb_pvalue = float(1 - sp_stats.chi2.cdf(jb_stat, df=2))
    is_normal = jb_pvalue > 0.05

    # ── STARR Ratio (eVestment p.72) ─────────────────────────────────
    # STARR = (E(R) - Rf_daily) / |ETL|
    starr = None
    rf_daily = risk_free_rate / 252
    abs_etl = abs(etl_95)
    if abs_etl > 1e-12:
        starr = round(float((mean - rf_daily) / abs_etl), 6)

    # ── Rachev Ratio (eVestment p.72) ────────────────────────────────
    # Rachev = ETR_α / |ETL_β|  where α = β = 5%
    rachev = None
    if abs_etl > 1e-12 and etr_95 > 1e-12:
        rachev = round(float(etr_95 / abs_etl), 6)

    return TailRiskResult(
        var_parametric_90=round(var_p90, 8),
        var_parametric_95=round(var_p95, 8),
        var_parametric_99=round(var_p99, 8),
        var_modified_95=round(var_m95, 8),
        var_modified_99=round(var_m99, 8),
        etl_95=round(etl_95, 8),
        etl_modified_95=round(etl_m95, 8),
        etr_95=round(etr_95, 8),
        starr_ratio=starr,
        rachev_ratio=rachev,
        jarque_bera_stat=round(jb_stat, 4),
        jarque_bera_pvalue=round(jb_pvalue, 6),
        is_normal=is_normal,
    )

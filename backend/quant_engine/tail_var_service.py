"""Tail risk service — eVestment Section VII.

Pure sync computation — no I/O, no DB access.  Computes:

Parametric VaR:   Normal-distribution VaR at 90/95/99% confidence
Modified VaR:     Cornish-Fisher expansion (skewness + kurtosis adjustment)
ETL/CVaR:         Expected Tail Loss at 95% (historical)
Modified ETL:     ETL using modified VaR threshold
ETR:              Expected Tail Return at 95% (right tail)
Normality:        Jarque-Bera test statistic and p-value

Reusable across entity_analytics, DD reports, risk dashboards.

Statistical conventions:
  - Returns: simple decimals (0.01 = 1%), daily.
  - Risk sign: VaR/CVaR/ETL returned NEGATIVE (losses are negative).
    Consumers display via abs() at frontend.
  - Skew/Kurt: scipy default `bias=True` (population moments).
    Used for both Jarque-Bera (correct: JB derivation requires population
    moments) AND Cornish-Fisher expansion (current convention; Hull 2018
    and Jaschke 2002 use sample moments — see method_version below).
  - DOF: std uses ddof=1 (sample std) for VaR/STARR computations.
  - Tail count: ceil(n * α), matching cvar_service.py convention (PR-Q13).
  - Sample minimums:
      * n < 30: empty result (no metrics)
      * 30 <= n < 100: parametric VaR + JB only; ETL/STARR/Rachev = None
      * n >= 100: full result (≥5 tail observations at 95%)

Method version: cf_population_moments_v1
  Reason: migrating to sample moments (Fisher-Pearson bias correction)
  alters historical mVaR series and rankings. Decision deferred to a
  future versioned migration with backfill comparison. See PR-Q21
  decision log and audit-validation-quant-wave5.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import structlog
from scipy import stats as sp_stats

logger = structlog.get_logger()

CF_METHOD_VERSION = "cf_population_moments_v1"

TAIL_MIN_OBS_FOR_HISTORICAL = 100  # institutional floor — guarantees ≥5 tail obs at 95%


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
    risk_free_rate: float = 0.04,
) -> TailRiskResult:
    """Compute eVestment Section VII tail risk measures.

    Parameters
    ----------
    daily_returns : np.ndarray
        (T,) daily returns.
    risk_free_rate : float
        Annualized risk-free rate for STARR computation (default 4%).

    """
    n = len(daily_returns)
    if n < 30:
        return TailRiskResult()

    # Filter NaN/Inf before any computation (BUG-T2a-NaN)
    returns = daily_returns[np.isfinite(daily_returns)]
    n_finite = len(returns)
    if n_finite < 30:
        return TailRiskResult()

    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))

    # BUG-T3-SCIPY-ORDER: check std before computing moments to avoid scipy precision warnings
    if std < 1e-12:
        return TailRiskResult()

    skew = float(sp_stats.skew(returns))
    excess_kurt = float(sp_stats.kurtosis(returns))  # excess kurtosis

    # ── Parametric VaR (Normal) ───────────────────────────────────────
    var_p90 = _parametric_var(mean, std, 0.90)
    var_p95 = _parametric_var(mean, std, 0.95)
    var_p99 = _parametric_var(mean, std, 0.99)

    # ── Modified VaR (Cornish-Fisher) ─────────────────────────────────
    var_m95 = _cornish_fisher_var(mean, std, skew, excess_kurt, 0.95)
    var_m99 = _cornish_fisher_var(mean, std, skew, excess_kurt, 0.99)

    # BUG-T2c-CF-MONOTONIC: clamp 99 to be at least as severe as 95
    if abs(var_m99) < abs(var_m95):
        logger.warning(
            "cornish_fisher_non_monotonic",
            skew=skew,
            excess_kurt=excess_kurt,
            var_m95=var_m95,
            var_m99=var_m99,
        )
        # min() selects the more negative (worse loss)
        var_m99 = min(var_m99, var_m95)

    # ── Jarque-Bera Normality Test ────────────────────────────────────
    jb_stat = float(n_finite * (skew**2 / 6 + excess_kurt**2 / 24))
    jb_pvalue = float(sp_stats.chi2.sf(jb_stat, df=2))  # BUG-T2a-JBSF: survival function
    is_normal = jb_pvalue > 0.05

    # ── Historical tail metrics gate (BUG-T1) ─────────────────────────
    historical_tail_enabled = n_finite >= TAIL_MIN_OBS_FOR_HISTORICAL

    etl_95: float | None = None
    etl_m95: float | None = None
    etr_95: float | None = None
    starr: float | None = None
    rachev: float | None = None

    if historical_tail_enabled:
        # ── ETL / CVaR (Historical) ───────────────────────────────────
        sorted_returns = np.sort(returns)
        # BUG-T2a-CEIL: ceil instead of floor, matching cvar_service convention
        cutoff_95 = max(1, math.ceil(round(len(sorted_returns) * 0.05, 10)))

        etl_95 = float(np.mean(sorted_returns[:cutoff_95]))

        # Modified ETL: mean of returns below modified VaR threshold
        below_mvar = returns[returns <= var_m95]
        if len(below_mvar) > 0:
            etl_m95 = float(np.mean(below_mvar))
        else:
            # BUG-T2b-METL-FALLBACK: None instead of silent fallback to etl_95
            etl_m95 = None
            logger.info(
                "modified_etl_undefined_no_returns_below_threshold",
                var_m95=var_m95,
                n=n_finite,
            )

        # ── ETR (Expected Tail Return — right tail) ──────────────────
        # BUG-T2b-ETR-SYMMETRY: symmetric to ETL by construction
        upper_cutoff = len(sorted_returns) - cutoff_95
        etr_95 = float(np.mean(sorted_returns[upper_cutoff:]))

        # ── STARR Ratio (eVestment p.72) ─────────────────────────────
        # BUG-T2b-STARR-SIGN: use signed ETL, not abs()
        rf_daily = risk_free_rate / 252
        if etl_95 is not None and etl_95 < 0:
            expected_shortfall = -etl_95  # positive loss magnitude
            if expected_shortfall > 1e-12:
                starr = float((mean - rf_daily) / expected_shortfall)

        # ── Rachev Ratio (eVestment p.72) ────────────────────────────
        # BUG-T3-RACHEV-DEGRADED: proper None handling + logging
        if (
            etl_95 is not None
            and etr_95 is not None
            and etl_95 < 0
            and etr_95 > 1e-12
        ):
            rachev = float(etr_95 / -etl_95)
        elif etl_95 is not None and etr_95 is not None:
            logger.info(
                "rachev_undefined_non_negative_left_tail",
                etl_95=etl_95,
                etr_95=etr_95,
            )

    return TailRiskResult(
        var_parametric_90=var_p90,
        var_parametric_95=var_p95,
        var_parametric_99=var_p99,
        var_modified_95=var_m95,
        var_modified_99=var_m99,
        etl_95=etl_95,
        etl_modified_95=etl_m95,
        etr_95=etr_95,
        starr_ratio=starr,
        rachev_ratio=rachev,
        jarque_bera_stat=jb_stat,
        jarque_bera_pvalue=jb_pvalue,
        is_normal=is_normal,
    )

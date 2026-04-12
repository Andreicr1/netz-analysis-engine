"""Alternatives analytics -- correlation, capture ratios, crisis alpha, inflation beta.

Sync-pure module: zero I/O, zero imports from app.* or vertical_engines.*.
Config is injected as parameter -- never reads YAML, never uses @lru_cache.

All metrics are computed from NAV timeseries (nav_timeseries), benchmark
returns (benchmark_nav), and macro data (macro_data CPIAUCSL).  The worker
pre-fetches data and passes it to these pure functions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class AltAnalyticsResult:
    """Result of alternatives fund analytics."""

    equity_correlation_252d: float | None  # Rolling 252-day correlation with SPY
    downside_capture_1y: float | None  # Down-market capture ratio
    upside_capture_1y: float | None  # Up-market capture ratio
    crisis_alpha_score: float | None  # Performance during equity drawdowns > 10%
    calmar_ratio_3y: float | None  # 3Y annualized return / max drawdown
    inflation_beta: float | None  # Regression beta vs CPI changes
    inflation_beta_r2: float | None  # R^2 of inflation regression


@dataclass(frozen=True, slots=True)
class AltAnalyticsConfig:
    """Configuration for alternatives analytics."""

    min_observations: int = 120  # ~6 months of daily data
    correlation_window_days: int = 252  # 1 year rolling
    crisis_drawdown_threshold: float = -0.10  # 10% drawdown = crisis period
    min_crisis_days: int = 20  # Minimum crisis days to compute crisis alpha
    inflation_min_months: int = 12  # Minimum months for inflation beta regression
    inflation_min_r2: float = 0.02  # Minimum R^2 to consider result valid


def _ols_regression(
    y: np.ndarray,  # type: ignore[type-arg]
    x: np.ndarray,  # type: ignore[type-arg]
) -> tuple[float, float, float]:
    """Simple OLS: y = alpha + beta * x. Returns (alpha, beta, r_squared)."""
    X = np.column_stack([np.ones(len(x)), x])
    result = np.linalg.lstsq(X, y, rcond=None)
    coeffs = result[0]
    alpha, beta = float(coeffs[0]), float(coeffs[1])

    y_hat = X @ coeffs
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    return alpha, beta, r_squared


def compute_equity_correlation(
    fund_returns: np.ndarray,  # type: ignore[type-arg]
    benchmark_returns: np.ndarray,  # type: ignore[type-arg]
    window: int = 252,
    min_observations: int = 120,
) -> float | None:
    """Rolling correlation with equity benchmark (SPY).

    Returns Pearson correlation coefficient [-1.0, 1.0].
    For alternatives: LOWER correlation = BETTER diversification.
    """
    n = min(len(fund_returns), len(benchmark_returns))
    if n < min_observations:
        return None

    # Use the last `window` observations (or all if fewer)
    k = min(n, window)
    fund_tail = fund_returns[-k:]
    bench_tail = benchmark_returns[-k:]

    corr_matrix = np.corrcoef(fund_tail, bench_tail)
    corr = float(corr_matrix[0, 1])

    if np.isnan(corr):
        return None

    return round(corr, 4)


def compute_capture_ratios(
    fund_monthly: np.ndarray,  # type: ignore[type-arg]
    bench_monthly: np.ndarray,  # type: ignore[type-arg]
    min_periods: int = 3,
) -> tuple[float | None, float | None]:
    """Downside and upside capture ratios.

    Downside capture = fund return in down months / benchmark return in down months.
    Upside capture = fund return in up months / benchmark return in up months.

    Institutional interpretation:
    - Downside capture < 1.0 = fund loses LESS than benchmark in down months = GOOD.
    - Upside capture > 1.0 = fund gains MORE than benchmark in up months = GOOD.
    """
    n = min(len(fund_monthly), len(bench_monthly))
    if n < min_periods:
        return None, None

    fund_m = fund_monthly[-n:]
    bench_m = bench_monthly[-n:]

    down_mask = bench_m < 0
    up_mask = bench_m > 0

    downside_capture = None
    if down_mask.sum() >= min_periods:
        bench_down_mean = float(bench_m[down_mask].mean())
        if abs(bench_down_mean) > 1e-10:
            downside_capture = round(float(fund_m[down_mask].mean() / bench_down_mean), 4)

    upside_capture = None
    if up_mask.sum() >= min_periods:
        bench_up_mean = float(bench_m[up_mask].mean())
        if abs(bench_up_mean) > 1e-10:
            upside_capture = round(float(fund_m[up_mask].mean() / bench_up_mean), 4)

    return downside_capture, upside_capture


def compute_crisis_alpha(
    fund_daily: np.ndarray,  # type: ignore[type-arg]
    bench_daily: np.ndarray,  # type: ignore[type-arg]
    threshold: float = -0.10,
    min_crisis_days: int = 20,
) -> float | None:
    """Performance during equity drawdown periods > threshold.

    Crisis alpha = fund cumulative return - benchmark cumulative return
    during periods when benchmark is in drawdown > threshold.
    Positive = fund outperformed during crisis = diversification value.
    """
    n = min(len(fund_daily), len(bench_daily))
    if n < 60:
        return None

    fund_d = fund_daily[-n:]
    bench_d = bench_daily[-n:]

    # Compute benchmark cumulative drawdown
    bench_cum = np.cumprod(1 + bench_d)
    bench_peak = np.maximum.accumulate(bench_cum)
    bench_dd = (bench_cum - bench_peak) / bench_peak

    crisis_mask = bench_dd < threshold

    if crisis_mask.sum() < min_crisis_days:
        return None

    # Fund return during crisis vs benchmark return during crisis
    fund_crisis_return = float(np.prod(1 + fund_d[crisis_mask]) - 1)
    bench_crisis_return = float(np.prod(1 + bench_d[crisis_mask]) - 1)

    return round(fund_crisis_return - bench_crisis_return, 6)


def compute_calmar_ratio(
    return_3y_ann: float | None,
    max_drawdown_3y: float | None,
) -> float | None:
    """Calmar ratio: 3Y annualized return / abs(max drawdown 3Y).

    Higher = better risk-adjusted return.
    """
    if return_3y_ann is None or max_drawdown_3y is None:
        return None
    if max_drawdown_3y >= 0:  # No drawdown or positive (data error)
        return None
    return round(return_3y_ann / abs(max_drawdown_3y), 4)


def compute_inflation_beta(
    fund_monthly_returns: np.ndarray,  # type: ignore[type-arg]
    cpi_monthly_changes: np.ndarray,  # type: ignore[type-arg]
    config: AltAnalyticsConfig | None = None,
) -> tuple[float | None, float | None]:
    """Inflation beta via OLS: R_fund(t) = alpha + beta * delta_CPI(t).

    Positive beta = fund returns go up with inflation = inflation hedge.
    Returns (inflation_beta, r_squared) or (None, None) if insufficient data.
    """
    cfg = config or AltAnalyticsConfig()

    n = min(len(fund_monthly_returns), len(cpi_monthly_changes))
    if n < cfg.inflation_min_months:
        return None, None

    fund_m = fund_monthly_returns[-n:]
    cpi_m = cpi_monthly_changes[-n:]

    _, beta, r_sq = _ols_regression(fund_m, cpi_m)

    if r_sq < cfg.inflation_min_r2:
        return None, None

    return round(beta, 4), round(r_sq, 4)


def compute_alt_analytics(
    fund_dated_returns: list[tuple],
    benchmark_dated_returns: list[tuple],
    cpi_monthly_changes: list[tuple],
    return_3y_ann: float | None,
    max_drawdown_3y: float | None,
    config: AltAnalyticsConfig | None = None,
) -> AltAnalyticsResult:
    """Compute all alternatives analytics from dated returns and macro data.

    Aligns fund returns with benchmark by date (inner join), then runs
    correlation, capture ratios, crisis alpha, Calmar, and inflation beta.

    Args:
        fund_dated_returns: list of (date, return) tuples.
        benchmark_dated_returns: list of (date, return) tuples for SPY.
        cpi_monthly_changes: list of (date, delta_cpi) tuples (monthly).
        return_3y_ann: 3Y annualized return (already in fund_risk_metrics).
        max_drawdown_3y: 3Y max drawdown (already in fund_risk_metrics).
        config: analytics configuration.
    """
    cfg = config or AltAnalyticsConfig()

    # Build date-keyed dicts for alignment
    fund_by_date = {d: r for d, r in fund_dated_returns}
    bench_by_date = {d: r for d, r in benchmark_dated_returns}
    cpi_by_date = {d: r for d, r in cpi_monthly_changes}

    # Align daily fund returns with benchmark (inner join)
    daily_dates = sorted(set(fund_by_date.keys()) & set(bench_by_date.keys()))

    eq_corr = None
    downside_cap = None
    upside_cap = None
    crisis_alpha = None

    if len(daily_dates) >= cfg.min_observations:
        fund_daily = np.array([fund_by_date[d] for d in daily_dates])
        bench_daily = np.array([bench_by_date[d] for d in daily_dates])

        # Equity correlation
        eq_corr = compute_equity_correlation(
            fund_daily, bench_daily,
            window=cfg.correlation_window_days,
            min_observations=cfg.min_observations,
        )

        # Crisis alpha
        crisis_alpha = compute_crisis_alpha(
            fund_daily, bench_daily,
            threshold=cfg.crisis_drawdown_threshold,
            min_crisis_days=cfg.min_crisis_days,
        )

        # Capture ratios (monthly)
        # Resample daily to monthly by grouping on year-month
        fund_monthly_map: dict[tuple[int, int], list[float]] = {}
        bench_monthly_map: dict[tuple[int, int], list[float]] = {}
        for d, fr, br in zip(daily_dates, fund_daily, bench_daily, strict=True):
            key = (d.year, d.month)
            fund_monthly_map.setdefault(key, []).append(float(fr))
            bench_monthly_map.setdefault(key, []).append(float(br))

        # Convert daily to monthly compound returns
        common_months = sorted(set(fund_monthly_map.keys()) & set(bench_monthly_map.keys()))
        if len(common_months) >= 3:
            fund_monthly_arr = np.array([
                np.prod(1 + np.array(fund_monthly_map[m])) - 1
                for m in common_months
            ])
            bench_monthly_arr = np.array([
                np.prod(1 + np.array(bench_monthly_map[m])) - 1
                for m in common_months
            ])
            downside_cap, upside_cap = compute_capture_ratios(
                fund_monthly_arr, bench_monthly_arr,
            )

    # Calmar ratio (uses pre-computed 3Y data)
    calmar = compute_calmar_ratio(return_3y_ann, max_drawdown_3y)

    # Inflation beta (monthly)
    fund_monthly_by_date = {}
    for d, r in fund_dated_returns:
        key = (d.year, d.month)
        fund_monthly_by_date.setdefault(key, []).append(r)

    common_cpi_months = sorted(set(fund_monthly_by_date.keys()) & set(
        (d.year, d.month) for d in cpi_by_date
    ))

    infl_beta = None
    infl_r2 = None
    if len(common_cpi_months) >= cfg.inflation_min_months:
        fund_monthly_for_cpi = np.array([
            np.prod(1 + np.array(fund_monthly_by_date[m])) - 1
            for m in common_cpi_months
        ])
        # CPI changes indexed by (year, month)
        cpi_by_ym = {(d.year, d.month): r for d, r in cpi_monthly_changes}
        cpi_aligned = np.array([cpi_by_ym[m] for m in common_cpi_months])
        infl_beta, infl_r2 = compute_inflation_beta(
            fund_monthly_for_cpi, cpi_aligned, cfg,
        )

    return AltAnalyticsResult(
        equity_correlation_252d=eq_corr,
        downside_capture_1y=downside_cap,
        upside_capture_1y=upside_cap,
        crisis_alpha_score=crisis_alpha,
        calmar_ratio_3y=calmar,
        inflation_beta=infl_beta,
        inflation_beta_r2=infl_r2,
    )

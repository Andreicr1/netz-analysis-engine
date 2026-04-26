"""Return statistics service — eVestment Sections I-V.

Pure sync computation — no I/O, no DB access.  Receives daily return arrays
and optional benchmark arrays.  Computes 16 metrics:

Absolute Return:  arithmetic mean, geometric mean, gain mean, loss mean, gain/loss ratio
Absolute Risk:    gain std dev, loss std dev, downside deviation (MAR), semi deviation
Risk-Adjusted:    sterling ratio, omega ratio, treynor ratio, jensen alpha
Proficiency:      up percentage ratio, down percentage ratio
Regression:       R-squared

Reusable across entity_analytics, DD reports, fact sheets.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# ── Canonical risk-ratio constants ────────────────────────────────────────────
# A single source of truth for every quant consumer (risk_calc worker,
# screener quant metrics, DD report, fact sheets). Prior to S4 the Sharpe
# calculation diverged across modules: risk_calc used rf=0.04, the screener
# used rf=0.05 and a compounded annual-return formula, and a silent
# |r| < 0.5 filter masked data-quality issues. The three implementations
# produced different numbers for the same fund. We now converge on the
# arithmetic-mean daily-excess formula annualised by √252, with a minimum
# volatility guard to protect against stale NAV series.
TRADING_DAYS_PER_YEAR = 252
MIN_ANNUALIZED_VOL = 0.01  # 1% — stale NAV flattens σ and Sharpe diverges
DEFAULT_RISK_FREE_RATE = 0.04


def compute_sharpe_ratio(
    daily_returns: np.ndarray,  # type: ignore[type-arg]
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    *,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
    min_annualized_vol: float = MIN_ANNUALIZED_VOL,
) -> float | None:
    """Annualised Sharpe ratio from a daily return series.

    Formula (canonical, matches every Netz risk writer):

        excess    = daily_returns − rf / trading_days
        σ         = std(excess, ddof=1)
        σ_ann     = σ · √trading_days
        sharpe    = mean(excess) / σ · √trading_days
                  = annualised_excess_return / annualised_vol

    Returns ``None`` when:
      * the series is shorter than 2 observations (σ is undefined);
      * σ collapses to zero (constant series — stale NAV artefact);
      * the annualised vol is below ``min_annualized_vol`` (1 %). Yahoo
        Finance continues to emit prices for merged / delisted funds
        as a flat line, which would otherwise make Sharpe diverge.
    """
    if len(daily_returns) < 2:
        return None
    excess = daily_returns - risk_free_rate / trading_days_per_year
    vol = float(np.std(excess, ddof=1))
    if vol == 0 or not np.isfinite(vol):
        return None
    annualized_vol = vol * np.sqrt(trading_days_per_year)
    if annualized_vol < min_annualized_vol:
        return None
    return float(np.mean(excess) / vol * np.sqrt(trading_days_per_year))


def compute_sortino_ratio(
    daily_returns: np.ndarray,  # type: ignore[type-arg]
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    *,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
    min_annualized_vol: float = MIN_ANNUALIZED_VOL,
) -> float | None:
    """Annualised Sortino ratio with canonical Target Downside Deviation.

    Denominator: TDD = sqrt(mean(min(R - rf_daily, 0)²)) over full sample N.
    Source: Spec §3.4. Replaces prior std(downside_excess) formulation which
    was mathematically a "modified" Sortino that biased risk vs MAR.
    """
    if len(daily_returns) < 2:
        return None
    rf_daily = risk_free_rate / trading_days_per_year
    excess = daily_returns - rf_daily

    # Target Downside Deviation: shortfall² over full sample
    shortfall = np.minimum(excess, 0.0)
    tdd = float(np.sqrt(np.mean(shortfall**2)))

    if tdd == 0 or not np.isfinite(tdd):
        return None
    annualized_tdd = tdd * np.sqrt(trading_days_per_year)
    if annualized_tdd < min_annualized_vol:
        return None
    return float(np.mean(excess) / tdd * np.sqrt(trading_days_per_year))


@dataclass(frozen=True, slots=True)
class ReturnStatisticsResult:
    """eVestment Sections I-V return statistics."""

    # Absolute Return Measures
    arithmetic_mean_monthly: float | None = None
    geometric_mean_monthly: float | None = None
    avg_monthly_gain: float | None = None
    avg_monthly_loss: float | None = None
    gain_loss_ratio: float | None = None

    # Absolute Risk Measures
    gain_std_dev: float | None = None
    loss_std_dev: float | None = None
    downside_deviation: float | None = None  # MAR-based
    semi_deviation: float | None = None

    # Risk-Adjusted
    sterling_ratio: float | None = None
    omega_ratio: float | None = None  # MAR-based
    treynor_ratio: float | None = None  # requires beta
    jensen_alpha: float | None = None  # requires benchmark

    # Proficiency Ratios (relative)
    up_percentage_ratio: float | None = None
    down_percentage_ratio: float | None = None

    # Regression
    r_squared: float | None = None


def _to_monthly_returns(daily_returns: np.ndarray) -> np.ndarray:
    """Aggregate daily returns to monthly geometric returns.

    Assumes ~21 trading days per month.  Groups by 21-day blocks.
    """
    if len(daily_returns) < 21:
        return np.array([])

    n_months = len(daily_returns) // 21
    trimmed = daily_returns[: n_months * 21]
    reshaped = trimmed.reshape(n_months, 21)

    result: np.ndarray = np.prod(1 + reshaped, axis=1) - 1
    return result


def _annualize_monthly(monthly_mean: float) -> float:
    """Annualize a monthly return via compounding."""
    return (1 + monthly_mean) ** 12 - 1


def _compute_downside_deviation(returns: np.ndarray, mar: float = 0.0) -> float | None:
    """Downside deviation (MAR-based).

    Formula: sqrt(mean(min(R - MAR, 0)^2))  — uses N denominator, not N-1.
    """
    if len(returns) < 2:
        return None
    shortfall = np.minimum(returns - mar, 0.0)
    return float(np.sqrt(np.mean(shortfall**2)))


def _compute_semi_deviation(returns: np.ndarray) -> float | None:
    """Semi deviation — downside deviation using mean as threshold.

    Formula: sqrt(mean(min(R - mean(R), 0)^2))
    """
    if len(returns) < 2:
        return None
    mean_r = np.mean(returns)
    shortfall = np.minimum(returns - mean_r, 0.0)
    return float(np.sqrt(np.mean(shortfall**2)))


def _compute_sterling_ratio(
    daily_returns: np.ndarray,
) -> float | None:
    """Sterling ratio = ann_return / abs(avg_yearly_max_dd - 10%).

    Uses 3-year equivalent: average of annual max drawdowns.
    Falls back to single max DD if < 3 years of data.
    """
    if len(daily_returns) < 252:
        return None

    # Annualized return
    ann_return = float(np.mean(daily_returns)) * 252

    # Split into yearly chunks (252 trading days)
    n_years = len(daily_returns) // 252
    yearly_max_dds: list[float] = []

    for i in range(n_years):
        chunk = daily_returns[i * 252 : (i + 1) * 252]
        navs = np.cumprod(1 + chunk)
        running_max = np.maximum.accumulate(navs)
        dd_series = (navs - running_max) / np.where(running_max > 0, running_max, 1.0)
        yearly_max_dds.append(float(np.min(dd_series)))

    avg_max_dd = np.mean(yearly_max_dds)
    denominator = abs(avg_max_dd - 0.10)

    if denominator <= 0:
        return None

    return float(ann_return / denominator)


def _compute_omega_ratio(returns: np.ndarray, mar: float = 0.0) -> float | None:
    """Omega ratio = sum(max(R - MAR, 0)) / sum(abs(min(R - MAR, 0))).

    Threshold-dependent.
    """
    if len(returns) < 2:
        return None

    gains = np.sum(np.maximum(returns - mar, 0.0))
    losses = np.sum(np.abs(np.minimum(returns - mar, 0.0)))

    if losses < 1e-12:
        return None

    return float(gains / losses)


def compute_return_statistics(
    daily_returns: np.ndarray,
    benchmark_returns: np.ndarray | None = None,
    risk_free_rate: float = 0.04,
    mar: float = 0.0,
    config: dict[str, object] | None = None,
) -> ReturnStatisticsResult:
    """Compute eVestment Sections I-V return statistics.

    Parameters
    ----------
    daily_returns : np.ndarray
        (T,) daily returns for the entity.
    benchmark_returns : np.ndarray | None
        (T,) daily benchmark returns for relative metrics.
    risk_free_rate : float
        Annual risk-free rate (default 4%).
    mar : float
        Minimum acceptable return (monthly, for Omega/DD).
    config : dict | None
        Reserved for future per-tenant config injection.

    """
    if len(daily_returns) < 21:
        return ReturnStatisticsResult()

    monthly = _to_monthly_returns(daily_returns)

    if len(monthly) < 2:
        return ReturnStatisticsResult()

    # ── Absolute Return Measures ──────────────────────────────────────
    arith_mean = float(np.mean(monthly))
    geom_mean = float(np.prod(1 + monthly) ** (1 / len(monthly)) - 1)

    gains = monthly[monthly >= 0]
    losses = monthly[monthly < 0]

    avg_gain = float(np.mean(gains)) if len(gains) > 0 else None
    avg_loss = float(np.mean(losses)) if len(losses) > 0 else None
    gain_loss = abs(avg_gain / avg_loss) if avg_gain is not None and avg_loss is not None and abs(avg_loss) > 1e-12 else None

    # ── Absolute Risk Measures ────────────────────────────────────────
    gain_std = float(np.std(gains, ddof=1)) if len(gains) > 1 else None
    loss_std = float(np.std(losses, ddof=1)) if len(losses) > 1 else None
    dd_dev = _compute_downside_deviation(monthly, mar=mar)
    semi_dev = _compute_semi_deviation(monthly)

    # ── Risk-Adjusted ─────────────────────────────────────────────────
    sterling = _compute_sterling_ratio(daily_returns)
    omega = _compute_omega_ratio(monthly, mar=mar)

    treynor = None
    jensen = None
    r_sq = None
    up_pct = None
    down_pct = None

    # ── Relative metrics (require benchmark) ──────────────────────────
    if benchmark_returns is not None and len(benchmark_returns) == len(daily_returns):
        from scipy import stats as sp_stats

        bm_monthly = _to_monthly_returns(benchmark_returns)

        n_common = min(len(monthly), len(bm_monthly))
        if n_common >= 12:
            r = monthly[:n_common]
            bm = bm_monthly[:n_common]

            # Beta & R-squared via regression
            slope, intercept, r_value, _, _ = sp_stats.linregress(bm, r)
            beta = float(slope)
            r_sq = float(r_value**2)

            # Treynor: (ann_return - Rf) / beta — geometric annualization
            ann_return = _annualize_monthly(geom_mean)
            if abs(beta) > 1e-10:
                treynor = float((ann_return - risk_free_rate) / beta)

            # Jensen alpha: annualized, simple Rf (matches §3.1 and adjacent Treynor scale)
            rf_monthly = risk_free_rate / 12
            monthly_alpha = float(np.mean(r) - rf_monthly - beta * (np.mean(bm) - rf_monthly))
            jensen = monthly_alpha * 12

            # Proficiency ratios
            bm_up_mask = bm >= 0
            bm_down_mask = bm < 0

            if np.sum(bm_up_mask) > 0:
                up_pct = float(np.sum(r[bm_up_mask] > bm[bm_up_mask]) / np.sum(bm_up_mask) * 100)

            if np.sum(bm_down_mask) > 0:
                down_pct = float(np.sum(r[bm_down_mask] > bm[bm_down_mask]) / np.sum(bm_down_mask) * 100)

    return ReturnStatisticsResult(
        arithmetic_mean_monthly=round(arith_mean, 8),
        geometric_mean_monthly=round(geom_mean, 8),
        avg_monthly_gain=round(avg_gain, 8) if avg_gain is not None else None,
        avg_monthly_loss=round(avg_loss, 8) if avg_loss is not None else None,
        gain_loss_ratio=round(gain_loss, 4) if gain_loss is not None else None,
        gain_std_dev=round(gain_std, 8) if gain_std is not None else None,
        loss_std_dev=round(loss_std, 8) if loss_std is not None else None,
        downside_deviation=round(dd_dev, 8) if dd_dev is not None else None,
        semi_deviation=round(semi_dev, 8) if semi_dev is not None else None,
        sterling_ratio=round(sterling, 4) if sterling is not None else None,
        omega_ratio=round(omega, 4) if omega is not None else None,
        treynor_ratio=round(treynor, 4) if treynor is not None else None,
        jensen_alpha=round(jensen, 8) if jensen is not None else None,
        up_percentage_ratio=round(up_pct, 2) if up_pct is not None else None,
        down_percentage_ratio=round(down_pct, 2) if down_pct is not None else None,
        r_squared=round(r_sq, 4) if r_sq is not None else None,
    )

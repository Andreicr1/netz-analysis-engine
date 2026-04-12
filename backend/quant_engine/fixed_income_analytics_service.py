"""Fixed Income analytics — return-based style analysis regressions.

Sync-pure module: zero I/O, zero imports from app.* or vertical_engines.*.
Config is injected as parameter — never reads YAML, never uses @lru_cache.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class FIAnalyticsResult:
    """Result of fixed income regression analytics."""

    empirical_duration: float | None  # OLS beta vs Treasury yield changes
    duration_r_squared: float | None  # R² of duration regression
    credit_beta: float | None  # OLS beta vs credit spread changes
    credit_beta_r_squared: float | None  # R² of credit beta regression
    yield_proxy_12m: float | None  # Trailing 12m income return proxy
    duration_adj_drawdown: float | None  # max_drawdown_1y / max(duration, 1)


@dataclass(frozen=True, slots=True)
class FIRegressionConfig:
    """Configuration for FI regressions."""

    min_observations: int = 120  # ~6 months of daily data
    regression_window_days: int = 504  # 2 years (2 * 252)
    yield_change_series: str = "DGS10"  # FRED series for duration regression
    credit_spread_series: str = "BAA10Y"  # FRED series for credit beta regression
    min_r_squared: float = 0.05  # Minimum R² to consider result valid


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


def compute_empirical_duration(
    fund_returns: np.ndarray,  # type: ignore[type-arg]
    treasury_yield_changes: np.ndarray,  # type: ignore[type-arg]
    config: FIRegressionConfig | None = None,
) -> tuple[float | None, float | None]:
    """Empirical duration via OLS of fund returns vs Treasury yield changes.

    R_fund(t) = alpha + beta * delta_Y_10Y(t) + epsilon(t)
    empirical_duration = -beta

    Returns (empirical_duration, r_squared) or (None, None) if insufficient
    data or R² below threshold.
    """
    cfg = config or FIRegressionConfig()

    if len(fund_returns) < cfg.min_observations or len(treasury_yield_changes) < cfg.min_observations:
        return None, None

    n = min(len(fund_returns), len(treasury_yield_changes), cfg.regression_window_days)
    y = fund_returns[-n:]
    x = treasury_yield_changes[-n:]

    _, beta, r_sq = _ols_regression(y, x)

    if r_sq < cfg.min_r_squared:
        return None, None

    return -beta, r_sq


def compute_credit_beta(
    fund_returns: np.ndarray,  # type: ignore[type-arg]
    credit_spread_changes: np.ndarray,  # type: ignore[type-arg]
    config: FIRegressionConfig | None = None,
) -> tuple[float | None, float | None]:
    """Credit beta via OLS of fund returns vs credit spread changes.

    R_fund(t) = alpha + beta * delta_Spread(t) + epsilon(t)
    credit_beta = -beta

    Returns (credit_beta, r_squared) or (None, None) if insufficient data
    or R² below threshold.
    """
    cfg = config or FIRegressionConfig()

    if len(fund_returns) < cfg.min_observations or len(credit_spread_changes) < cfg.min_observations:
        return None, None

    n = min(len(fund_returns), len(credit_spread_changes), cfg.regression_window_days)
    y = fund_returns[-n:]
    x = credit_spread_changes[-n:]

    _, beta, r_sq = _ols_regression(y, x)

    if r_sq < cfg.min_r_squared:
        return None, None

    return -beta, r_sq


def compute_yield_proxy(monthly_returns: np.ndarray) -> float | None:  # type: ignore[type-arg]
    """Trailing 12-month income return proxy.

    Uses the mean of positive monthly returns over the last 12 months
    multiplied by 12 as a proxy for the carry/income component.

    Returns yield_proxy_12m as a decimal (e.g. 0.045 = 4.5%) or None
    if fewer than 12 months of data.
    """
    if len(monthly_returns) < 12:
        return None

    last_12 = monthly_returns[-12:]
    positive = last_12[last_12 > 0]

    if len(positive) == 0:
        return 0.0

    return float(np.mean(positive) * 12)


def compute_duration_adjusted_drawdown(
    max_drawdown_1y: float,
    empirical_duration: float | None,
) -> float | None:
    """Drawdown normalized by duration.

    duration_adj_drawdown = max_drawdown_1y / max(empirical_duration, 1.0)

    A fund with duration 8 and drawdown -8% scores -1.0% (excellent
    risk management). A fund with duration 2 and drawdown -5% scores
    -2.5% (worse per unit of risk assumed).
    """
    if empirical_duration is None:
        return None

    return max_drawdown_1y / max(empirical_duration, 1.0)

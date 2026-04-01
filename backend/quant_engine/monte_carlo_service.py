"""Monte Carlo simulation service — block bootstrap.

Pure sync computation — no I/O, no DB access.  Uses block bootstrap
(21-day blocks) to preserve autocorrelation structure.  Does NOT assume
normal distribution.

Reusable across entity_analytics, risk dashboards, DD reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class MonteCarloResult:
    """Bootstrapped Monte Carlo simulation result."""

    n_simulations: int
    statistic: str  # "max_drawdown" | "return" | "sharpe"
    percentiles: dict[str, float] = field(default_factory=dict)
    mean: float = 0.0
    median: float = 0.0
    std: float = 0.0
    historical_value: float = 0.0
    confidence_bars: list[dict[str, object]] = field(default_factory=list)


def _block_bootstrap_paths(
    daily_returns: np.ndarray,
    n_simulations: int,
    horizon: int,
    block_size: int = 21,
    rng: np.random.RandomState | None = None,
) -> np.ndarray:
    """Generate bootstrapped return paths via block bootstrap.

    Returns (n_simulations, horizon) array of simulated daily returns.
    """
    if rng is None:
        rng = np.random.RandomState()

    n = len(daily_returns)
    n_blocks = (horizon + block_size - 1) // block_size

    # Pre-compute all block start indices
    starts = rng.randint(0, n - block_size + 1, size=(n_simulations, n_blocks))

    paths = np.empty((n_simulations, n_blocks * block_size))
    for b in range(n_blocks):
        for s in range(n_simulations):
            paths[s, b * block_size : (b + 1) * block_size] = daily_returns[
                starts[s, b] : starts[s, b] + block_size
            ]

    return paths[:, :horizon]


def _compute_max_drawdown(nav_series: np.ndarray) -> float:
    """Max drawdown from a NAV index series."""
    running_max = np.maximum.accumulate(nav_series)
    drawdown = (nav_series - running_max) / np.where(running_max > 0, running_max, 1.0)
    return float(np.min(drawdown))


def _compute_statistic(
    simulated_returns: np.ndarray,
    statistic: str,
    risk_free_rate: float,
) -> np.ndarray:
    """Compute the chosen statistic for each simulation path.

    Parameters
    ----------
    simulated_returns : np.ndarray
        (n_simulations, horizon) daily returns.
    statistic : str
        One of "max_drawdown", "return", "sharpe".
    risk_free_rate : float
        Annualized risk-free rate.

    """
    n_sims = simulated_returns.shape[0]
    results = np.empty(n_sims)

    if statistic == "max_drawdown":
        for i in range(n_sims):
            nav = np.cumprod(1 + simulated_returns[i])
            results[i] = _compute_max_drawdown(nav)

    elif statistic == "return":
        # Total return over horizon
        for i in range(n_sims):
            results[i] = float(np.prod(1 + simulated_returns[i]) - 1)

    elif statistic == "sharpe":
        rf_daily = risk_free_rate / 252
        for i in range(n_sims):
            path = simulated_returns[i]
            excess = path - rf_daily
            mean_excess = np.mean(excess)
            std_excess = np.std(excess, ddof=1)
            if std_excess > 1e-12:
                results[i] = mean_excess / std_excess * np.sqrt(252)
            else:
                results[i] = 0.0

    else:
        msg = f"Unknown statistic: {statistic}"
        raise ValueError(msg)

    return results


def _historical_statistic(
    daily_returns: np.ndarray,
    statistic: str,
    risk_free_rate: float,
) -> float:
    """Compute the statistic on the actual historical series."""
    if statistic == "max_drawdown":
        nav = np.cumprod(1 + daily_returns)
        return _compute_max_drawdown(nav)

    if statistic == "return":
        return float(np.prod(1 + daily_returns) - 1)

    if statistic == "sharpe":
        rf_daily = risk_free_rate / 252
        excess = daily_returns - rf_daily
        mean_e = np.mean(excess)
        std_e = np.std(excess, ddof=1)
        if std_e > 1e-12:
            return float(mean_e / std_e * np.sqrt(252))
        return 0.0

    msg = f"Unknown statistic: {statistic}"
    raise ValueError(msg)


def run_monte_carlo(
    daily_returns: np.ndarray,
    n_simulations: int = 10_000,
    horizons: list[int] | None = None,
    statistic: str = "max_drawdown",
    risk_free_rate: float = 0.04,
    seed: int | None = None,
) -> MonteCarloResult:
    """Bootstrapped Monte Carlo preserving skewness and kurtosis.

    Uses block bootstrap (block_size=21 trading days) to preserve
    autocorrelation structure.  Does NOT assume normal distribution.

    Parameters
    ----------
    daily_returns : np.ndarray
        (T,) daily returns.
    n_simulations : int
        Number of simulation paths (default 10,000).
    horizons : list[int] | None
        Trading-day horizons for confidence bars.
        Default: [252, 756, 1260, 1764, 2520] (1Y-10Y).
    statistic : str
        "max_drawdown" | "return" | "sharpe".
    risk_free_rate : float
        Annualized risk-free rate for Sharpe computation.
    seed : int | None
        Random seed for reproducibility.

    """
    if len(daily_returns) < 42:
        return MonteCarloResult(
            n_simulations=0,
            statistic=statistic,
        )

    if horizons is None:
        horizons = [252, 756, 1260, 1764, 2520]

    rng = np.random.RandomState(seed)

    # Primary simulation at the longest horizon
    primary_horizon = max(horizons)
    paths = _block_bootstrap_paths(
        daily_returns, n_simulations, primary_horizon, block_size=21, rng=rng,
    )

    sim_stats = _compute_statistic(paths, statistic, risk_free_rate)

    # Percentile distribution
    pctl_keys = ["1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"]
    pctl_vals = [1, 5, 10, 25, 50, 75, 90, 95, 99]
    percentiles = {
        k: round(float(np.percentile(sim_stats, p)), 8)
        for k, p in zip(pctl_keys, pctl_vals, strict=True)
    }

    # Historical value
    hist_value = _historical_statistic(daily_returns, statistic, risk_free_rate)

    # Confidence bars across horizons
    confidence_bars: list[dict[str, object]] = []
    for h in horizons:
        h_paths = paths[:, :h] if h <= primary_horizon else _block_bootstrap_paths(
            daily_returns, n_simulations, h, block_size=21, rng=rng,
        )
        h_stats = _compute_statistic(h_paths, statistic, risk_free_rate)

        label = f"{h // 252}Y" if h >= 252 else f"{h}D"
        confidence_bars.append({
            "horizon": label,
            "horizon_days": h,
            "pct_5": round(float(np.percentile(h_stats, 5)), 8),
            "pct_10": round(float(np.percentile(h_stats, 10)), 8),
            "pct_25": round(float(np.percentile(h_stats, 25)), 8),
            "pct_50": round(float(np.percentile(h_stats, 50)), 8),
            "pct_75": round(float(np.percentile(h_stats, 75)), 8),
            "pct_90": round(float(np.percentile(h_stats, 90)), 8),
            "pct_95": round(float(np.percentile(h_stats, 95)), 8),
            "mean": round(float(np.mean(h_stats)), 8),
        })

    return MonteCarloResult(
        n_simulations=n_simulations,
        statistic=statistic,
        percentiles=percentiles,
        mean=round(float(np.mean(sim_stats)), 8),
        median=round(float(np.median(sim_stats)), 8),
        std=round(float(np.std(sim_stats, ddof=1)), 8),
        historical_value=round(hist_value, 8),
        confidence_bars=confidence_bars,
    )

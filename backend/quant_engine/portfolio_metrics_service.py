"""Portfolio-level metrics aggregation service.

Computes portfolio-level Sharpe, Sortino, max drawdown, and information ratio
from constituent fund data. Domain-agnostic — reusable across verticals.

Pure sync, config as parameter, no I/O (except DB reads for returns).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass(frozen=True)
class PortfolioMetrics:
    """Aggregated portfolio-level metrics."""

    sharpe_ratio: float | None = None
    sortino_ratio: float | None = None
    max_drawdown: float | None = None
    information_ratio: float | None = None
    annualized_return: float | None = None
    annualized_volatility: float | None = None
    n_observations: int = 0


def aggregate(
    portfolio_returns: np.ndarray,
    benchmark_returns: np.ndarray | None = None,
    risk_free_rate: float = 0.04,
    config: dict[str, Any] | None = None,
) -> PortfolioMetrics:
    """Compute portfolio-level metrics from daily returns.

    Parameters
    ----------
    portfolio_returns : np.ndarray
        Daily portfolio returns (T,).
    benchmark_returns : np.ndarray | None
        Daily benchmark returns for IR calculation.
    risk_free_rate : float
        Annual risk-free rate (default 4%).
    config : dict | None
        Optional overrides.

    """
    if len(portfolio_returns) == 0:
        return PortfolioMetrics()

    rf_daily = risk_free_rate / 252
    n = len(portfolio_returns)

    mean_r = float(np.mean(portfolio_returns))
    std_r = float(np.std(portfolio_returns, ddof=1))

    # Annualized
    ann_return = float(mean_r * 252)
    ann_vol = float(std_r * np.sqrt(252)) if std_r > 0 else None

    # Sharpe
    sharpe = float((mean_r - rf_daily) / std_r * np.sqrt(252)) if std_r > 0 else None

    # Sortino (downside deviation)
    downside = portfolio_returns[portfolio_returns < rf_daily] - rf_daily
    downside_std = float(np.std(downside, ddof=1)) if len(downside) > 1 else None
    sortino = (
        float((mean_r - rf_daily) / downside_std * np.sqrt(252))
        if downside_std and downside_std > 0
        else None
    )

    # Max drawdown
    cum = np.cumprod(1.0 + portfolio_returns)
    running_max = np.maximum.accumulate(cum)
    drawdowns = (cum - running_max) / np.where(running_max > 0, running_max, 1.0)
    max_dd = float(np.min(drawdowns))

    # Information ratio
    ir = None
    if benchmark_returns is not None and len(benchmark_returns) == n:
        excess = portfolio_returns - benchmark_returns
        excess_std = float(np.std(excess, ddof=1))
        if excess_std > 0:
            ir = float(np.mean(excess) / excess_std * np.sqrt(252))

    return PortfolioMetrics(
        sharpe_ratio=round(sharpe, 4) if sharpe is not None else None,
        sortino_ratio=round(sortino, 4) if sortino is not None else None,
        max_drawdown=round(max_dd, 6),
        information_ratio=round(ir, 4) if ir is not None else None,
        annualized_return=round(ann_return, 6),
        annualized_volatility=round(ann_vol, 6) if ann_vol is not None else None,
        n_observations=n,
    )

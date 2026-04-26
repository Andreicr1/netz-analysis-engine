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

    from quant_engine.return_statistics_service import compute_sortino_ratio

    rf_daily = risk_free_rate / 252
    n = len(portfolio_returns)

    mean_r = float(np.mean(portfolio_returns))
    std_r = float(np.std(portfolio_returns, ddof=1))

    # Annualized return: geometric (preserves true terminal wealth)
    cum_return = float(np.prod(1.0 + portfolio_returns))
    ann_return = float(cum_return ** (252 / n) - 1.0) if n > 0 else None

    # Annualized volatility: arithmetic by sqrt(252) (variance scales linearly under iid)
    ann_vol = float(std_r * np.sqrt(252)) if std_r > 0 else None

    # Sharpe
    sharpe = float((mean_r - rf_daily) / std_r * np.sqrt(252)) if std_r > 0 else None

    # Sortino — delegate to canonical TDD helper
    sortino = compute_sortino_ratio(portfolio_returns, risk_free_rate=risk_free_rate)

    # Max drawdown — delegate to canonical drawdown_service (F01)
    from quant_engine.drawdown_service import compute_drawdown_series

    navs = np.concatenate([[1.0], np.cumprod(1.0 + portfolio_returns)])
    dd_series = compute_drawdown_series(navs)
    max_dd = float(np.min(dd_series)) if len(dd_series) > 0 else 0.0

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

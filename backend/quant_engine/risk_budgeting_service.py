"""Risk budgeting service — eVestment p.43-44.

Pure sync computation — no I/O, no DB access.  Computes:

MCTR:   Marginal Contribution to Risk (volatility)
PCTR:   Percentage Contribution to Risk (sums to 100%)
MCETL:  Marginal Contribution to ETL (via finite difference)
PCETL:  Percentage Contribution to ETL (sums to 100%)
Implied Return:  STARR-optimal implied return per fund

Reusable across portfolio analytics, DD reports, risk dashboards.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class FundRiskBudget:
    """Per-fund risk budget decomposition."""

    block_id: str
    block_name: str
    weight: float
    mean_return: float
    mctr: float | None = None
    pctr: float | None = None
    mcetl: float | None = None
    pcetl: float | None = None
    implied_return_vol: float | None = None
    implied_return_etl: float | None = None
    difference_vol: float | None = None
    difference_etl: float | None = None


@dataclass(frozen=True, slots=True)
class RiskBudgetResult:
    """Portfolio-level risk budget decomposition."""

    portfolio_volatility: float
    portfolio_etl: float
    portfolio_starr: float | None = None
    funds: list[FundRiskBudget] = field(default_factory=list)


def _portfolio_etl(returns: np.ndarray, confidence: float = 0.95) -> float:
    """Historical ETL (CVaR) of a portfolio return series."""
    cutoff = int(len(returns) * (1 - confidence))
    cutoff = max(cutoff, 1)
    sorted_rets = np.sort(returns)
    return float(np.mean(sorted_rets[:cutoff]))


def compute_risk_budget(
    weights: np.ndarray,
    returns_matrix: np.ndarray,
    block_ids: list[str],
    block_names: list[str],
    risk_free_rate: float = 0.04,
    confidence: float = 0.95,
) -> RiskBudgetResult:
    """Compute eVestment risk budgeting metrics.

    Parameters
    ----------
    weights : np.ndarray
        (N,) portfolio weights.
    returns_matrix : np.ndarray
        (T, N) daily returns of N funds over T observations.
    block_ids : list[str]
        Block identifiers for each fund column.
    block_names : list[str]
        Display names for each block.
    risk_free_rate : float
        Annualized risk-free rate for STARR computation.
    confidence : float
        Confidence level for ETL (default 0.95).

    """
    T, N = returns_matrix.shape

    if T < 30 or N < 1:
        return RiskBudgetResult(portfolio_volatility=0.0, portfolio_etl=0.0)

    w = weights.copy()

    # Portfolio return series
    port_returns = returns_matrix @ w  # (T,)

    # ── Portfolio-level metrics ───────────────────────────────────────
    cov = np.cov(returns_matrix, rowvar=False, ddof=1)  # (N, N) or scalar if N=1
    if cov.ndim == 0:
        cov = cov.reshape(1, 1)
    port_var = float(w @ cov @ w)
    port_vol = float(np.sqrt(port_var)) if port_var > 0 else 1e-12

    port_etl = _portfolio_etl(port_returns, confidence)
    abs_port_etl = abs(port_etl) if abs(port_etl) > 1e-12 else 1e-12

    rf_daily = risk_free_rate / 252
    port_mean = float(np.mean(port_returns))
    port_starr = (port_mean - rf_daily) / abs_port_etl

    # ── MCTR: Marginal Contribution to Risk ──────────────────────────
    # MCTR_i = (Sigma @ w)_i / sigma_portfolio
    marginal = cov @ w  # (N,)
    mctr = marginal / port_vol  # (N,)

    # ── PCTR: Percentage Contribution to Risk ────────────────────────
    # PCTR_i = w_i * MCTR_i / sigma_portfolio  (sums to 100%)
    pctr = (w * mctr) / port_vol  # (N,)

    # ── MCETL: Marginal Contribution to ETL (finite difference) ──────
    epsilon = 1e-4
    mcetl = np.zeros(N)
    for i in range(N):
        w_up = w.copy()
        w_up[i] += epsilon
        port_up = returns_matrix @ w_up
        etl_up = _portfolio_etl(port_up, confidence)
        mcetl[i] = (etl_up - port_etl) / epsilon

    # ── PCETL: Percentage Contribution to ETL ────────────────────────
    # Euler decomposition: PCETL_i = w_i * MCETL_i / ETL_portfolio
    if abs_port_etl > 1e-12:
        pcetl = (w * mcetl) / port_etl  # port_etl is negative, mcetl is negative → positive
    else:
        pcetl = np.zeros(N)

    # ── Implied Returns ──────────────────────────────────────────────
    # Implied Return (vol) = STARR * MCTR_i (re-using portfolio STARR)
    # Implied Return (etl) = STARR * MCETL_i
    implied_vol = port_starr * mctr  # (N,)
    implied_etl = port_starr * mcetl  # (N,)

    # Per-fund mean returns
    fund_means = np.mean(returns_matrix, axis=0)  # (N,)

    # ── Build per-fund results ───────────────────────────────────────
    funds = []
    for i in range(N):
        funds.append(FundRiskBudget(
            block_id=block_ids[i],
            block_name=block_names[i],
            weight=round(float(w[i]), 6),
            mean_return=round(float(fund_means[i]), 8),
            mctr=round(float(mctr[i]), 8),
            pctr=round(float(pctr[i]), 6),
            mcetl=round(float(mcetl[i]), 8),
            pcetl=round(float(pcetl[i]), 6),
            implied_return_vol=round(float(implied_vol[i]), 8),
            implied_return_etl=round(float(implied_etl[i]), 8),
            difference_vol=round(float(fund_means[i] - implied_vol[i]), 8),
            difference_etl=round(float(fund_means[i] - implied_etl[i]), 8),
        ))

    return RiskBudgetResult(
        portfolio_volatility=round(port_vol, 8),
        portfolio_etl=round(port_etl, 8),
        portfolio_starr=round(port_starr, 6),
        funds=funds,
    )

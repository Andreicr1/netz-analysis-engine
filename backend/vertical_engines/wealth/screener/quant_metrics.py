"""Quant metrics computation for Layer 3 screening.

Pure functions — no I/O, no DB. Computes metrics from price history
(funds/equities) or JSONB attributes (bonds).

Score normalization uses percentile rank within peer group
(Lipper/Morningstar industry standard, not min-max).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class QuantMetrics:
    """Computed quant metrics from price history (funds/equities)."""

    sharpe_ratio: float
    annual_volatility_pct: float
    max_drawdown_pct: float
    pct_positive_months: float
    annual_return_pct: float
    data_period_days: int


@dataclass(frozen=True, slots=True)
class BondQuantMetrics:
    """Bond screening metrics from attributes (no timeseries needed)."""

    spread_vs_benchmark_bps: float
    liquidity_score: float
    duration_efficiency: float
    data_source: str  # csv | yahoo | manual


def compute_quant_metrics(
    history: pd.DataFrame,
    risk_free_rate_annual: float = 0.05,
) -> QuantMetrics | None:
    """Compute quant metrics from price history.

    Args:
        history: DataFrame with 'Close' column indexed by date.
        risk_free_rate_annual: Annual risk-free rate for Sharpe calculation.

    Returns:
        QuantMetrics or None if insufficient data.
    """
    if history is None or history.empty:
        return None

    close_col = "Close" if "Close" in history.columns else "Adj Close"
    if close_col not in history.columns:
        return None

    prices = history[close_col].dropna()
    if len(prices) < 60:  # Minimum ~3 months daily data
        return None

    data_period_days = (prices.index[-1] - prices.index[0]).days

    # Daily returns
    daily_returns = prices.pct_change().dropna()
    if daily_returns.empty:
        return None

    # Filter out unreasonable returns (data quality)
    daily_returns = daily_returns[daily_returns.abs() < 0.5]
    if len(daily_returns) < 30:
        return None

    # Annualized return
    total_return = (1 + daily_returns).prod() - 1
    years = data_period_days / 365.25
    if years <= 0:
        return None
    annual_return = (1 + total_return) ** (1 / years) - 1

    # Annualized volatility
    annual_vol = float(daily_returns.std() * np.sqrt(252))
    if annual_vol == 0 or math.isnan(annual_vol):
        return None

    # Sharpe ratio
    sharpe = (annual_return - risk_free_rate_annual) / annual_vol

    # Max drawdown
    cumulative = (1 + daily_returns).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    max_dd = float(drawdown.min()) * 100  # As percentage (negative)

    # Percentage of positive months
    monthly = daily_returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    pct_pos = float((monthly > 0).sum() / len(monthly)) if len(monthly) > 0 else 0.0

    # Validate outputs
    for val in (sharpe, annual_vol, max_dd, pct_pos, annual_return):
        if math.isnan(val) or math.isinf(val):
            return None

    return QuantMetrics(
        sharpe_ratio=round(float(sharpe), 4),
        annual_volatility_pct=round(annual_vol * 100, 4),
        max_drawdown_pct=round(max_dd, 4),
        pct_positive_months=round(pct_pos, 4),
        annual_return_pct=round(float(annual_return) * 100, 4),
        data_period_days=data_period_days,
    )


def compute_bond_metrics(attributes: dict[str, Any]) -> BondQuantMetrics | None:
    """Compute bond screening metrics from JSONB attributes.

    Args:
        attributes: Bond instrument JSONB attributes dict.

    Returns:
        BondQuantMetrics or None if insufficient data.
    """
    try:
        coupon = float(attributes.get("coupon_rate_pct", 0) or 0)
        outstanding = float(attributes.get("outstanding_usd", 0) or 0)
        face_value = float(attributes.get("face_value_usd", 0) or 0)
        duration = float(attributes.get("duration_years", 0) or 0)
        benchmark_yield = float(attributes.get("benchmark_yield_pct", 0) or 0)
    except (ValueError, TypeError):
        return None

    # Spread vs benchmark (basis points)
    spread_bps = (coupon - benchmark_yield) * 100

    # Liquidity score (0-1): outstanding / face_value as proxy
    if face_value > 0:
        liquidity = min(1.0, outstanding / face_value)
    else:
        liquidity = 0.0

    # Duration efficiency: yield per unit of duration
    if duration > 0:
        duration_eff = coupon / duration
    else:
        duration_eff = 0.0

    data_source = str(attributes.get("data_source", "csv"))

    return BondQuantMetrics(
        spread_vs_benchmark_bps=round(spread_bps, 2),
        liquidity_score=round(liquidity, 4),
        duration_efficiency=round(duration_eff, 4),
        data_source=data_source,
    )


def composite_score(
    metrics: dict[str, float],
    peer_values: dict[str, list[float]],
    weights: dict[str, float],
    lower_is_better: frozenset[str] | None = None,
    winsorize_pct: float = 0.01,
) -> float | None:
    """Composite score via percentile rank within peer group.

    Industry standard (Lipper/Morningstar): percentile rank is robust
    to outliers and provides bounded 0.0-1.0 output.

    Args:
        metrics: Dict of metric_name → value for this instrument.
        peer_values: Dict of metric_name → list of peer values.
        weights: Dict of metric_name → weight (must sum to ~1.0).
        lower_is_better: Metrics where lower = better (inverted rank).
        winsorize_pct: Winsorization percentile (default 1%).

    Returns:
        Composite score 0.0-1.0, or None if insufficient data.
    """
    if lower_is_better is None:
        lower_is_better = frozenset({
            "max_drawdown_pct", "pe_ratio_ttm", "debt_to_equity",
            "annual_volatility_pct",
        })

    score = 0.0
    total_weight = 0.0

    for metric, value in metrics.items():
        if value is None or metric not in weights:
            continue

        peers = peer_values.get(metric, [])
        peers_arr = np.array([p for p in peers if p is not None and not math.isnan(p)])
        if len(peers_arr) < 3:
            continue  # Insufficient peer data

        lo, hi = np.quantile(peers_arr, [winsorize_pct, 1 - winsorize_pct])
        if lo == hi:
            continue  # No variance in peer data

        clipped = float(np.clip(value, lo, hi))
        peers_clipped = np.clip(peers_arr, lo, hi)

        # Percentile rank
        rank = float(np.searchsorted(np.sort(peers_clipped), clipped)) / len(peers_clipped)

        if metric in lower_is_better:
            rank = 1.0 - rank

        score += weights[metric] * rank
        total_weight += weights[metric]

    if total_weight == 0:
        return None

    # Normalize by actual weight used (handle missing metrics gracefully)
    return round(score / total_weight, 4)

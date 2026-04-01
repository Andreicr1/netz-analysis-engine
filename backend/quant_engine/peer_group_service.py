"""Peer group ranking service — eVestment Section IV.

Pure sync computation — no I/O, no DB access.  Ranks a fund against
strategy-matched peers on configurable metrics.

Reusable across entity_analytics, screener, DD reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class PeerRanking:
    """Single-metric ranking within peer group."""

    metric_name: str
    value: float | None = None
    percentile: float = 0.0  # 0-100 (higher = better)
    quartile: int = 4  # 1-4
    peer_count: int = 0
    peer_median: float = 0.0
    peer_p25: float = 0.0
    peer_p75: float = 0.0


@dataclass(frozen=True, slots=True)
class PeerGroupResult:
    """Fund's rankings relative to strategy-matched peers."""

    strategy_label: str
    peer_count: int = 0
    rankings: list[PeerRanking] = field(default_factory=list)


# Metrics where higher values are better (ascending rank)
_HIGHER_IS_BETTER_DEFAULTS: dict[str, bool] = {
    "sharpe_1y": True,
    "sortino_1y": True,
    "return_1y": True,
    "return_3y_ann": True,
    "alpha_1y": True,
    "information_ratio_1y": True,
    "max_drawdown_1y": True,  # less negative is better → higher numeric value is better
    "max_drawdown_3y": True,
    "volatility_1y": False,  # lower is better
    "tracking_error_1y": False,
    "manager_score": True,
}


def _percentile_rank(value: float, peers: np.ndarray, higher_is_better: bool) -> float:
    """Compute percentile rank (0-100).

    For higher_is_better=True, higher percentile means better performance.
    For higher_is_better=False (e.g. max_drawdown), lower value → higher percentile.
    """
    if len(peers) == 0:
        return 50.0

    if higher_is_better:
        rank = float(np.sum(peers <= value)) / len(peers) * 100
    else:
        rank = float(np.sum(peers >= value)) / len(peers) * 100

    return round(rank, 2)


def _quartile_from_percentile(percentile: float) -> int:
    """Map percentile to quartile (1=best, 4=worst)."""
    if percentile >= 75:
        return 1
    if percentile >= 50:
        return 2
    if percentile >= 25:
        return 3
    return 4


def compute_peer_rankings(
    fund_metrics: dict[str, float | None],
    peer_metrics: list[dict[str, float | None]],
    strategy_label: str = "Unknown",
    metrics_to_rank: list[str] | None = None,
    higher_is_better: dict[str, bool] | None = None,
) -> PeerGroupResult:
    """Rank fund against strategy-matched peers (eVestment Section IV).

    Parameters
    ----------
    fund_metrics : dict
        The fund's metric values keyed by metric name.
    peer_metrics : list[dict]
        All peer fund metric dicts (same keys as fund_metrics).
    strategy_label : str
        Strategy label used for peer cohort.
    metrics_to_rank : list[str] | None
        Metrics to rank (default: sharpe, sortino, return, max_dd).
    higher_is_better : dict[str, bool] | None
        Override direction for each metric.

    """
    if metrics_to_rank is None:
        metrics_to_rank = [
            "sharpe_1y", "sortino_1y", "return_1y", "max_drawdown_1y",
            "volatility_1y", "alpha_1y", "manager_score",
        ]

    hib = {**_HIGHER_IS_BETTER_DEFAULTS, **(higher_is_better or {})}

    if len(peer_metrics) < 1:
        return PeerGroupResult(
            strategy_label=strategy_label,
            peer_count=0,
            rankings=[
                PeerRanking(metric_name=m, value=fund_metrics.get(m))
                for m in metrics_to_rank
            ],
        )

    rankings: list[PeerRanking] = []

    for metric in metrics_to_rank:
        fund_val = fund_metrics.get(metric)

        # Collect peer values (exclude None)
        peer_vals = [
            p[metric] for p in peer_metrics
            if p.get(metric) is not None
        ]
        peer_arr = np.array(peer_vals, dtype=float) if peer_vals else np.array([])

        if fund_val is None or len(peer_arr) == 0:
            rankings.append(PeerRanking(
                metric_name=metric,
                value=fund_val,
                peer_count=len(peer_arr),
                peer_median=round(float(np.median(peer_arr)), 6) if len(peer_arr) > 0 else 0.0,
                peer_p25=round(float(np.percentile(peer_arr, 25)), 6) if len(peer_arr) > 0 else 0.0,
                peer_p75=round(float(np.percentile(peer_arr, 75)), 6) if len(peer_arr) > 0 else 0.0,
            ))
            continue

        is_hib = hib.get(metric, True)
        pctl = _percentile_rank(fund_val, peer_arr, is_hib)
        quartile = _quartile_from_percentile(pctl)

        rankings.append(PeerRanking(
            metric_name=metric,
            value=round(fund_val, 6),
            percentile=pctl,
            quartile=quartile,
            peer_count=len(peer_arr),
            peer_median=round(float(np.median(peer_arr)), 6),
            peer_p25=round(float(np.percentile(peer_arr, 25)), 6),
            peer_p75=round(float(np.percentile(peer_arr, 75)), 6),
        ))

    return PeerGroupResult(
        strategy_label=strategy_label,
        peer_count=len(peer_metrics),
        rankings=rankings,
    )

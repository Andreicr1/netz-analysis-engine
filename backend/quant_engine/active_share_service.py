"""Active share service — eVestment p.73.

Pure sync computation — no I/O, no DB access.  Computes:

Active Share:       0.5 * sum(|w_fund,i - w_index,i|) over union of positions
Overlap:            1 - Active Share (complement)
Active Share Eff.:  excess_return / active_share (if both available)

Reusable across entity_analytics, DD reports, screener.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ActiveShareResult:
    """Active share metrics."""

    active_share: float  # 0-100
    overlap: float  # 0-100 (complement of active share)
    active_share_efficiency: float | None = None  # excess_return / active_share
    n_portfolio_positions: int = 0
    n_benchmark_positions: int = 0
    n_common_positions: int = 0


def compute_active_share(
    portfolio_weights: dict[str, float],
    benchmark_weights: dict[str, float],
    excess_return: float | None = None,
) -> ActiveShareResult:
    """Compute Active Share = 0.5 * sum(|w_fund,i - w_index,i|).

    Parameters
    ----------
    portfolio_weights : dict[str, float]
        {identifier: weight} for the fund.  Weights should sum to ~1.0.
    benchmark_weights : dict[str, float]
        {identifier: weight} for the benchmark index.
    excess_return : float | None
        Annualized excess return for efficiency calculation.

    """
    if not portfolio_weights or not benchmark_weights:
        return ActiveShareResult(
            active_share=100.0,
            overlap=0.0,
            n_portfolio_positions=len(portfolio_weights),
            n_benchmark_positions=len(benchmark_weights),
            n_common_positions=0,
        )

    # Union of all position identifiers
    all_ids = set(portfolio_weights.keys()) | set(benchmark_weights.keys())

    total_diff = 0.0
    for pid in all_ids:
        w_fund = portfolio_weights.get(pid, 0.0)
        w_bench = benchmark_weights.get(pid, 0.0)
        total_diff += abs(w_fund - w_bench)

    active_share = total_diff / 2.0 * 100  # 0-100 scale

    # Clamp to [0, 100]
    active_share = min(max(active_share, 0.0), 100.0)
    overlap = 100.0 - active_share

    # Common positions
    common = set(portfolio_weights.keys()) & set(benchmark_weights.keys())

    # Efficiency
    efficiency = None
    if excess_return is not None and active_share > 1e-6:
        efficiency = round(excess_return / (active_share / 100), 6)

    return ActiveShareResult(
        active_share=round(active_share, 4),
        overlap=round(overlap, 4),
        active_share_efficiency=efficiency,
        n_portfolio_positions=len(portfolio_weights),
        n_benchmark_positions=len(benchmark_weights),
        n_common_positions=len(common),
    )

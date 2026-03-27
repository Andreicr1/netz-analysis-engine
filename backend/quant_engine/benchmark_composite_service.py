"""Benchmark Composite NAV — weighted cross-product of block benchmark NAVs.

Analogous to portfolio_nav_synthesizer but for benchmarks: each AllocationBlock
has a benchmark_ticker → this service computes the blended benchmark NAV using
the same weighted-return compounding formula.

Pure sync, no I/O, config as parameter.

Algorithm:
    NAV_0 = 1000.0
    R_t   = Σ(w_block × r_benchmark_block_t)
    NAV_t = NAV_{t-1} × (1 + R_t)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any


@dataclass(frozen=True, slots=True)
class NavRow:
    """Single composite NAV data point."""

    nav_date: date
    nav: float
    daily_return: float


def compute_composite_nav(
    block_weights: dict[str, float],
    benchmark_navs: dict[str, list[dict[str, Any]]],
    inception_nav: float = 1000.0,
) -> list[NavRow]:
    """Compute composite benchmark NAV from block-weighted benchmark returns.

    Parameters
    ----------
    block_weights : dict[str, float]
        Mapping of block_id → target weight (should sum to ~1.0).
    benchmark_navs : dict[str, list[dict]]
        Mapping of block_id → list of {nav_date: date, return_1d: float}.
        Rows must be sorted by nav_date ascending.
    inception_nav : float
        Starting NAV value (default 1000.0).

    Returns
    -------
    list[NavRow]
        Composite NAV series, ordered by date ascending.

    """
    if not block_weights or not benchmark_navs:
        return []

    # Collect all returns by date across blocks
    returns_by_date: dict[date, dict[str, float]] = {}
    for block_id, rows in benchmark_navs.items():
        if block_id not in block_weights:
            continue
        for row in rows:
            d = row["nav_date"]
            r = row.get("return_1d")
            if r is not None:
                returns_by_date.setdefault(d, {})[block_id] = float(r)

    if not returns_by_date:
        return []

    weight_sum = sum(block_weights.values())
    if weight_sum <= 0:
        return []

    sorted_dates = sorted(returns_by_date.keys())
    current_nav = inception_nav
    result: list[NavRow] = []

    for d in sorted_dates:
        day_returns = returns_by_date[d]

        composite_return = 0.0
        active_weight = 0.0
        for block_id, w in block_weights.items():
            r = day_returns.get(block_id)
            if r is not None:
                composite_return += w * r
                active_weight += w

        # Renormalize if some blocks missing for this day
        if active_weight > 0 and active_weight < weight_sum * 0.999:
            composite_return = composite_return * (weight_sum / active_weight)

        current_nav = current_nav * (1.0 + composite_return)

        result.append(NavRow(
            nav_date=d,
            nav=current_nav,
            daily_return=composite_return,
        ))

    return result

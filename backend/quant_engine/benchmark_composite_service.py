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

import structlog

logger = structlog.get_logger(__name__)


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

    weight_sum = sum(block_weights.values())
    if weight_sum <= 0:
        return []

    # ── F01 fix: enforce latest-common-inception start date ─────────
    # A fixed-weight composite cannot exist before all constituents have
    # data.  Earlier dates would require phantom 100% weight on the
    # present blocks (invalid) or synthetic backfill (out of scope).
    block_min_dates: dict[str, date] = {}
    for block_id, rows in benchmark_navs.items():
        if block_id not in block_weights:
            continue
        if not rows:
            logger.warning(
                "composite_block_missing_navs",
                block_id=block_id,
                weight=block_weights.get(block_id),
            )
            continue
        dates_in_block = [row["nav_date"] for row in rows if row.get("return_1d") is not None]
        if dates_in_block:
            block_min_dates[block_id] = min(dates_in_block)

    # Require ALL weighted blocks to have NAVs; otherwise composite is undefined.
    blocks_with_data = set(block_min_dates.keys())
    blocks_required = set(block_weights.keys())
    if blocks_required - blocks_with_data:
        logger.warning(
            "composite_blocks_without_navs",
            missing=sorted(blocks_required - blocks_with_data),
        )
        return []

    latest_inception = max(block_min_dates.values())

    # Collect all returns by date across blocks, filtered to >= latest_inception
    returns_by_date: dict[date, dict[str, float]] = {}
    for block_id, rows in benchmark_navs.items():
        if block_id not in block_weights:
            continue
        for row in rows:
            d = row["nav_date"]
            if d < latest_inception:
                continue
            r = row.get("return_1d")
            if r is not None:
                returns_by_date.setdefault(d, {})[block_id] = float(r)

    if not returns_by_date:
        return []

    sorted_dates = sorted(returns_by_date.keys())
    current_nav = inception_nav
    result: list[NavRow] = []

    # ── F01 fix: minimum active-weight threshold for renormalization ──
    ACTIVE_WEIGHT_FLOOR_PCT = 0.5  # require >= 50% of weight present

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
            if active_weight < weight_sum * ACTIVE_WEIGHT_FLOOR_PCT:
                # Insufficient coverage — skip to avoid return-side
                # forward-fill amplification.
                logger.warning(
                    "composite_day_skipped_insufficient_active_weight",
                    nav_date=d,
                    active_weight=active_weight,
                    weight_sum=weight_sum,
                    active_pct=active_weight / weight_sum,
                )
                continue
            # Above threshold: renormalize with telemetry
            logger.info(
                "composite_day_renormalized",
                nav_date=d,
                active_weight=active_weight,
                weight_sum=weight_sum,
                active_pct=active_weight / weight_sum,
            )
            composite_return = composite_return * (weight_sum / active_weight)

        current_nav = current_nav * (1.0 + composite_return)

        result.append(NavRow(
            nav_date=d,
            nav=current_nav,
            daily_return=composite_return,
        ))

    return result

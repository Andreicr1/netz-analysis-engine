"""Portfolio construction — optimizer-driven fund selection within blocks.

Pure sync function. Config as parameter. No I/O.

Algorithm (primary — optimizer-driven):
1. Fund weights come directly from CLARABEL fund-level optimizer
2. Optimizer enforces block-group sum constraints + concentration limit + CVaR
3. Returns frozen PortfolioComposition with weights summing to 1.0

Algorithm (fallback — score-proportional):
1. Block weights come from CLARABEL block-level optimizer (or strategic targets)
2. Within each block, select top N funds by manager_score
3. Funds weighted proportionally to score within block weight
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from vertical_engines.wealth.model_portfolio.models import (
    FundWeight,
    OptimizationMeta,
    PortfolioComposition,
)

logger = structlog.get_logger()

# Default number of top funds per block (fallback path only)
_DEFAULT_TOP_N = 3


def construct_from_optimizer(
    profile: str,
    fund_weights: dict[str, float],
    fund_info: dict[str, dict[str, Any]],
    optimization_meta: OptimizationMeta,
) -> PortfolioComposition:
    """Construct portfolio from fund-level optimizer output.

    Parameters
    ----------
    profile : str
        Portfolio profile (conservative, moderate, growth).
    fund_weights : dict[str, float]
        Optimized per-fund weights from CLARABEL (instrument_id -> weight).
    fund_info : dict[str, dict]
        Fund metadata keyed by instrument_id with keys: fund_name, block_id, manager_score.
    optimization_meta : OptimizationMeta
        Solver metadata (CVaR, Sharpe, solver name).

    Returns
    -------
    PortfolioComposition
        Frozen dataclass with per-fund weights summing to 1.0.

    """
    all_weights: list[FundWeight] = []
    total = 0.0

    for fid, weight in fund_weights.items():
        if weight < 1e-6:
            continue  # skip near-zero allocations
        info = fund_info.get(fid, {})
        all_weights.append(
            FundWeight(
                instrument_id=uuid.UUID(fid),
                fund_name=info.get("fund_name", ""),
                block_id=info.get("block_id", ""),
                weight=round(weight, 6),
                score=info.get("manager_score", 0) or 0,
            ),
        )
        total += weight

    # Sort by block then weight descending for readability
    all_weights.sort(key=lambda fw: (fw.block_id, -fw.weight))

    return PortfolioComposition(
        profile=profile,
        funds=all_weights,
        total_weight=round(total, 6),
        optimization=optimization_meta,
    )


def construct(
    profile: str,
    universe_funds: list[dict[str, Any]],
    block_weights: dict[str, float],
    config: dict[str, Any] | None = None,
    optimization_meta: OptimizationMeta | None = None,
) -> PortfolioComposition:
    """Fallback: construct portfolio from block weights via score-proportional heuristic.

    Used ONLY when the fund-level optimizer cannot run (insufficient NAV data).
    For normal flow, use construct_from_optimizer() instead.

    Parameters
    ----------
    profile : str
        Portfolio profile (conservative, moderate, growth).
    universe_funds : list[dict]
        Approved funds with keys: instrument_id, fund_name, block_id, manager_score.
    block_weights : dict[str, float]
        Block-level weights (block_id -> weight, summing to ~1.0).
    config : dict | None
        Optional config with top_n_per_block override.
    optimization_meta : OptimizationMeta | None
        Solver metadata.

    """
    top_n = (config or {}).get("top_n_per_block", _DEFAULT_TOP_N)

    # Group funds by block
    funds_by_block: dict[str, list[dict[str, Any]]] = {}
    for fund in universe_funds:
        block = fund.get("block_id")
        if block and block in block_weights:
            funds_by_block.setdefault(block, []).append(fund)

    all_weights: list[FundWeight] = []
    total_allocated = 0.0

    for block_id, block_weight in block_weights.items():
        block_funds = funds_by_block.get(block_id, [])
        if not block_funds:
            logger.warning(
                "portfolio_block_empty",
                profile=profile,
                block_id=block_id,
                block_weight=block_weight,
            )
            continue

        # Sort by manager_score descending, take top N
        block_funds.sort(key=lambda f: f.get("manager_score", 0) or 0, reverse=True)
        selected = block_funds[:top_n]

        # Score-proportional weighting within block
        scores = [max(f.get("manager_score", 0) or 0, 0.01) for f in selected]
        score_total = sum(scores)

        for fund, score in zip(selected, scores, strict=False):
            fund_weight = block_weight * (score / score_total)
            all_weights.append(
                FundWeight(
                    instrument_id=uuid.UUID(str(fund["instrument_id"])),
                    fund_name=fund.get("fund_name", ""),
                    block_id=block_id,
                    weight=round(fund_weight, 6),
                    score=score,
                ),
            )
            total_allocated += fund_weight

    # Normalize weights to sum to exactly 1.0 if we have any allocation
    if total_allocated > 0 and abs(total_allocated - 1.0) > 1e-6:
        factor = 1.0 / total_allocated
        normalized = []
        for fw in all_weights:
            normalized.append(
                FundWeight(
                    instrument_id=fw.instrument_id,
                    fund_name=fw.fund_name,
                    block_id=fw.block_id,
                    weight=round(fw.weight * factor, 6),
                    score=fw.score,
                ),
            )
        all_weights = normalized
        total_allocated = 1.0

    return PortfolioComposition(
        profile=profile,
        funds=all_weights,
        total_weight=round(total_allocated, 6),
        optimization=optimization_meta,
    )

"""Portfolio construction — score-weighted fund selection within blocks.

Pure sync function. Config as parameter. No I/O.

Algorithm:
1. Strategic allocation defines weights per AllocationBlock
2. Within each block, select top N funds by manager_score
3. Funds weighted proportionally to score within block allocation
4. Returns frozen PortfolioComposition with weights summing to 1.0
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog

from vertical_engines.wealth.model_portfolio.models import FundWeight, PortfolioComposition

logger = structlog.get_logger()

# Default number of top funds per block
_DEFAULT_TOP_N = 3


def construct(
    profile: str,
    universe_funds: list[dict[str, Any]],
    strategic_allocation: dict[str, float],
    config: dict[str, Any] | None = None,
) -> PortfolioComposition:
    """Construct a model portfolio from universe assets.

    Parameters
    ----------
    profile : str
        Portfolio profile (conservative, moderate, growth).
    universe_funds : list[dict]
        Approved funds with keys: instrument_id, fund_name, block_id, manager_score.
    strategic_allocation : dict[str, float]
        Block weights summing to 1.0, e.g. {"equity_global": 0.4, "fixed_income": 0.3, ...}.
    config : dict | None
        Optional config with top_n_per_block override.

    Returns
    -------
    PortfolioComposition
        Frozen dataclass with per-fund weights summing to 1.0.
    """
    top_n = (config or {}).get("top_n_per_block", _DEFAULT_TOP_N)

    # Group funds by block
    funds_by_block: dict[str, list[dict[str, Any]]] = {}
    for fund in universe_funds:
        block = fund.get("block_id")
        if block and block in strategic_allocation:
            funds_by_block.setdefault(block, []).append(fund)

    all_weights: list[FundWeight] = []
    total_allocated = 0.0

    for block_id, block_weight in strategic_allocation.items():
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
                )
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
                )
            )
        all_weights = normalized
        total_allocated = 1.0

    return PortfolioComposition(
        profile=profile,
        funds=all_weights,
        total_weight=round(total_allocated, 6),
    )

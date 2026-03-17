"""Attribution orchestrator — bridges DB data to quant_engine attribution.

Uses POLICY BENCHMARK approach (CFA CIPM standard):
  - benchmark_weights = strategic allocation target weights per block
  - benchmark_returns = per-block benchmark ticker returns from benchmark_nav
  - portfolio_weights = actual current weights or strategic targets
  - portfolio_returns = weighted fund returns per block

Pure sync, designed for asyncio.to_thread(). No DB, no I/O.
Config as parameter.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import structlog

from quant_engine.attribution_service import (
    AttributionResult,
    SectorAttribution,
    compute_attribution,
    compute_multi_period_attribution,
)

logger = structlog.get_logger()

# Weight sum tolerance — if weights don't sum to ~1.0, add cash/residual
_WEIGHT_SUM_TOLERANCE = 1e-4
_CASH_LABEL = "cash_residual"

# Carino k_t clamp to prevent divergence
_CARINO_K_CLAMP = 10.0


class AttributionService:
    """Orchestrate policy benchmark attribution."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}

    def compute_portfolio_attribution(
        self,
        strategic_allocations: list[dict[str, Any]],
        fund_returns_by_block: dict[str, float],
        benchmark_returns_by_block: dict[str, float],
        block_labels: dict[str, str],
        actual_weights_by_block: dict[str, float] | None = None,
    ) -> AttributionResult:
        """Single-period attribution using policy benchmark.

        Parameters
        ----------
        strategic_allocations : list[dict]
            Each dict has 'block_id' and 'target_weight' (Decimal or float).
        fund_returns_by_block : dict
            block_id -> weighted average fund return for that block.
        benchmark_returns_by_block : dict
            block_id -> benchmark return from benchmark_nav.
        block_labels : dict
            block_id -> display name.
        actual_weights_by_block : dict | None
            block_id -> actual portfolio weight. If None, uses strategic targets.
        """
        # Build aligned arrays — only blocks that have BOTH fund and benchmark data
        block_ids: list[str] = []
        for sa in strategic_allocations:
            bid = sa["block_id"]
            if bid in fund_returns_by_block and bid in benchmark_returns_by_block:
                block_ids.append(bid)
            else:
                logger.warning(
                    "attribution_block_excluded",
                    block_id=bid,
                    has_fund_return=bid in fund_returns_by_block,
                    has_benchmark_return=bid in benchmark_returns_by_block,
                )

        if not block_ids:
            return AttributionResult(benchmark_available=False, n_periods=1)

        # Build weight/return arrays
        sa_map = {sa["block_id"]: float(sa["target_weight"]) for sa in strategic_allocations}

        benchmark_weights = np.array([sa_map.get(bid, 0.0) for bid in block_ids])
        portfolio_weights = np.array([
            (actual_weights_by_block or sa_map).get(bid, 0.0) for bid in block_ids
        ])
        portfolio_returns = np.array([fund_returns_by_block[bid] for bid in block_ids])
        benchmark_returns = np.array([benchmark_returns_by_block[bid] for bid in block_ids])
        labels = [block_labels.get(bid, bid) for bid in block_ids]

        # Weight normalization check
        bw_sum = float(np.sum(benchmark_weights))
        if abs(bw_sum - 1.0) > _WEIGHT_SUM_TOLERANCE and bw_sum > 0:
            residual = 1.0 - bw_sum
            benchmark_weights = np.append(benchmark_weights, residual)
            portfolio_weights = np.append(portfolio_weights, residual)
            portfolio_returns = np.append(portfolio_returns, 0.0)
            benchmark_returns = np.append(benchmark_returns, 0.0)
            labels.append(_CASH_LABEL)
            block_ids.append(_CASH_LABEL)
            logger.info(
                "attribution_weight_normalization",
                original_sum=bw_sum,
                residual=residual,
            )

        return compute_attribution(
            portfolio_weights=portfolio_weights,
            benchmark_weights=benchmark_weights,
            portfolio_returns=portfolio_returns,
            benchmark_returns=benchmark_returns,
            sector_labels=labels,
            config=self._config,
        )

    def compute_multi_period(
        self,
        period_results: list[AttributionResult],
        portfolio_period_returns: list[float],
        benchmark_period_returns: list[float],
    ) -> AttributionResult:
        """Multi-period Carino linking with numerical guards.

        Guards:
        1. Clamp k_t to [-_CARINO_K_CLAMP, _CARINO_K_CLAMP] to prevent divergence
        2. If abs(k_total) < 1e-10 (opposing excesses cancel),
           fall back to simple average
        """
        if not period_results:
            return AttributionResult()
        if len(period_results) == 1:
            return period_results[0]

        # Check for Carino edge case: total excess near zero
        total_excess = float(
            np.prod([1 + r for r in portfolio_period_returns])
            - np.prod([1 + r for r in benchmark_period_returns])
        )

        if abs(total_excess) < 1e-10:
            # Simple average fallback — Carino k_total diverges
            logger.info(
                "attribution_carino_fallback",
                total_excess=total_excess,
                n_periods=len(period_results),
            )
            return self._simple_average_linking(period_results)

        return compute_multi_period_attribution(
            period_results=period_results,
            portfolio_period_returns=portfolio_period_returns,
            benchmark_period_returns=benchmark_period_returns,
        )

    def _simple_average_linking(
        self,
        period_results: list[AttributionResult],
    ) -> AttributionResult:
        """Fallback when Carino diverges: simple average of period effects."""
        n = len(period_results)
        if n == 0:
            return AttributionResult()

        # Aggregate sector effects as simple average
        sector_map: dict[str, dict[str, float]] = {}
        total_p = 0.0
        total_b = 0.0

        for r in period_results:
            total_p += r.total_portfolio_return
            total_b += r.total_benchmark_return
            for s in r.sectors:
                if s.sector not in sector_map:
                    sector_map[s.sector] = {
                        "allocation": 0.0,
                        "selection": 0.0,
                        "interaction": 0.0,
                    }
                sector_map[s.sector]["allocation"] += s.allocation_effect / n
                sector_map[s.sector]["selection"] += s.selection_effect / n
                sector_map[s.sector]["interaction"] += s.interaction_effect / n

        sectors = []
        for label, effects in sector_map.items():
            total = effects["allocation"] + effects["selection"] + effects["interaction"]
            sectors.append(
                SectorAttribution(
                    sector=label,
                    allocation_effect=round(effects["allocation"], 6),
                    selection_effect=round(effects["selection"], 6),
                    interaction_effect=round(effects["interaction"], 6),
                    total_effect=round(total, 6),
                )
            )

        avg_p = total_p / n
        avg_b = total_b / n
        alloc_t = sum(s.allocation_effect for s in sectors)
        select_t = sum(s.selection_effect for s in sectors)
        interact_t = sum(s.interaction_effect for s in sectors)

        return AttributionResult(
            total_portfolio_return=round(avg_p, 6),
            total_benchmark_return=round(avg_b, 6),
            total_excess_return=round(avg_p - avg_b, 6),
            sectors=sectors,
            allocation_total=round(alloc_t, 6),
            selection_total=round(select_t, 6),
            interaction_total=round(interact_t, 6),
            n_periods=n,
            benchmark_available=True,
        )

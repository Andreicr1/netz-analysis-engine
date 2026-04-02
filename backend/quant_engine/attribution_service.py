"""Brinson-Fachler attribution with Carino multi-period linking.

Deferred implementation — requires benchmark constituent data that does not
currently exist (no Bloomberg/Morningstar feed). Returns empty result when
benchmark data is unavailable.

Pure sync, no I/O, config as parameter.

Formulas:
- Allocation effect: sum((w_p_i - w_b_i) * (r_b_i - R_b))  [Fachler adjustment]
- Selection effect:  sum(w_b_i * (r_p_i - r_b_i))
- Interaction effect: sum((w_p_i - w_b_i) * (r_p_i - r_b_i))
- Multi-period: Carino (1999) smoothing factors
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import structlog

logger = structlog.get_logger()

# Threshold for treating weight differences as zero (numerical stability)
_WEIGHT_EPSILON = 1e-6


@dataclass(frozen=True)
class SectorAttribution:
    """Attribution effects for a single sector/block."""

    sector: str
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    total_effect: float


@dataclass(frozen=True)
class AttributionResult:
    """Full attribution breakdown for a period."""

    total_portfolio_return: float = 0.0
    total_benchmark_return: float = 0.0
    total_excess_return: float = 0.0
    sectors: list[SectorAttribution] = field(default_factory=list)
    allocation_total: float = 0.0
    selection_total: float = 0.0
    interaction_total: float = 0.0
    n_periods: int = 0
    benchmark_available: bool = False


def compute_attribution(
    portfolio_weights: np.ndarray,
    benchmark_weights: np.ndarray | None,
    portfolio_returns: np.ndarray,
    benchmark_returns: np.ndarray | None,
    sector_labels: list[str] | None = None,
    config: dict[str, Any] | None = None,
) -> AttributionResult:
    """Compute single-period Brinson-Fachler attribution.

    Parameters
    ----------
    portfolio_weights : np.ndarray
        Portfolio weights per sector (N,).
    benchmark_weights : np.ndarray | None
        Benchmark weights per sector (N,). None = benchmark unavailable.
    portfolio_returns : np.ndarray
        Portfolio returns per sector (N,).
    benchmark_returns : np.ndarray | None
        Benchmark returns per sector (N,). None = benchmark unavailable.
    sector_labels : list[str] | None
        Labels for each sector.
    config : dict | None
        Optional config overrides.

    Returns
    -------
    AttributionResult
        Attribution breakdown. benchmark_available=False if no benchmark data.

    """
    if benchmark_weights is None or benchmark_returns is None:
        # No benchmark data — return empty result
        total_r_p = float(np.sum(portfolio_weights * portfolio_returns))
        return AttributionResult(
            total_portfolio_return=round(total_r_p, 6),
            benchmark_available=False,
            n_periods=1,
        )

    w_p = np.asarray(portfolio_weights, dtype=np.float64)
    w_b = np.asarray(benchmark_weights, dtype=np.float64)
    r_p = np.asarray(portfolio_returns, dtype=np.float64)
    r_b = np.asarray(benchmark_returns, dtype=np.float64)

    n = len(w_p)
    labels = sector_labels or [f"sector_{i}" for i in range(n)]

    # Total benchmark return
    R_b = float(np.sum(w_b * r_b))
    R_p = float(np.sum(w_p * r_p))

    sectors = []
    alloc_total = 0.0
    select_total = 0.0
    interact_total = 0.0

    for i in range(n):
        w_diff = w_p[i] - w_b[i]

        # Allocation effect with Fachler adjustment (relative benchmark)
        if abs(w_diff) < _WEIGHT_EPSILON:
            alloc_i = 0.0
        else:
            alloc_i = float(w_diff * (r_b[i] - R_b))

        # Selection effect
        select_i = float(w_b[i] * (r_p[i] - r_b[i]))

        # Interaction effect
        if abs(w_diff) < _WEIGHT_EPSILON:
            interact_i = 0.0
        else:
            interact_i = float(w_diff * (r_p[i] - r_b[i]))

        total_i = alloc_i + select_i + interact_i

        sectors.append(SectorAttribution(
            sector=labels[i],
            allocation_effect=round(alloc_i, 6),
            selection_effect=round(select_i, 6),
            interaction_effect=round(interact_i, 6),
            total_effect=round(total_i, 6),
        ))

        alloc_total += alloc_i
        select_total += select_i
        interact_total += interact_i

    return AttributionResult(
        total_portfolio_return=round(R_p, 6),
        total_benchmark_return=round(R_b, 6),
        total_excess_return=round(R_p - R_b, 6),
        sectors=sectors,
        allocation_total=round(alloc_total, 6),
        selection_total=round(select_total, 6),
        interaction_total=round(interact_total, 6),
        n_periods=1,
        benchmark_available=True,
    )


def compute_multi_period_attribution(
    period_results: list[AttributionResult],
    portfolio_period_returns: list[float],
    benchmark_period_returns: list[float],
) -> AttributionResult:
    """Link single-period attributions using Carino (1999) smoothing.

    Carino linking preserves additivity across periods:
    smoothing_factor_t = ln(1+r_t) / r_t  (for r_t != 0)
    """
    if not period_results:
        return AttributionResult()

    if len(period_results) == 1:
        return period_results[0]

    # Compound returns
    R_p_total = float(np.prod([1 + r for r in portfolio_period_returns]) - 1)
    R_b_total = float(np.prod([1 + r for r in benchmark_period_returns]) - 1)

    # Carino smoothing factors
    def _carino_factor(r: float) -> float:
        if abs(r) < 1e-10:
            return 1.0
        return float(np.log(1 + r) / r)

    k_total = _carino_factor(R_p_total - R_b_total) if abs(R_p_total - R_b_total) > 1e-10 else 1.0

    # Aggregate sector-level effects with Carino linking
    sector_map: dict[str, dict[str, float]] = {}

    for t, result in enumerate(period_results):
        r_p_t = portfolio_period_returns[t]
        r_b_t = benchmark_period_returns[t]
        excess_t = r_p_t - r_b_t

        k_t = _carino_factor(excess_t) if abs(excess_t) > 1e-10 else 1.0
        scale = k_t / k_total if abs(k_total) > 1e-10 else 1.0

        for s in result.sectors:
            if s.sector not in sector_map:
                sector_map[s.sector] = {
                    "allocation": 0.0,
                    "selection": 0.0,
                    "interaction": 0.0,
                }
            sector_map[s.sector]["allocation"] += s.allocation_effect * scale
            sector_map[s.sector]["selection"] += s.selection_effect * scale
            sector_map[s.sector]["interaction"] += s.interaction_effect * scale

    sectors = []
    for label, effects in sector_map.items():
        total = effects["allocation"] + effects["selection"] + effects["interaction"]
        sectors.append(SectorAttribution(
            sector=label,
            allocation_effect=round(effects["allocation"], 6),
            selection_effect=round(effects["selection"], 6),
            interaction_effect=round(effects["interaction"], 6),
            total_effect=round(total, 6),
        ))

    alloc_t = sum(s.allocation_effect for s in sectors)
    select_t = sum(s.selection_effect for s in sectors)
    interact_t = sum(s.interaction_effect for s in sectors)

    return AttributionResult(
        total_portfolio_return=round(R_p_total, 6),
        total_benchmark_return=round(R_b_total, 6),
        total_excess_return=round(R_p_total - R_b_total, 6),
        sectors=sectors,
        allocation_total=round(alloc_t, 6),
        selection_total=round(select_t, 6),
        interaction_total=round(interact_t, 6),
        n_periods=len(period_results),
        benchmark_available=True,
    )

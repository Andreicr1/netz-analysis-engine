"""Canonical Brinson-Fachler single-period attribution.

Pure deterministic function. No DB, no I/O, no concurrency. Decomposes a
fund's active return vs. a benchmark into allocation, selection, and
interaction effects at the sector level.

Formulation (Brinson, Hood, Beebower 1986; Fachler 1985):

    Allocation_s = (w_p[s] - w_b[s]) * (r_b[s] - R_B)
    Selection_s  = w_b[s] * (r_p[s] - r_b[s])
    Interaction_s = (w_p[s] - w_b[s]) * (r_p[s] - r_b[s])
    R_B          = Σ_s w_b[s] * r_b[s]

Missing sectors on either side are treated as zero weight / zero return
(the standard convention). When a fund holds a sector the benchmark does
not, the benchmark's aggregate return R_B is used as the sector's
benchmark return — this keeps allocation credit pure (the manager's bet
on that sector is compared to doing nothing different from the index).

The formula preserves the identity::

    R_P - R_B = Σ_s allocation_s + selection_s + interaction_s

within floating-point tolerance when both sides cover the same universe.
"""

from __future__ import annotations

from collections.abc import Mapping

from vertical_engines.wealth.attribution.models import (
    BrinsonResult,
    BrinsonSectorEffect,
)


def brinson_fachler(
    fund_weights: Mapping[str, float],
    fund_returns: Mapping[str, float],
    bench_weights: Mapping[str, float],
    bench_returns: Mapping[str, float],
) -> BrinsonResult:
    """Decompose active return into allocation, selection, interaction.

    Parameters
    ----------
    fund_weights, bench_weights
        Sector → weight (fractions summing to ~1.0). A missing sector is
        treated as zero weight.
    fund_returns, bench_returns
        Sector → period return (decimal, e.g. 0.03 for +3%). A missing
        sector return on the fund side is treated as zero. On the
        benchmark side, a missing sector falls back to the aggregate
        benchmark return R_B so that allocation credit for fund-only
        sectors is measured against "do nothing" (the index).
    """
    sectors = set(fund_weights) | set(bench_weights)

    aggregate_benchmark_return = sum(
        float(bench_weights.get(s, 0.0)) * float(bench_returns.get(s, 0.0))
        for s in sectors
    )

    allocation_total = 0.0
    selection_total = 0.0
    interaction_total = 0.0
    by_sector: list[BrinsonSectorEffect] = []

    for sector in sorted(sectors):
        w_p = float(fund_weights.get(sector, 0.0))
        w_b = float(bench_weights.get(sector, 0.0))
        r_p = float(fund_returns.get(sector, 0.0))
        # If the benchmark does not hold the sector, fall back to the
        # aggregate benchmark return so allocation captures the whole bet.
        r_b = float(bench_returns.get(sector, aggregate_benchmark_return))

        allocation = (w_p - w_b) * (r_b - aggregate_benchmark_return)
        selection = w_b * (r_p - r_b)
        interaction = (w_p - w_b) * (r_p - r_b)

        allocation_total += allocation
        selection_total += selection
        interaction_total += interaction

        by_sector.append(
            BrinsonSectorEffect(
                sector=sector,
                portfolio_weight=w_p,
                benchmark_weight=w_b,
                portfolio_return=r_p,
                benchmark_return=r_b,
                allocation_effect=allocation,
                selection_effect=selection,
                interaction_effect=interaction,
            ),
        )

    return BrinsonResult(
        allocation_effect=allocation_total,
        selection_effect=selection_total,
        interaction_effect=interaction_total,
        total_active_return=allocation_total + selection_total + interaction_total,
        by_sector=tuple(by_sector),
    )

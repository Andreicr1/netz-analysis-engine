"""Authoritative source of strategic weights for the ELITE ranking.

Phase 2 Session B Commit 6 investigation outcome
=================================================

**Question asked:** Where does the ``risk_calc`` ELITE ranking worker
read the strategic allocation weights that determine how many funds
of each strategy belong in the global top-300?

**Investigation run 2026-04-11 against the live local-dev schema:**

1. Table ``allocation_blocks`` exists (16 rows) but is a GLOBAL
   *taxonomy* table — ``block_id``, ``geography``, ``asset_class``,
   ``display_name``. It carries NO strategic weight.

2. Table ``strategic_allocation`` exists and holds per-profile,
   per-block target weights, but it is **tenant-scoped**
   (OrganizationScopedMixin). It is the tactical per-tenant view
   applied by Allocation Committee flows, not a global default.

3. The authoritative GLOBAL default lives in
   ``vertical_config_defaults`` where
   ``vertical = 'liquid_funds' AND config_type = 'portfolio_profiles'``.
   The JSONB has shape::

       {
         "profiles": {
           "moderate": {
             "strategic_allocation": {
               "na_equity_large":  {"target": 0.19, "min": ..., "max": ...},
               "fi_us_aggregate":  {"target": 0.12, ...},
               "alt_commodities":  {"target": 0.03, ...},
               ...
             },
             ...
           },
           "conservative": {...},
           "growth":       {...}
         }
       }

4. Profile ``moderate`` is the canonical balanced baseline. Phase 2
   Session B adopts it as the global default for ELITE ranking —
   ``conservative`` and ``growth`` are tilts away from the neutral
   center, not the center itself.

5. Aggregating the moderate profile's per-block targets by the
   parent ``asset_class`` column from ``allocation_blocks`` yields a
   clean top-level distribution that sums to exactly 1.00:

       equity        0.50
       fixed_income  0.33
       alternatives  0.12
       cash          0.05
                    -----
       total         1.00

**This is Form A per the brief** — the source already exists and is
canonical. This module is the single accessor function every ELITE
consumer must go through. Do NOT replicate the query elsewhere.

The ELITE ranking worker buckets funds by
``instruments_universe.asset_class`` — the same 4-way axis
(equity / fixed_income / alternatives / cash) — and allocates a
``round(300 * weight)`` target count per bucket.
"""
from __future__ import annotations

from typing import Final

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

#: The canonical profile name whose strategic allocation is adopted
#: as the ELITE-ranking global default. See module docstring §4.
CANONICAL_PROFILE: Final[str] = "moderate"

#: Vertical that owns the canonical portfolio_profiles config.
CANONICAL_VERTICAL: Final[str] = "liquid_funds"

#: Upper bound on tolerated deviation when the aggregated strategy
#: weights are asserted to sum to 1.0.
SUM_TOLERANCE: Final[float] = 1e-3


class EliteAllocationSourceError(RuntimeError):
    """Raised when the ELITE allocation source cannot be resolved."""


async def get_global_default_strategy_weights(
    db: AsyncSession,
) -> dict[str, float]:
    """Return the authoritative ``{asset_class: weight}`` map.

    Reads the moderate profile's ``strategic_allocation`` from
    ``vertical_config_defaults``, joins every block_id to its
    ``asset_class`` via ``allocation_blocks``, and sums targets per
    asset_class. The returned mapping sums to ~1.0 (±1e-3).

    Raises:
        EliteAllocationSourceError: if the config row is missing,
            the ``moderate`` profile is not present, or the
            aggregated weights do not sum to 1.0 within tolerance.
    """
    query = text(
        """
        WITH profile_alloc AS (
            SELECT
                jsonb_each.key AS block_id,
                (jsonb_each.value ->> 'target')::numeric AS target
            FROM vertical_config_defaults vcd,
                 LATERAL jsonb_each(
                     vcd.config
                         -> 'profiles'
                         -> :profile
                         -> 'strategic_allocation'
                 )
            WHERE vcd.vertical = :vertical
              AND vcd.config_type = 'portfolio_profiles'
        )
        SELECT
            b.asset_class AS asset_class,
            SUM(pa.target)::float8 AS total_weight
        FROM profile_alloc pa
        JOIN allocation_blocks b ON b.block_id = pa.block_id
        GROUP BY b.asset_class
        ORDER BY total_weight DESC
        """,
    )

    result = await db.execute(
        query,
        {"profile": CANONICAL_PROFILE, "vertical": CANONICAL_VERTICAL},
    )
    rows = result.mappings().all()

    if not rows:
        raise EliteAllocationSourceError(
            f"No strategic_allocation rows found for profile="
            f"{CANONICAL_PROFILE!r} in vertical_config_defaults "
            f"(vertical={CANONICAL_VERTICAL!r}). Seed the "
            f"portfolio_profiles config before running ELITE "
            f"ranking.",
        )

    weights: dict[str, float] = {
        row["asset_class"]: float(row["total_weight"]) for row in rows
    }
    total = sum(weights.values())

    if abs(total - 1.0) > SUM_TOLERANCE:
        raise EliteAllocationSourceError(
            f"ELITE strategy weights sum to {total:.6f}, "
            f"expected 1.0 ± {SUM_TOLERANCE}. "
            f"Check vertical_config_defaults for profile "
            f"{CANONICAL_PROFILE!r}. Per-class breakdown: {weights}",
        )

    logger.info(
        "elite_ranking.allocation_source_loaded",
        profile=CANONICAL_PROFILE,
        total_weight=total,
        buckets=weights,
    )
    return weights


def compute_target_counts(
    weights: dict[str, float],
    total_elite: int = 300,
) -> dict[str, int]:
    """Convert a weight map into per-strategy target counts.

    ``round(total_elite * weight)`` per bucket. The per-bucket sum
    may diverge from ``total_elite`` by rounding (±1 or ±2 over 4
    buckets), which is acceptable per the brief §"Computation
    algorithm" step 2. The ELITE worker logs the deviation.
    """
    return {
        asset_class: round(total_elite * weight)
        for asset_class, weight in weights.items()
    }

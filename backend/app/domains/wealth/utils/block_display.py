"""Humanized display names for the 18 canonical allocation blocks.

Seeded once from the A25 canonical template (migration 0153). Kept as
a hardcoded mapping rather than a DB column because the 18-block set
is intentionally stable and operator-facing labels rarely change. If
the canonical set changes, update ``_CANONICAL_BLOCKS`` in migration
0153 + this map in lockstep.
"""
from __future__ import annotations

from typing import Final

# Order matches A25 canonical template + allocation_blocks sort — the
# allocation response returns rows in this order so the donut chart
# and diff table align deterministically across profiles and orgs.
CANONICAL_BLOCK_ORDER: Final[tuple[str, ...]] = (
    "na_equity_large",
    "na_equity_growth",
    "na_equity_value",
    "na_equity_small",
    "dm_europe_equity",
    "dm_asia_equity",
    "em_equity",
    "fi_us_aggregate",
    "fi_us_treasury",
    "fi_us_short_term",
    "fi_us_high_yield",
    "fi_us_tips",
    "fi_ig_corporate",
    "fi_em_debt",
    "alt_real_estate",
    "alt_gold",
    "alt_commodities",
    "cash",
)

BLOCK_DISPLAY_NAMES: Final[dict[str, str]] = {
    "na_equity_large": "US Large-Cap Equity",
    "na_equity_growth": "US Growth Equity",
    "na_equity_value": "US Value Equity",
    "na_equity_small": "US Small-Cap Equity",
    "dm_europe_equity": "Developed Europe Equity",
    "dm_asia_equity": "Developed Asia Equity",
    "em_equity": "Emerging Markets Equity",
    "fi_us_aggregate": "US Aggregate Bond",
    "fi_us_treasury": "US Treasury",
    "fi_us_short_term": "US Short-Term Bond",
    "fi_us_high_yield": "US High Yield",
    "fi_us_tips": "US TIPS",
    "fi_ig_corporate": "US Investment-Grade Corporate",
    "fi_em_debt": "Emerging Markets Debt",
    "alt_real_estate": "Real Estate",
    "alt_gold": "Gold",
    "alt_commodities": "Broad Commodities",
    "cash": "Cash",
}


def humanize_block(block_id: str) -> str:
    """Return the operator-facing label for ``block_id``.

    Falls back to a title-cased form of the raw id for non-canonical
    blocks so unknown ids don't crash the allocation page render.
    """
    label = BLOCK_DISPLAY_NAMES.get(block_id)
    if label is not None:
        return label
    return block_id.replace("_", " ").title()

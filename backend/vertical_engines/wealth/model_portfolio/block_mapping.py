"""Strategy label to allocation block mapping for candidate discovery.

Hand-coded mapping from the ~37 ``strategy_label`` values found in
``instruments_universe.attributes`` to the 16 allocation blocks defined in
``calibration/config/blocks.yaml``.

Used by the construction advisor to discover candidate funds from the global
catalog when the user's portfolio has uncovered blocks.  The mapping only
needs to be "close enough" for advisory purposes — the user confirms the
block assignment when clicking "Add to [block]".
"""

from __future__ import annotations

# Each strategy_label maps to a *list* of candidate blocks (primary first).
# The advisor queries instruments_universe WHERE strategy_label IN (labels for block).
STRATEGY_LABEL_TO_BLOCKS: dict[str, list[str]] = {
    # Equity — US large cap
    "Large Blend": ["na_equity_large"],
    "Large Growth": ["na_equity_large", "na_equity_growth"],
    "Large Value": ["na_equity_large", "na_equity_value"],
    "Multi-Cap Core": ["na_equity_large"],
    "Long/Short Equity": ["alt_hedge_fund", "na_equity_large"],
    "Multi-Strategy": ["alt_hedge_fund"],
    "Market Neutral": ["alt_hedge_fund"],
    "Managed Futures": ["alt_managed_futures"],
    # Equity — US growth
    "Growth": ["na_equity_growth"],
    "Growth Equity": ["na_equity_growth"],
    "Technology": ["na_equity_growth"],
    # Equity — US value
    "Equity Income": ["na_equity_value"],
    "Dividend": ["na_equity_value"],
    # Equity — US small cap
    "Small Blend": ["na_equity_small"],
    "Small Growth": ["na_equity_small"],
    "Small Value": ["na_equity_small"],
    "Mid-Cap Blend": ["na_equity_small"],
    "Mid-Cap Growth": ["na_equity_small"],
    "Mid-Cap Value": ["na_equity_small"],
    # PR-A25 — catalog uses space-form variants alongside Morningstar's
    # hyphenated names. Keep both keys so legacy rows carrying the exact
    # hyphen-form label still map correctly.
    "Mid Growth": ["na_equity_small", "na_equity_growth"],
    "Mid Value": ["na_equity_small", "na_equity_value"],
    # Equity — Europe
    "Europe Stock": ["dm_europe_equity"],
    "Foreign Large Blend": ["dm_europe_equity"],
    "Foreign Large Growth": ["dm_europe_equity"],
    "Foreign Large Value": ["dm_europe_equity"],
    # Equity — Asia
    "Japan Stock": ["dm_asia_equity"],
    "Pacific/Asia ex-Japan Stock": ["dm_asia_equity"],
    "Asian Equity": ["dm_asia_equity"],
    # Equity — Emerging Markets
    "Diversified Emerging Mkts": ["em_equity"],
    "Emerging Markets": ["em_equity"],
    "China Region": ["em_equity"],
    "India Equity": ["em_equity"],
    "Latin America Stock": ["em_equity"],
    # Fixed Income — Aggregate
    "Intermediate Core Bond": ["fi_us_aggregate"],
    "Intermediate Core-Plus Bond": ["fi_us_aggregate"],
    "Fixed Income": ["fi_us_aggregate"],
    "Multisector Bond": ["fi_us_aggregate"],
    # Fixed Income — Treasury
    # PR-A25 — Short Government remaps to the new canonical fi_us_short_term
    # block (post-rename from fi_short_term). Long/Intermediate stay under
    # fi_us_treasury.
    "Short Government": ["fi_us_short_term"],
    "Long Government": ["fi_us_treasury"],
    "Intermediate Government": ["fi_us_treasury"],
    # Fixed Income — Short-term
    "Ultrashort Bond": ["fi_us_short_term"],
    # Fixed Income — TIPS
    "Inflation-Protected Bond": ["fi_us_tips"],
    "Inflation-Linked Bond": ["fi_us_tips"],
    # Fixed Income — High Yield
    "High Yield Bond": ["fi_us_high_yield"],
    "Private Credit": ["fi_us_high_yield"],
    "Bank Loan": ["fi_us_high_yield"],
    "Securitized Asset Fund": ["fi_us_high_yield"],
    # Fixed Income — EM Debt
    "Emerging Markets Bond": ["fi_em_debt"],
    "Emerging-Markets Local-Currency Bond": ["fi_em_debt"],
    # Alternatives — Real Estate
    "Real Estate": ["alt_real_estate"],
    "Real Estate Fund": ["alt_real_estate"],
    # Alternatives — Commodities
    "Commodities Broad Basket": ["alt_commodities"],
    # PR-A25 — catalog labels "Commodities" and "Commodities / Energy"
    # alongside the Morningstar "Commodities Broad Basket" canonical name.
    "Commodities": ["alt_commodities"],
    "Commodities / Energy": ["alt_commodities"],
    "Natural Resources": ["alt_commodities"],
    "Infrastructure": ["alt_commodities"],
    # Alternatives — Gold
    "Precious Metals": ["alt_gold"],
    # Cash
    "Money Market": ["cash"],
    "Liquidity Fund": ["cash"],
    "Cash Equivalent": ["cash"],
}


def blocks_for_strategy_label(strategy_label: str | None) -> list[str]:
    """Return candidate block IDs for a given strategy_label.

    Falls back to empty list if the label is not mapped.
    """
    if not strategy_label:
        return []
    return STRATEGY_LABEL_TO_BLOCKS.get(strategy_label, [])


def strategy_labels_for_block(block_id: str) -> list[str]:
    """Return all strategy_labels that map to a given block_id.

    Used when querying instruments_universe for candidates to fill a gap block.
    """
    labels: list[str] = []
    for label, blocks in STRATEGY_LABEL_TO_BLOCKS.items():
        if block_id in blocks:
            labels.append(label)
    return labels

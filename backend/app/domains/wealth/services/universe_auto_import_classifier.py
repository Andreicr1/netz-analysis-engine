"""Block classification for universe auto-import.

Deterministic cascade: strategy_label -> asset_class -> fund_type -> skip.
Consumes the canonical STRATEGY_LABEL_TO_BLOCKS mapping from block_mapping.py.
"""

from __future__ import annotations

from typing import Any

from vertical_engines.wealth.model_portfolio.block_mapping import blocks_for_strategy_label

_PRIVATE_FUND_TYPES = frozenset({
    "Hedge Fund",
    "Private Equity Fund",
    "Venture Capital Fund",
    "Securitized Asset Fund",
})

_HYBRID_PREFIXES = ("Allocation--", "Target Date", "Retirement")


def classify_block(instrument: dict[str, Any]) -> tuple[str | None, str]:
    """Return (block_id, decision_reason) for an instrument payload.

    The instrument dict must contain ``instrument_type``, ``asset_class``,
    and ``attributes`` (JSONB dict from instruments_universe).
    """
    attrs = instrument.get("attributes") or {}
    asset_class = instrument.get("asset_class", "")
    instrument_type = instrument.get("instrument_type", "")
    strategy_label = attrs.get("strategy_label")
    fund_type = attrs.get("fund_type")
    name = instrument.get("name", "")

    # Hybrid / multi-asset: skip
    if strategy_label and any(strategy_label.startswith(p) for p in _HYBRID_PREFIXES):
        return None, "hybrid_unsupported"
    if name and any(name.startswith(p) for p in _HYBRID_PREFIXES):
        return None, "hybrid_unsupported"

    # 1. Strategy label mapping (most granular)
    blocks = blocks_for_strategy_label(strategy_label)
    if blocks:
        return blocks[0], "strategy_label"

    # 2. Cash / money market
    if asset_class == "cash" or instrument_type == "money_market":
        return "cash", "asset_class_cash"

    # 3. Fixed income without strategy_label
    if asset_class == "fixed_income":
        return "fi_us_aggregate", "fallback_fi"

    # 4. Equity without strategy_label
    if asset_class == "equity":
        return "na_equity_large", "fallback_equity"

    # 5. Real estate fund type
    if fund_type == "Real Estate Fund":
        return "alt_real_estate", "fund_type_real_estate"

    # 6. Private fund types in liquid universe -- skip
    if fund_type in _PRIVATE_FUND_TYPES:
        return None, "private_fund_type"

    # 7. BDC -- skip (enters via Screener only)
    if instrument_type == "bdc":
        return None, "bdc_manual_only"

    # 8. Unclassified
    return None, "unclassified"

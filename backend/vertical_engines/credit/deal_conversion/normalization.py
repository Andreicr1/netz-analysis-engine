"""Deal conversion normalization helpers — amount parsing, strategy formatting, type derivation."""
from __future__ import annotations

import re
from typing import Any


def normalize_amount(val: object | None) -> float | None:
    """Best-effort parse of a monetary string (e.g. '$10M', '10,000,000')."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    text = str(val).replace(",", "").replace("$", "").strip()
    match = re.search(r"([\d.]+)\s*(k|m|mm|b|bn)?", text, re.IGNORECASE)
    if not match:
        return None
    num = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multipliers = {"k": 1e3, "m": 1e6, "mm": 1e6, "b": 1e9, "bn": 1e9}
    return num * multipliers.get(suffix, 1.0)


def title_case_strategy(value: str | None) -> str | None:
    """Normalize strategy_type to Title Case (e.g. 'ASSET_BACKED' → 'Asset Backed')."""
    if not value:
        return value
    return " ".join(w.capitalize() for w in value.replace("_", " ").split())


def derive_deal_type(research_output: dict[str, Any] | None) -> str:
    """Derive DealType enum value from research_output.deal_overview.instrument."""
    overview = (research_output or {}).get("deal_overview", {})
    instrument = (overview.get("instrument") or "").lower()
    if any(w in instrument for w in ("loan", "credit", "debt", "lending", "facility")):
        return "DIRECT_LOAN"
    if "fund" in instrument:
        return "FUND_INVESTMENT"
    if any(w in instrument for w in ("equity", "preferred", "stock")):
        return "EQUITY_STAKE"
    if any(w in instrument for w in ("note", "spv", "structured")):
        return "SPV_NOTE"
    return "DIRECT_LOAN"

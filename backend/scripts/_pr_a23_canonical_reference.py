"""PR-A23 canonical reference — known-correct (strategy_label, block_id)
mappings for the ~30 most-liquid US ETFs used by the classifier audit
(``pr_a23_classifier_audit.py``), the re-classification script
(``pr_a23_reclassify_auto_import.py``) and the strategy-label data
migration ``0151_fix_known_strategy_labels``.

Hardcoded from public fund fact sheets. Narrow, high-confidence patch.
NOT a substitute for a full upstream fix in the SEC / ESMA ingestion
workers — see PR-A23 prompt "Out of scope".

VTEB/MUB map to ``None`` until the operator decides whether to split
muni from aggregate — ``fi_us_aggregate_muni`` is intentionally NOT in
``allocation_blocks`` in this PR.
"""
from __future__ import annotations

# ticker -> (canonical_strategy_label, canonical_block_id_or_None)
CANONICAL_REFERENCE: dict[str, tuple[str, str | None]] = {
    # Equity — US Blend
    "SPY": ("Large Blend", "na_equity_large"),
    "IVV": ("Large Blend", "na_equity_large"),
    "VOO": ("Large Blend", "na_equity_large"),
    "VTI": ("Large Blend", "na_equity_large"),
    # Equity — US Growth
    "QQQ": ("Large Growth", "na_equity_growth"),
    "VUG": ("Large Growth", "na_equity_growth"),
    "IWF": ("Large Growth", "na_equity_growth"),
    # Equity — US Value
    "VTV": ("Large Value", "na_equity_value"),
    "IWD": ("Large Value", "na_equity_value"),
    # Equity — US Small
    "IWM": ("Small Blend", "na_equity_small"),
    "VB": ("Small Blend", "na_equity_small"),
    # Equity — International Developed
    "EFA": ("Foreign Large Blend", "dm_europe_equity"),
    "VEA": ("Foreign Large Blend", "dm_europe_equity"),
    "IEFA": ("Foreign Large Blend", "dm_europe_equity"),
    # Equity — Emerging Markets
    "EEM": ("Diversified Emerging Mkts", "em_equity"),
    "VWO": ("Diversified Emerging Mkts", "em_equity"),
    "IEMG": ("Diversified Emerging Mkts", "em_equity"),
    # Fixed Income — Aggregate
    "AGG": ("Intermediate Core Bond", "fi_us_aggregate"),
    "BND": ("Intermediate Core Bond", "fi_us_aggregate"),
    # Fixed Income — Treasury / Government
    "IEF": ("Intermediate Government", "fi_us_treasury"),
    "TLT": ("Long Government", "fi_us_treasury"),
    "SHY": ("Short Government", "fi_us_treasury"),
    "GOVT": ("Intermediate Government", "fi_us_treasury"),
    # Fixed Income — Muni (block_id=None until operator decides to split
    # muni from aggregate; see PR-A23 prompt Section A note).
    "VTEB": ("Muni National Interm", None),
    "MUB": ("Muni National Interm", None),
    # Fixed Income — TIPS
    "TIP": ("Inflation-Protected Bond", "fi_us_tips"),
    "SCHP": ("Inflation-Protected Bond", "fi_us_tips"),
    # Fixed Income — High Yield
    "HYG": ("High Yield Bond", "fi_us_high_yield"),
    "JNK": ("High Yield Bond", "fi_us_high_yield"),
    # Fixed Income — IG Corporate (``Corporate Bond`` is NOT in
    # STRATEGY_LABEL_TO_BLOCKS as of 2026-04-18; listed here so the audit
    # surfaces the coverage gap. Once added to block_mapping.py the
    # reclassify script will route LQD correctly.)
    "LQD": ("Corporate Bond", "fi_ig_corporate"),
    # Alternatives — Gold / Precious Metals
    "GLD": ("Precious Metals", "alt_gold"),
    "IAU": ("Precious Metals", "alt_gold"),
    # Alternatives — Broad Commodities
    "DBC": ("Commodities Broad Basket", "alt_commodities"),
    "GSG": ("Commodities Broad Basket", "alt_commodities"),
    # Alternatives — Real Estate
    "VNQ": ("Real Estate", "alt_real_estate"),
}


__all__ = ["CANONICAL_REFERENCE"]

"""PR-A23 canonical reference — known-correct (strategy_label, block_id)
mappings for the ~30 most-liquid US ETFs used by the classifier audit
(``pr_a23_classifier_audit.py``), the re-classification script
(``pr_a23_reclassify_auto_import.py``) and the strategy-label data
migration ``0151_fix_known_strategy_labels``.

Hardcoded from public fund fact sheets. Narrow, high-confidence patch.
NOT a substitute for a full upstream fix in the SEC / ESMA ingestion
workers — see PR-A23 prompt "Out of scope".

PR-A24 (2026-04-18): VTEB / MUB removed from ``CANONICAL_REFERENCE``
because US muni bonds are now categorically excluded — see
``EXCLUDED_STRATEGY_LABELS`` below. The canonical map only tracks
instruments that have a valid destination block in
``allocation_blocks``; exclusion is handled on a separate, mandate-level
channel.
"""
from __future__ import annotations

# ticker -> (canonical_strategy_label, canonical_block_id)
#
# Every entry must have a non-None block_id. Muni tickers that used to
# map to ``(label, None)`` moved to EXCLUDED_STRATEGY_LABELS below.
CANONICAL_REFERENCE: dict[str, tuple[str, str]] = {
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


# PR-A24 — mandate-level asset-class exclusion.
#
# US muni bonds are categorically excluded from the Netz wealth engine.
# Rationale (Andrei, 2026-04-18):
#
#   - The tax-exempt premium that makes muni economically attractive
#     applies only to US taxpayers.
#   - Netz's client base is international portfolios (Brazilian PFICs /
#     offshore structures) that do not benefit from US muni tax
#     treatment.
#   - Holding muni in an international structure introduces tax
#     inefficiency vs. direct Treasury exposure at equivalent
#     duration/credit.
#   - No plan to create ``fi_us_aggregate_muni`` block.
#
# Exclusion is mandate-level, not a classification fallback:
# ``universe_auto_import_classifier`` returns
# ``(None, "excluded_asset_class")`` early — distinct from
# ``needs_human_review`` — and the service skips row insertion in
# ``instruments_org`` entirely. The global ``instruments_universe`` row
# is preserved (catalog keeps everything) with an
# ``attributes.strategic_excluded_reason`` audit breadcrumb.
#
# Muni labels were derived from Morningstar / Lipper muni categories
# seen in the catalog. Verify coverage with::
#
#     SELECT DISTINCT attributes->>'strategy_label'
#       FROM instruments_universe
#      WHERE attributes->>'strategy_label' ILIKE '%muni%';
#
# Extend this set if new muni labels surface.
EXCLUDED_STRATEGY_LABELS: frozenset[str] = frozenset({
    # Generic label used by the upstream ingestion worker when no
    # Morningstar-level granularity is available (dev DB: 328 rows).
    "Municipal Bond",
    # Morningstar muni categories — surface post-0151 label corrections
    # and once the upstream ingestion starts emitting granular labels.
    "Muni National Interm",
    "Muni National Short",
    "Muni National Long",
    "Muni Single State Interm",
    "Muni Single State Short",
    "Muni Single State Long",
    "High Yield Muni",
    "Muni California Intermediate",
    "Muni California Long",
    "Muni New York Intermediate",
    "Muni New York Long",
    "Muni Target Maturity",
})


__all__ = ["CANONICAL_REFERENCE", "EXCLUDED_STRATEGY_LABELS"]

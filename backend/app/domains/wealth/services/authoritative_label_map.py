"""Authoritative-source ``strategy_label`` normalization for PR-A26.3.2.

Maps raw values emitted by the SEC/ESMA authoritative tables
(``sec_money_market_funds``, ``sec_etfs``, ``sec_bdcs``, ``esma_funds``)
to canonical ``strategy_label`` keys defined in
``backend/vertical_engines/wealth/model_portfolio/block_mapping.py``.

Used by ``backend/scripts/refresh_authoritative_labels.py`` to overwrite
the contaminated ``instruments_universe.attributes->>'strategy_label'``
values produced by the Tiingo description cascade.

Invariant: every distinct value found in the four authoritative source
tables (verified against dev DB on 2026-04-18) maps to either:

* a key present in ``STRATEGY_LABEL_TO_BLOCKS``, or
* ``None`` with an explicit ``reason`` string indicating operator review.

Unit tests in ``backend/tests/wealth/services/test_authoritative_label_map.py``
pin this invariant.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.vertical_engines.wealth.model_portfolio.block_mapping import (
    STRATEGY_LABEL_TO_BLOCKS,
)


@dataclass(frozen=True)
class LabelMapping:
    """Result of normalizing an authoritative source value.

    ``label`` is ``None`` when the source value is recognized but
    intentionally not mapped to any block (operator must review).
    """

    label: str | None
    reason: str


# ---------------------------------------------------------------------------
# Section B.1 — SEC Money Market Funds (sec_money_market_funds.mmf_category)
# ---------------------------------------------------------------------------
# Verified against dev DB 2026-04-18: 4 distinct categories, all mapped to
# canonical MMF labels already present in block_mapping.py (cash block).
MMF_CATEGORY_TO_LABEL: dict[str, str] = {
    "Government": "Government Money Market",
    "Prime": "Prime Money Market",
    "Other Tax Exempt": "Tax-Exempt Money Market",
    "Single State": "Single State Money Market",
}


# ---------------------------------------------------------------------------
# Section B.2 — SEC ETFs (sec_etfs.strategy_label)
# ---------------------------------------------------------------------------
# Verified against dev DB 2026-04-18 (30 distinct values across 546 ETFs).
# Counts annotated in comments. ``None`` entries flag operator review.
SEC_ETF_LABEL_NORMALIZE: dict[str, str | None] = {
    "Intermediate-Term Bond": "Intermediate-Term Bond",  # 61 — new canonical
    "Sector Equity": "Sector Equity",  # 58 — new canonical
    "International Equity": "International Equity",  # 56 — new canonical
    "Large Blend": "Large Blend",  # 50 — existing
    "Investment Grade Bond": "Investment Grade Bond",  # 37 — new canonical
    "Municipal Bond": None,  # 35 — A24 categorically excludes US muni
    "Small Blend": "Small Blend",  # 34 — existing
    "High Yield Bond": "High Yield Bond",  # 30 — existing
    "Emerging Markets Equity": "Emerging Markets Equity",  # 27 — new canonical
    "ESG/Sustainable Equity": "ESG/Sustainable Equity",  # 26 — new canonical
    "Large Value": "Large Value",  # 24 — existing
    "Large Growth": "Large Growth",  # 22 — existing
    "Mid Blend": "Mid Blend",  # 14 — new canonical
    "Government Bond": "Government Bond",  # 12 — new canonical
    "Balanced": "Balanced",  # 12 — new canonical
    "Real Estate": "Real Estate",  # 7 — existing
    "Structured Credit": "Structured Credit",  # 6 — new canonical
    "ESG/Sustainable Bond": "ESG/Sustainable Bond",  # 6 — new canonical
    "Precious Metals": "Precious Metals",  # 5 — existing
    "Emerging Markets Debt": "Emerging Markets Debt",  # 4 — new canonical
    "Small Value": "Small Value",  # 3 — existing
    "Small Growth": "Small Growth",  # 3 — existing
    "Mid Value": "Mid Value",  # 3 — existing
    "Mid Growth": "Mid Growth",  # 2 — existing
    "Mortgage-Backed Securities": "Mortgage-Backed Securities",  # 2 — new
    "Long/Short Equity": "Long/Short Equity",  # 2 — existing
    "Asian Equity": "Asian Equity",  # 2 — existing
    "European Equity": "European Equity",  # 1 — new canonical
    "Private Credit": "Private Credit",  # 1 — existing
    "Asset-Backed Securities": "Asset-Backed Securities",  # 1 — new canonical
}


_ETF_REASON_OVERRIDES: dict[str, str] = {
    "Municipal Bond": "muni excluded by PR-A24 (auto-import filter)",
}


# ---------------------------------------------------------------------------
# Section B.3 — SEC BDCs (sec_bdcs.strategy_label)
# ---------------------------------------------------------------------------
# Verified against dev DB 2026-04-18: 3 distinct values across 196 BDCs.
# All BDCs are private-credit lending vehicles regardless of internal label.
SEC_BDC_LABEL_NORMALIZE: dict[str, str | None] = {
    "Private Credit (BDC)": "Private Credit",  # 139
    "BDC": "Private Credit",  # 45
    "Growth / Venture (BDC)": "Private Credit",  # 12
}


# ---------------------------------------------------------------------------
# Section B.4 — ESMA UCITS (esma_funds.strategy_label)
# ---------------------------------------------------------------------------
# Verified against dev DB 2026-04-18: 33 distinct values across 6,051 funds.
ESMA_LABEL_NORMALIZE: dict[str, str | None] = {
    "International Equity": "International Equity",  # 1430
    "Intermediate-Term Bond": "Intermediate-Term Bond",  # 894
    "ESG/Sustainable Equity": "ESG/Sustainable Equity",  # 770
    "Balanced": "Balanced",  # 605
    "Asian Equity": "Asian Equity",  # 277
    "High Yield Bond": "High Yield Bond",  # 276
    "ESG/Sustainable Bond": "ESG/Sustainable Bond",  # 239
    "Emerging Markets Debt": "Emerging Markets Debt",  # 233
    "Investment Grade Bond": "Investment Grade Bond",  # 209
    "Emerging Markets Equity": "Emerging Markets Equity",  # 178
    "Government Bond": "Government Bond",  # 144
    "Large Growth": "Large Growth",  # 136
    "Sector Equity": "Sector Equity",  # 134
    "Large Value": "Large Value",  # 100
    "European Equity": "European Equity",  # 82
    "Small Blend": "Small Blend",  # 47
    "Target Date": None,  # 38 — multi-asset glide-path, requires operator review
    "Precious Metals": "Precious Metals",  # 34
    "Inflation-Linked Bond": "Inflation-Linked Bond",  # 34
    "Convertible Securities": None,  # 33 — no convertible block, requires review
    "Real Estate": "Real Estate",  # 32
    "Long/Short Equity": "Long/Short Equity",  # 31
    "Mid Blend": "Mid Blend",  # 31
    "European Bond": None,  # 22 — no developed-markets-bond block, requires review
    "Large Blend": "Large Blend",  # 18
    "Structured Credit": "Structured Credit",  # 10
    "Asset-Backed Securities": "Asset-Backed Securities",  # 8
    "Mid Growth": "Mid Growth",  # 1
    "Municipal Bond": None,  # 1 — muni excluded by A24
    "Private Credit": "Private Credit",  # 1
    "Small Growth": "Small Growth",  # 1
    "Small Value": "Small Value",  # 1
    "Mortgage-Backed Securities": "Mortgage-Backed Securities",  # 1
}


_ESMA_REASON_OVERRIDES: dict[str, str] = {
    "Target Date": "multi-asset glide-path; no canonical block (review)",
    "Convertible Securities": "no convertible-securities block (review)",
    "European Bond": "no developed-markets-bond block (review)",
    "Municipal Bond": "muni excluded by PR-A24 (auto-import filter)",
}


# ---------------------------------------------------------------------------
# Section B.5 — public API
# ---------------------------------------------------------------------------


def map_mmf_category(value: str | None) -> LabelMapping:
    """Normalize a ``sec_money_market_funds.mmf_category`` value."""
    if value is None:
        return LabelMapping(None, "mmf_category is null")
    label = MMF_CATEGORY_TO_LABEL.get(value)
    if label is None:
        return LabelMapping(None, f"unknown mmf_category={value!r}")
    return LabelMapping(label, "sec_mmf")


def map_etf_label(value: str | None) -> LabelMapping:
    """Normalize a ``sec_etfs.strategy_label`` value."""
    if value is None:
        return LabelMapping(None, "etf strategy_label is null")
    if value not in SEC_ETF_LABEL_NORMALIZE:
        return LabelMapping(None, f"unmapped sec_etfs label={value!r}")
    label = SEC_ETF_LABEL_NORMALIZE[value]
    if label is None:
        reason = _ETF_REASON_OVERRIDES.get(value, "intentionally unmapped")
        return LabelMapping(None, reason)
    return LabelMapping(label, "sec_etf")


def map_bdc_label(value: str | None) -> LabelMapping:
    """Normalize a ``sec_bdcs.strategy_label`` value."""
    if value is None:
        return LabelMapping(None, "bdc strategy_label is null")
    if value not in SEC_BDC_LABEL_NORMALIZE:
        return LabelMapping(None, f"unmapped sec_bdcs label={value!r}")
    label = SEC_BDC_LABEL_NORMALIZE[value]
    if label is None:
        return LabelMapping(None, "intentionally unmapped")
    return LabelMapping(label, "sec_bdc")


def map_esma_label(value: str | None) -> LabelMapping:
    """Normalize an ``esma_funds.strategy_label`` value."""
    if value is None:
        return LabelMapping(None, "esma strategy_label is null")
    if value not in ESMA_LABEL_NORMALIZE:
        return LabelMapping(None, f"unmapped esma_funds label={value!r}")
    label = ESMA_LABEL_NORMALIZE[value]
    if label is None:
        reason = _ESMA_REASON_OVERRIDES.get(value, "intentionally unmapped")
        return LabelMapping(None, reason)
    return LabelMapping(label, "esma_funds")


def all_canonical_labels() -> set[str]:
    """Return every non-``None`` canonical label this module can emit.

    Used by tests to assert every emitted label exists in
    ``STRATEGY_LABEL_TO_BLOCKS``.
    """
    out: set[str] = set()
    out.update(v for v in MMF_CATEGORY_TO_LABEL.values())
    out.update(v for v in SEC_ETF_LABEL_NORMALIZE.values() if v is not None)
    out.update(v for v in SEC_BDC_LABEL_NORMALIZE.values() if v is not None)
    out.update(v for v in ESMA_LABEL_NORMALIZE.values() if v is not None)
    return out


def assert_block_mapping_coverage() -> list[str]:
    """Return the list of canonical labels missing from ``block_mapping.py``.

    An empty list means the map is fully covered by the block mapping.
    """
    missing: list[str] = []
    for label in sorted(all_canonical_labels()):
        if label not in STRATEGY_LABEL_TO_BLOCKS:
            missing.append(label)
    return missing

"""Strategy label family mapping + diff-severity classification.

Families group strategy labels that are peer-comparable. A label change
*within* a family ("Large Blend" → "Large Growth") is a low-risk style
refinement; a change *across* families ("Large Blend" → "High Yield Bond")
is an asset-class change that may break allocation blocks, peer groups,
or scoring.

The apply gate in ``apply_strategy_reclassification.py`` uses these
severity tiers to decide whether ``--force`` and/or ``--justification``
are required before touching production.
"""

from __future__ import annotations

from typing import Literal

Family = Literal[
    "equity",
    "fixed_income",
    "alts",
    "private",
    "hedge",
    "multi_asset",
    "convertible",
    "cash",
    "other",
]


# Canonical mapping. Must stay in sync with
# ``app.domains.wealth.services.strategy_classifier.STRATEGY_LABELS`` —
# enforced by ``test_classification_family.py::TestFamilyMap``.
STRATEGY_FAMILY: dict[str, Family] = {
    # ── Equity ─────────────────────────────────────────────────────
    "Large Blend": "equity",
    "Large Growth": "equity",
    "Large Value": "equity",
    "Mid Blend": "equity",
    "Mid Growth": "equity",
    "Mid Value": "equity",
    "Small Blend": "equity",
    "Small Growth": "equity",
    "Small Value": "equity",
    "International Equity": "equity",
    "Emerging Markets Equity": "equity",
    "Global Equity": "equity",
    "Sector Equity": "equity",
    "European Equity": "equity",
    "Asian Equity": "equity",
    "ESG/Sustainable Equity": "equity",
    # ── Fixed Income ───────────────────────────────────────────────
    "Short-Term Bond": "fixed_income",
    "Intermediate-Term Bond": "fixed_income",
    "Long-Term Bond": "fixed_income",
    "High Yield Bond": "fixed_income",
    "Investment Grade Bond": "fixed_income",
    "Government Bond": "fixed_income",
    "Municipal Bond": "fixed_income",
    "International Bond": "fixed_income",
    "Inflation-Linked Bond": "fixed_income",
    "European Bond": "fixed_income",
    "Emerging Markets Debt": "fixed_income",
    "ESG/Sustainable Bond": "fixed_income",
    "Mortgage-Backed Securities": "fixed_income",
    "Asset-Backed Securities": "fixed_income",
    # ── Alternatives ───────────────────────────────────────────────
    "Real Estate": "alts",
    "Infrastructure": "alts",
    "Commodities": "alts",
    "Precious Metals": "alts",
    # ── Private ────────────────────────────────────────────────────
    "Private Credit": "private",
    "Private Equity": "private",
    "Venture Capital": "private",
    "Structured Credit": "private",
    # ── Hedge ──────────────────────────────────────────────────────
    "Long/Short Equity": "hedge",
    "Global Macro": "hedge",
    "Multi-Strategy": "hedge",
    "Event-Driven": "hedge",
    "Volatility Arbitrage": "hedge",
    "Convertible Arbitrage": "hedge",
    "Quant/Systematic": "hedge",
    # ── Multi-Asset ────────────────────────────────────────────────
    "Balanced": "multi_asset",
    "Target Date": "multi_asset",
    "Allocation": "multi_asset",
    # ── Convertible (hybrid security, distinct from arb hedge) ─────
    "Convertible Securities": "convertible",
    # ── Cash / Other ───────────────────────────────────────────────
    "Cash Equivalent": "cash",
    "Other": "other",
}


Severity = Literal[
    "unchanged",
    "safe_auto_apply",      # P0: NULL → specific
    "style_refinement",     # P1: same family
    "asset_class_change",   # P2: cross family
    "lost_class",           # P3: non-null → NULL
]


def family_of(label: str | None) -> Family | None:
    """Return the family for a label, or ``None`` for NULL/unknown."""
    if label is None:
        return None
    return STRATEGY_FAMILY.get(label)


def is_same_family(current: str | None, proposed: str | None) -> bool:
    """True only when both labels are known and share a family.

    A NULL on either side is treated as "not same family" — those cases
    are routed to ``safe_auto_apply`` or ``lost_class`` by the severity
    classifier, never to ``style_refinement``.
    """
    if current is None or proposed is None:
        return False
    cur = family_of(current)
    prop = family_of(proposed)
    if cur is None or prop is None:
        return False
    return cur == prop


def classify_severity(
    current: str | None, proposed: str | None,
) -> Severity:
    """Classify a (current, proposed) diff for apply gating."""
    if current == proposed:
        return "unchanged"
    if current is None and proposed is not None:
        return "safe_auto_apply"
    if current is not None and proposed is None:
        return "lost_class"
    # Both non-null and differ
    if is_same_family(current, proposed):
        return "style_refinement"
    return "asset_class_change"

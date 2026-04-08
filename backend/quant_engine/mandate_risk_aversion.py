"""Mandate → mean-variance risk-aversion (λ) mapping.

Single source of truth used across every quant service that needs a
DCP-compliant quadratic utility (E[r] − λ·σ²). Keeping this in one module
prevents drift between the optimizer, Black-Litterman, rebalancing and any
future consumer, and lets institutional mandates (Conservative, Moderate,
Aggressive, …) drive λ through a shared label instead of magic numbers.

The numeric ranges follow Grinold & Kahn, "Active Portfolio Management"
and CFA L3 "Risk Aversion and Utility" readings:

    Conservative  → 4.5   (low tolerance, variance heavily penalised)
    Moderate      → 2.5   (balanced, sensible fallback)
    Aggressive    → 1.5   (high tolerance, return-tilted)
"""

from __future__ import annotations

# Canonical map. Keep keys lowercase, underscore-separated.
_MANDATE_RISK_AVERSION: dict[str, float] = {
    "conservative": 4.5,
    "defensive": 4.5,
    "moderate_conservative": 3.5,
    "moderate": 2.5,
    "balanced": 2.5,
    "moderate_aggressive": 2.0,
    "aggressive": 1.5,
    "growth": 1.5,
}

DEFAULT_RISK_AVERSION = 2.5  # moderate — sane fallback when mandate unknown


def resolve_risk_aversion(
    risk_aversion: float | None,
    mandate: str | None,
) -> float:
    """Resolve λ from an explicit override, a mandate label, or the default.

    Priority:
      1. ``risk_aversion`` — caller-supplied override (must be > 0).
      2. ``mandate`` — label lookup in :data:`_MANDATE_RISK_AVERSION`.
      3. :data:`DEFAULT_RISK_AVERSION` — moderate.

    Never returns a hardcoded historical λ; every caller flowing through
    this helper honours the investor mandate.
    """
    if risk_aversion is not None and risk_aversion > 0:
        return float(risk_aversion)
    if mandate:
        key = mandate.strip().lower().replace("-", "_").replace(" ", "_")
        if key in _MANDATE_RISK_AVERSION:
            return _MANDATE_RISK_AVERSION[key]
    return DEFAULT_RISK_AVERSION

"""Mandate → mean-variance risk-aversion (λ) mapping.

Single source of truth used across every quant service that needs a
DCP-compliant quadratic utility (E[r] − λ·σ²). Keeping this in one module
prevents drift between the optimizer, Black-Litterman, rebalancing and any
future consumer, and lets institutional mandates (Conservative, Moderate,
Aggressive, …) drive λ through a shared label instead of magic numbers.

The arithmetic ladder (4.5/3.5/2.5/2.0/1.5) follows Grinold & Kahn,
"Active Portfolio Management" and CFA L3 "Risk Aversion and Utility"
readings. Migrating to a geometric ladder would alter optimizer outputs
for every tenant and constitutes recalibration, not bug fix — see Wave 5
audit decision log.

    Conservative  → 4.5   (low tolerance, variance heavily penalised)
    Moderate      → 2.5   (balanced, sensible fallback)
    Aggressive    → 1.5   (high tolerance, return-tilted)

Resolution rules:
  - Explicit override must be finite and within [RA_MIN, RA_MAX].
  - Mandate label normalization collapses whitespace and dashes.
  - Unknown mandate logs a warning and falls back to DEFAULT.
"""

from __future__ import annotations

import math
import re

import structlog

logger = structlog.get_logger()

# Canonical map. Keys lowercase, underscore-separated.
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
RA_MIN = 0.5                 # Grinold-Kahn lower bound for institutional λ
RA_MAX = 10.0                # upper bound — beyond this, optimizer scaling fails

# Pre-compiled normaliser: collapse runs of whitespace + dashes into one underscore.
_KEY_NORMALISER = re.compile(r"[\s\-]+")

# PR-BE-7 — backward-compat alias for the legacy ``aggressive`` mandate.
# The dict ``_MANDATE_RISK_AVERSION`` keeps the key so any direct lookups
# elsewhere keep working, but normalised input is rewritten to ``growth``
# with a deprecation log. Sunset 2026-10-30 (180d post-merge). Atomic
# (compound) keys like ``moderate_aggressive`` are NOT touched — those
# are independent ladder rungs, not the legacy artefact.
_MANDATE_ALIASES: dict[str, str] = {"aggressive": "growth"}
_MANDATE_SUNSET_DATE = "2026-10-30"


def _normalise_mandate(mandate: str) -> str:
    """Normalise a free-text mandate label to the canonical dict key.

    Collapses runs of whitespace and dashes (e.g., '  ', '--', ' - ')
    into single underscores. Idempotent. The legacy ``aggressive``
    mandate is rewritten to ``growth`` (PR-BE-7) with a structured
    deprecation log.
    """
    key = _KEY_NORMALISER.sub("_", mandate.strip().lower())
    if key in _MANDATE_ALIASES:
        canonical = _MANDATE_ALIASES[key]
        logger.info(
            "legacy_mandate_alias_used",
            received=key,
            canonical=canonical,
            sunset_at=_MANDATE_SUNSET_DATE,
        )
        return canonical
    return key


def resolve_risk_aversion(
    risk_aversion: float | None,
    mandate: str | None,
) -> float:
    """Resolve λ from an explicit override, a mandate label, or the default.

    Priority:
      1. ``risk_aversion`` — caller-supplied override.
         Must be finite and in [RA_MIN, RA_MAX]; out-of-range values are
         clamped with a warning. NaN/Inf are rejected (override discarded).
      2. ``mandate`` — label lookup in :data:`_MANDATE_RISK_AVERSION`,
         after whitespace+dash normalisation. Unknown labels log a warning
         and fall through to default.
      3. :data:`DEFAULT_RISK_AVERSION` — moderate.
    """
    if risk_aversion is not None:
        if not math.isfinite(risk_aversion):
            logger.warning(
                "non_finite_risk_aversion_discarded",
                value=risk_aversion,
            )
            # Fall through to mandate
        elif risk_aversion <= 0:
            logger.warning(
                "non_positive_risk_aversion_discarded",
                value=risk_aversion,
            )
            # Fall through to mandate
        elif risk_aversion < RA_MIN or risk_aversion > RA_MAX:
            clamped = max(RA_MIN, min(RA_MAX, risk_aversion))
            logger.warning(
                "risk_aversion_out_of_range_clamped",
                value=risk_aversion,
                clamped_to=clamped,
                range=(RA_MIN, RA_MAX),
            )
            return float(clamped)
        else:
            return float(risk_aversion)

    if mandate:
        key = _normalise_mandate(mandate)
        if key in _MANDATE_RISK_AVERSION:
            return _MANDATE_RISK_AVERSION[key]
        logger.warning(
            "unknown_mandate_using_default",
            mandate=mandate,
            normalized=key,
            default=DEFAULT_RISK_AVERSION,
        )

    return DEFAULT_RISK_AVERSION

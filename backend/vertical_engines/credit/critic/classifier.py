"""Instrument type classification — deterministic, no LLM call.

Imports only from models.py (leaf dependency).
"""
from __future__ import annotations

from typing import Any

import structlog

from vertical_engines.credit.critic.models import INSTRUMENT_TYPE_PROFILES  # noqa: F401

logger = structlog.get_logger()


def classify_instrument_type(structured_analysis: dict[str, Any]) -> str:
    """Classify deal instrument type deterministically from structured analysis.

    No LLM call — pure signal matching on extracted fields.
    Returns a key from INSTRUMENT_TYPE_PROFILES.

    Classification hierarchy (first match wins):
      1. Open-ended fund  — redemption signals + NAV + "fund" language
      2. Closed-end fund  — vintage / drawdown / capital call signals
      3. Revolving credit — ABL / factoring / borrowing base signals
      4. Note or bond     — note / bond / certificate language
      5. Equity co-invest — equity / co-invest in capital structure position
      6. Term loan        — maturity + coupon both present
      7. UNKNOWN          — no signals matched
    """
    strategy = (structured_analysis.get("strategyType") or "").lower()
    capital_pos = (structured_analysis.get("capitalStructurePosition") or "").lower()
    liquidity = (structured_analysis.get("liquidityProfile") or "").lower()
    terms = structured_analysis.get("investmentTerms") or {}

    # ── 1. Open-ended fund ────────────────────────────────────────
    open_signals = [
        any(x in strategy for x in ["open-ended", "open ended", "evergreen"]),
        "fund" in strategy and "closed" not in strategy and "hedge" not in strategy,
        any(x in liquidity for x in ["monthly redemption", "daily redemption",
                                      "weekly redemption", "quarterly redemption"]),
        "nav" in liquidity,
        bool(terms.get("redemptionFrequency")),
        any(x in strategy for x in ["private credit fund", "debt fund", "credit fund"])
        and "closed" not in strategy,
    ]
    if sum(open_signals) >= 2:
        return "OPEN_ENDED_FUND"

    # ── 2. Closed-end fund ────────────────────────────────────────
    closed_signals = [
        any(x in strategy for x in ["closed-end", "closed end", "vintage"]),
        any(x in liquidity for x in ["capital call", "drawdown", "j-curve", "j curve"]),
        any(x in strategy for x in ["private equity", "pe fund", "buyout", "growth equity"]),
    ]
    if sum(closed_signals) >= 1:
        return "CLOSED_END_FUND"

    # ── 3. Revolving credit / ABL ─────────────────────────────────
    revolving_signals = [
        any(x in strategy for x in [
            "revolving", "revolver", "abl", "asset-based", "asset based",
            "factoring", "borrowing base", "receivables", "lender finance",
            "specialty finance",
        ]),
        any(x in capital_pos for x in ["revolving", "abl", "senior secured revolving"]),
    ]
    if sum(revolving_signals) >= 1:
        return "REVOLVING_CREDIT"

    # ── 4. Note or bond ───────────────────────────────────────────
    note_signals = [
        any(x in strategy for x in [
            "note", "bond", "debenture", "etn",
            "certificate", "structured note", "amc",
        ]),
        any(x in capital_pos for x in ["note", "bond", "senior note", "subordinated note"]),
    ]
    if sum(note_signals) >= 1:
        return "NOTE_OR_BOND"

    # ── 5. Equity co-invest ───────────────────────────────────────
    equity_signals = [
        any(x in capital_pos for x in ["equity", "co-invest", "co invest", "common", "preferred"]),
        any(x in strategy for x in ["equity", "co-investment", "co-invest"]),
    ]
    if sum(equity_signals) >= 1:
        return "EQUITY_CO_INVEST"

    # ── 6. Term loan (fallback for debt with explicit terms) ──────
    has_maturity = bool(terms.get("maturityDate"))
    has_coupon = bool(terms.get("interestRate") or terms.get("couponRate"))
    if has_maturity and has_coupon:
        return "TERM_LOAN"

    return "UNKNOWN"

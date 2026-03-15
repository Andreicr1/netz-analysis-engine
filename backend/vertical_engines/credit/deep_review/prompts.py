"""Deep review prompts — system prompts, pre-classification, and prompt construction."""

from __future__ import annotations

from typing import Any

import structlog

from ai_engine.prompts import prompt_registry

logger = structlog.get_logger()


def _deal_review_template_context(
    instrument_type: str,
    deal_role_map: dict[str, Any] | None = None,
    third_party_counterparties: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build shared template context for deal review prompts."""
    from vertical_engines.credit.critic import INSTRUMENT_TYPE_PROFILES

    profile = INSTRUMENT_TYPE_PROFILES.get(
        instrument_type,
        INSTRUMENT_TYPE_PROFILES["UNKNOWN"],
    )
    deal_role_map = deal_role_map or {}

    return {
        "instrument_type": instrument_type,
        "expected_absent": profile.get("expected_absent", []),
        "key_risk_dimensions": profile.get("key_risk_dimensions", []),
        "deal_structure": deal_role_map.get("deal_structure"),
        "borrower": deal_role_map.get("borrower", "unknown"),
        "lender": deal_role_map.get("lender", "unknown"),
        "manager": deal_role_map.get("manager", "unknown"),
        "third_party_counterparties": third_party_counterparties or [],
    }


def _pre_classify_from_corpus(
    corpus: str,
    deal_fields: dict[str, Any] | None = None,
) -> str:
    """Lightweight instrument pre-classification from raw corpus text.

    Runs BEFORE the structured analysis LLM call so the extraction prompt
    can be instrument-aware.  Uses keyword scanning — no LLM call.

    Returns a key from INSTRUMENT_TYPE_PROFILES.
    """
    text = corpus[:20_000].lower()  # scan first ~20k chars
    deal_name = ((deal_fields or {}).get("deal_name") or "").lower()
    strategy = ((deal_fields or {}).get("strategy_type") or "").lower()
    combined = f"{deal_name} {strategy} {text}"

    # ── 1. Open-ended fund ────────────────────────────────────────
    open_signals = sum(
        [
            any(x in combined for x in ["open-ended", "open ended", "evergreen"]),
            "fund" in deal_name and "closed" not in deal_name,
            any(
                x in combined
                for x in [
                    "monthly redemption",
                    "quarterly redemption",
                    "weekly redemption",
                    "daily redemption",
                ]
            ),
            any(
                x in combined
                for x in [
                    "nav per unit",
                    "nav per share",
                    "net asset value",
                ]
            ),
            any(
                x in combined
                for x in [
                    "private credit fund",
                    "debt fund",
                    "credit fund",
                    "lending fund",
                    "income fund",
                ]
            )
            and "closed" not in combined[:500],
        ],
    )
    if open_signals >= 2:
        return "OPEN_ENDED_FUND"

    # ── 2. Closed-end fund ────────────────────────────────────────
    closed_signals = sum(
        [
            any(x in combined for x in ["closed-end", "closed end", "vintage"]),
            any(
                x in combined
                for x in [
                    "capital call",
                    "drawdown",
                    "j-curve",
                    "j curve",
                ]
            ),
            any(
                x in combined
                for x in [
                    "private equity",
                    "pe fund",
                    "buyout",
                    "growth equity",
                ]
            ),
        ],
    )
    if closed_signals >= 1:
        return "CLOSED_END_FUND"

    # ── 3. Revolving credit / ABL ─────────────────────────────────
    revolving_signals = sum(
        [
            any(
                x in combined
                for x in [
                    "revolving",
                    "revolver",
                    "abl",
                    "asset-based",
                    "asset based",
                    "factoring",
                    "borrowing base",
                    "receivables",
                    "lender finance",
                    "specialty finance",
                ]
            ),
        ],
    )
    if revolving_signals >= 1:
        return "REVOLVING_CREDIT"

    # ── 4. Note or bond ───────────────────────────────────────────
    note_signals = sum(
        [
            any(
                x in combined
                for x in [
                    "debenture",
                    "structured note",
                    "certificate",
                ]
            ),
            any(x in deal_name for x in ["note", "bond"]),
        ],
    )
    if note_signals >= 1:
        return "NOTE_OR_BOND"

    # ── 5. Equity co-invest ───────────────────────────────────────
    equity_signals = sum(
        [
            any(
                x in combined
                for x in [
                    "equity co-invest",
                    "co-investment",
                    "equity participation",
                ]
            ),
        ],
    )
    if equity_signals >= 1:
        return "EQUITY_CO_INVEST"

    # ── 6. Term loan ─────────────────────────────────────────────
    term_signals = sum(
        [
            any(
                x in combined
                for x in [
                    "term loan",
                    "senior secured loan",
                    "bilateral loan",
                ]
            ),
            "maturity" in combined and ("coupon" in combined or "interest" in combined),
        ],
    )
    if term_signals >= 1:
        return "TERM_LOAN"

    return "UNKNOWN"


def _build_deal_review_prompt_v2(
    instrument_type: str,
    deal_role_map: dict[str, Any] | None = None,
    third_party_counterparties: list[dict[str, Any]] | None = None,
) -> str:
    """Build v2 structured extraction prompt."""
    return prompt_registry.render(
        "deal_review_system_v2.j2",
        **_deal_review_template_context(
            instrument_type,
            deal_role_map=deal_role_map,
            third_party_counterparties=third_party_counterparties,
        ),
    )


__all__ = [
    "_deal_review_template_context",
    "_pre_classify_from_corpus",
    "_build_deal_review_prompt_v2",
]

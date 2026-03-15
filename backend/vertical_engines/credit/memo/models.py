"""Memo package models — LEAF node, zero sibling imports.

Contains:
  - CallOpenAiFn: Protocol for the OpenAI completion callback
  - CHAPTER_REGISTRY: authoritative 14-chapter table
  - ToneReviewEntry / ToneReviewResult: Pydantic schemas for tone normalizer output
"""
from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Callback protocol for call_openai_fn
# ---------------------------------------------------------------------------

class CallOpenAiFn(Protocol):
    """Structural type for the OpenAI completion callback."""

    def __call__(
        self, system_prompt: str, user_content: str, *, max_tokens: int = ..., model: str | None = ...,
    ) -> dict[str, Any]: ...


# ---------------------------------------------------------------------------
# Chapter registry — authoritative 14-chapter table
# ---------------------------------------------------------------------------

CHAPTER_REGISTRY: list[tuple[int, str, str]] = [
    (1,  "ch01_exec",           "Executive Summary"),
    (2,  "ch02_macro",          "Market Context"),
    (3,  "ch03_exit",           "Macro Regime & Exit Environment"),
    (4,  "ch04_sponsor",        "Sponsor & Management Analysis"),
    (5,  "ch05_legal",          "Legal Structure & Document Analysis"),
    (6,  "ch06_terms",          "Detailed Investment Terms & Covenants"),
    (7,  "ch07_capital",        "Capital Structure Analysis"),
    (8,  "ch08_returns",        "Return Modeling"),
    (9,  "ch09_downside",       "Downside Scenario Model"),
    (10, "ch10_covenants",      "Covenant Strength Assessment"),
    (11, "ch11_risks",          "Key Risks"),
    (12, "ch12_peers",          "Peer Comparison"),
    (13, "ch13_recommendation", "Final Recommendation"),
    (14, "ch14_governance_stress", "Governance Under Adverse Event & Stress Analysis"),
]


# ---------------------------------------------------------------------------
# Tone normalizer Pydantic schemas
# ---------------------------------------------------------------------------

class ToneReviewEntry(BaseModel):
    chapter: str
    change_type: str  # hedging_removed | tense_normalized | length_reduced | contradiction_flagged | signal_escalated
    original_fragment: str
    revised_fragment: str
    rationale: str


class ToneReviewResult(BaseModel):
    chapters: dict[str, str]        # ch_tag → revised chapter text
    signal_original: str            # INVEST | CONDITIONAL | PASS
    signal_final: str               # may differ if escalated
    signal_escalated: bool
    escalation_rationale: str | None  # required if escalated
    tone_review_log: list[ToneReviewEntry]
    pass1_changes: dict[str, int]   # {chapter_tag: chars_removed}
    pass2_changes: list[str]        # description of cross-chapter changes

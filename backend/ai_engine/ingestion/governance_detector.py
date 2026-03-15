"""Deterministic governance flag detection via regex.

Pure regex — zero API cost. Runs on every document after OCR.
Ported verbatim from prepare_pdfs_full.py (lines 441-476).
"""
from __future__ import annotations

import re

_GOV_PATTERNS: list[tuple[str, str]] = [
    ("side_letter",               r"\bside\s+letter\b"),
    ("most_favored_nation",       r"\bmost[- ]favored[- ]nation\b|\bMFN\b"),
    ("key_person_clause",         r"\bkey[- ]person\b|\bkeyman\b"),
    ("clawback",                  r"\bclawback\b|\bclaw[- ]back\b"),
    ("carried_interest",          r"\bcarried\s+interest\b|\bperformance\s+(?:fee|allocation)\b|\bpromote\s+interest\b"),
    ("fee_rebate",                r"\bfee\s+rebate\b|\bfee\s+waiver\b|\bmanagement\s+fee\s+offset\b"),
    ("gating_provision",          r"\bgating\s+provision\b|\bredemption\s+gate\b"),
    ("suspension_of_redemptions", r"\bsuspension\s+of\s+redemption\b|\bsuspend\s+redemption\b"),
    ("concentration_limit",       r"\bconcentration\s+limit\b|\bconcentration\s+cap\b"),
    ("board_override",            r"\bboard\s+(override|resolution|approval)\b"),
    ("investment_limit_exception", r"\binvestment\s+limit\s+exception\b|\bpolicy\s+exception\b"),
    ("policy_override",           r"\bpolicy\s+override\b"),
    ("conflicts_of_interest",     r"\bconflicts?\s+of\s+interest\b"),
    ("related_party",             r"\brelated\s+party\b|\brelated[- ]party\s+transaction\b"),
    ("fund_of_funds_structure",   r"\bfund[- ]of[- ]funds\b|\bFoF\b|\bunderlying\s+fund\b"),
]

_GOVERNANCE_CRITICAL_PATTERNS = re.compile(
    r"\bside\s+letter\b"
    r"|\bmost[- ]favored[- ]nation\b|\bMFN\b"
    r"|\bfee\s+rebate\b|\bfee\s+waiver\b"
    r"|\bboard\s+override\b"
    r"|\binvestment\s+limit\s+exception\b"
    r"|\bfund[- ]of[- ]funds\b",
    re.IGNORECASE,
)


def detect_governance(text: str) -> tuple[bool, list[str]]:
    """Detect governance flags in document text.

    Returns:
        (critical, flags) where critical is True if any critical governance
        pattern is found, and flags is the list of all matched flag names.
    """
    flags = []
    for flag, pattern in _GOV_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            flags.append(flag)
    critical = bool(_GOVERNANCE_CRITICAL_PATTERNS.search(text))
    return critical, flags

"""Governance detection — deterministic regex, zero API cost.

Extracted from legacy ``prepare_pdfs_full.py``. Detects 15 governance patterns
per chunk/document and flags governance-critical content.

Used by the ingestion pipeline to populate ``governance_critical`` and
``governance_flags`` fields in the search index, enabling Ch14 Governance
Stress chapter in IC Memos to prioritize evidence.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Governance patterns ──────────────────────────────────────────────

_GOV_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("side_letter",               re.compile(r"\bside\s+letter\b", re.IGNORECASE)),
    ("most_favored_nation",       re.compile(r"\bmost[- ]favored[- ]nation\b|\bMFN\b", re.IGNORECASE)),
    ("key_person_clause",         re.compile(r"\bkey[- ]person\b|\bkeyman\b", re.IGNORECASE)),
    ("clawback",                  re.compile(r"\bclawback\b|\bclaw[- ]back\b", re.IGNORECASE)),
    ("carried_interest",          re.compile(r"\bcarried\s+interest\b|\bperformance\s+(?:fee|allocation)\b|\bpromote\s+interest\b", re.IGNORECASE)),
    ("fee_rebate",                re.compile(r"\bfee\s+rebate\b|\bfee\s+waiver\b|\bmanagement\s+fee\s+offset\b", re.IGNORECASE)),
    ("gating_provision",          re.compile(r"\bgating\s+provision\b|\bredemption\s+gate\b", re.IGNORECASE)),
    ("suspension_of_redemptions", re.compile(r"\bsuspension\s+of\s+redemption\b|\bsuspend\s+redemption\b", re.IGNORECASE)),
    ("concentration_limit",       re.compile(r"\bconcentration\s+limit\b|\bconcentration\s+cap\b", re.IGNORECASE)),
    ("board_override",            re.compile(r"\bboard\s+(override|resolution|approval)\b", re.IGNORECASE)),
    ("investment_limit_exception", re.compile(r"\binvestment\s+limit\s+exception\b|\bpolicy\s+exception\b", re.IGNORECASE)),
    ("policy_override",           re.compile(r"\bpolicy\s+override\b", re.IGNORECASE)),
    ("conflicts_of_interest",     re.compile(r"\bconflicts?\s+of\s+interest\b", re.IGNORECASE)),
    ("related_party",             re.compile(r"\brelated\s+party\b|\brelated[- ]party\s+transaction\b", re.IGNORECASE)),
    ("fund_of_funds_structure",   re.compile(r"\bfund[- ]of[- ]funds\b|\bFoF\b|\bunderlying\s+fund\b", re.IGNORECASE)),
]

_GOVERNANCE_CRITICAL_RE = re.compile(
    r"\bside\s+letter\b"
    r"|\bmost[- ]favored[- ]nation\b|\bMFN\b"
    r"|\bfee\s+rebate\b|\bfee\s+waiver\b"
    r"|\bboard\s+override\b"
    r"|\binvestment\s+limit\s+exception\b"
    r"|\bfund[- ]of[- ]funds\b",
    re.IGNORECASE,
)


# ── Result type ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class GovernanceResult:
    governance_critical: bool
    governance_flags: list[str] = field(default_factory=list)


# ── Public API ───────────────────────────────────────────────────────


def detect_governance(text: str) -> GovernanceResult:
    """Detect governance patterns in text.

    Returns GovernanceResult with:
    - governance_critical: True if any high-priority pattern matches
    - governance_flags: list of matched pattern names (e.g. ["side_letter", "clawback"])

    Pure Python, deterministic, zero API cost.
    """
    flags: list[str] = []
    for flag_name, pattern in _GOV_PATTERNS:
        if pattern.search(text):
            flags.append(flag_name)

    critical = bool(_GOVERNANCE_CRITICAL_RE.search(text))
    return GovernanceResult(governance_critical=critical, governance_flags=flags)

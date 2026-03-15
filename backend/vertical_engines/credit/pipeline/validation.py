"""Citation and output validation (Tier-1 enforcement).

Implements _validate_output() and _validate_memo().
"""
from __future__ import annotations

from typing import Any

from vertical_engines.credit.pipeline.models import (
    MIN_CITATIONS_REQUIRED,
    MIN_KEY_RISKS,
    MIN_MEMO_CHARS,
)


def _validate_output(output: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate structured intelligence output.

    Tier-1 enforcement:
    - Minimum 5 citations (hard fail)
    - Minimum 3 key risks
    - All required top-level keys present
    - Each citation must have chunk_index, doc, rationale
    """
    issues: list[str] = []

    required_keys = {
        "deal_overview", "terms_and_covenants", "risk_map",
        "investment_thesis", "exit_scenarios", "comparables",
        "missing_documents", "citations",
    }
    missing_keys = required_keys - set(output.keys())
    if missing_keys:
        issues.append(
            f"Missing top-level keys: {', '.join(sorted(missing_keys))}",
        )

    overview = output.get("deal_overview", {})
    if not overview.get("name"):
        issues.append("deal_overview.name is empty")

    citations = output.get("citations", [])
    if len(citations) < MIN_CITATIONS_REQUIRED:
        issues.append(
            f"citations has only {len(citations)} entries "
            f"(minimum {MIN_CITATIONS_REQUIRED} required for Tier-1)",
        )

    for i, cit in enumerate(citations):
        if not isinstance(cit, dict):
            issues.append(f"citations[{i}] is not a dict")
            continue
        if "chunk_index" not in cit:
            issues.append(f"citations[{i}] missing chunk_index")
        if not cit.get("doc"):
            issues.append(f"citations[{i}] missing doc title")
        if not cit.get("rationale"):
            issues.append(f"citations[{i}] missing rationale")

    risk_map = output.get("risk_map", {})
    key_risks = (
        risk_map.get("key_risks", []) if isinstance(risk_map, dict)
        else risk_map
    )
    if len(key_risks) < MIN_KEY_RISKS:
        issues.append(
            f"risk_map.key_risks has only {len(key_risks)} entries "
            f"(minimum {MIN_KEY_RISKS})",
        )

    return len(issues) == 0, issues


def _validate_memo(memo_output: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate memo writer output."""
    issues: list[str] = []
    memo_text = memo_output.get("investment_memo", "")
    if len(memo_text) < MIN_MEMO_CHARS:
        issues.append(
            f"investment_memo is only {len(memo_text)} chars "
            f"(minimum {MIN_MEMO_CHARS})",
        )
    confidence = memo_output.get("confidence_score")
    if confidence is not None:
        try:
            if not (0.0 <= float(confidence) <= 1.0):
                issues.append(
                    f"confidence_score {confidence} outside [0, 1] range",
                )
        except (TypeError, ValueError):
            issues.append(f"confidence_score {confidence} is not numeric")
    return len(issues) == 0, issues

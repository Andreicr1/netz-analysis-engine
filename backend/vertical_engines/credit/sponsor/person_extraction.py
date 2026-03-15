"""Key person extraction — deterministic, no LLM call.

Stdlib only — no sibling imports.
"""
from __future__ import annotations

import re
from typing import Any

import structlog

logger = structlog.get_logger()

# Corporate entity suffixes — used to exclude non-person strings.
_CORP_SUFFIXES: set[str] = {
    "llc", "ltd", "inc", "corp", "plc", "gmbh", "sa", "ag", "lp", "llp",
    "fund", "trust", "holdings", "capital", "management", "partners",
    "group", "limited", "offshore", "advisers", "advisors", "investments",
    "investors", "company", "estate", "opps", "opportunities", "credit",
    "equity", "preferred", "senior", "spv", "spvs", "vehicles", "real",
    "project", "wealth", "housing", "international", "global", "ventures",
    "securities", "associates", "enterprises", "financial", "asset",
    "assets", "services", "advisories", "consulting",
}


def extract_key_persons_from_analysis(analysis: dict[str, Any]) -> list[str]:
    """Extract key person names from the structured deal analysis.

    Sources:
      - corporateStructure.guarantors
      - corporateStructure.ownershipChain
      - corporateStructure.borrower (if a person name)

    Returns a deduplicated list of person-like name strings.
    """
    names: list[str] = []

    structure = analysis.get("corporateStructure", {})
    if isinstance(structure, dict):
        # Guarantors
        for g in structure.get("guarantors", []):
            if isinstance(g, str) and _looks_like_person_name(g):
                names.append(g.strip())

        # Ownership chain — extract names from free text
        chain = structure.get("ownershipChain", "")
        if isinstance(chain, str):
            names.extend(_extract_names_from_text(chain))

        # Borrower — only if it looks like a person
        borrower = structure.get("borrower", "")
        if isinstance(borrower, str) and _looks_like_person_name(borrower):
            names.append(borrower.strip())

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for name in names:
        key = name.lower().strip()
        if key and key not in seen and key != "not specified":
            seen.add(key)
            result.append(name)

    return result


def _looks_like_person_name(text: str) -> bool:
    """Heuristic: a person name has 2-5 capitalized words, no corp suffixes."""
    if not text or len(text) > 60:
        return False
    words = text.strip().split()
    if len(words) < 2 or len(words) > 5:
        return False
    lower_words = {w.lower().rstrip(".,") for w in words}
    if lower_words & _CORP_SUFFIXES:
        return False
    return True


def _extract_names_from_text(text: str) -> list[str]:
    """Extract capitalized multi-word sequences that look like person names."""
    # Pattern: 2-4 consecutive capitalized words
    pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"
    matches = re.findall(pattern, text)
    return [m for m in matches if _looks_like_person_name(m)]

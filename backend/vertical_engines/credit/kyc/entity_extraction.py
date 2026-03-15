"""Entity extraction from deal analysis for KYC screening.

Cross-package dependency: imports from sponsor.person_extraction.
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()


def extract_persons_from_analysis(
    analysis: dict[str, Any],
    index_key_persons: list[str] | None = None,
    sponsor_output: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Collect unique person names from all analysis sources.

    Returns a list of dicts ``{"first_name": ..., "last_name": ...}``.
    """
    raw_names: set[str] = set()

    # 1) Index key persons (extracted from evidence chunks)
    if index_key_persons:
        for name in index_key_persons:
            clean = name.strip()
            if clean and len(clean) > 2:
                raw_names.add(clean)

    # 2) Sponsor output — key persons from sponsor engine
    if sponsor_output:
        for kp in sponsor_output.get("key_persons", []):
            n = (kp if isinstance(kp, str) else kp.get("name", "")).strip()
            if n and len(n) > 2 and n.lower() != "not specified":
                raw_names.add(n)

    # 3) Corporate structure — extract person names from guarantors / ownership
    from vertical_engines.credit.sponsor import extract_key_persons_from_analysis

    for name in extract_key_persons_from_analysis(analysis):
        if name.strip() and len(name.strip()) > 2:
            raw_names.add(name.strip())

    persons: list[dict[str, str]] = []
    seen: set[str] = set()

    for full_name in sorted(raw_names):
        key = full_name.lower()
        if key in seen:
            continue
        seen.add(key)

        parts = full_name.split()
        if len(parts) >= 2:
            persons.append(
                {
                    "first_name": parts[0],
                    "last_name": " ".join(parts[1:]),
                },
            )
        else:
            persons.append(
                {
                    "first_name": "",
                    "last_name": full_name,
                },
            )

    return persons


def extract_orgs_from_analysis(
    analysis: dict[str, Any],
    deal_fields: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Collect unique organisation names to screen."""
    raw_orgs: set[str] = set()

    corp = analysis.get("corporateStructure", {})

    # Borrower
    borrower = corp.get("borrower", "")
    if (
        isinstance(borrower, str)
        and borrower.strip()
        and "pending" not in borrower.lower()
    ):
        raw_orgs.add(borrower.strip())

    # Guarantors
    for g in corp.get("guarantors", []):
        if isinstance(g, str) and g.strip() and "pending" not in g.lower():
            raw_orgs.add(g.strip())

    # SPVs
    for spv in corp.get("spvs", []):
        if isinstance(spv, str) and spv.strip() and "pending" not in spv.lower():
            raw_orgs.add(spv.strip())

    # Sponsor firm
    sponsor = analysis.get("sponsorDetails", {})
    firm = sponsor.get("firmName", "")
    if isinstance(firm, str) and firm.strip() and "pending" not in firm.lower():
        raw_orgs.add(firm.strip())

    manager = sponsor.get("investmentManager", "")
    if (
        isinstance(manager, str)
        and manager.strip()
        and "pending" not in manager.lower()
    ):
        raw_orgs.add(manager.strip())

    gp = sponsor.get("gpEntity", "")
    if isinstance(gp, str) and gp.strip() and "pending" not in gp.lower():
        raw_orgs.add(gp.strip())

    # Target vehicle
    target = analysis.get("targetVehicle", "")
    if isinstance(target, str) and target.strip() and "pending" not in target.lower():
        raw_orgs.add(target.strip())

    orgs: list[dict[str, str]] = []
    seen: set[str] = set()
    for name in sorted(raw_orgs):
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        orgs.append({"name": name})

    return orgs

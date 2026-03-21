"""Entity extraction — build deduplicated list of entities to search in EDGAR.

Copied verbatim from ic_edgar_engine.py (lines 1010-1234).
This is well-tested production code — no changes except adding name sanitization.

8 entity roles extracted from deal_fields + LLM analysis:
  fund/vehicle, sponsor/manager, borrower, guarantor, spv,
  investment_manager, gp

Smart target detection: identifies when deal_name is actually the sponsor
name, using targetVehicle from LLM analysis as override.
"""
from __future__ import annotations

import re
from typing import Any

import structlog

from data_providers.sec.shared import sanitize_entity_name

logger = structlog.get_logger()


_SKIP_ENTITY_NAMES: set[str] = {
    "", "n/a", "none", "unknown", "tbd", "pending", "pending diligence",
    "...", "various", "see docs", "portfolio companies tbd",
    "various borrowers", "various cannabis operator borrowers",
    "multiple borrowers", "to be determined", "not disclosed",
}


def _normalize_entity_for_dedup(name: str) -> str:
    """Lowercase, strip suffixes like LP/LLC/Inc/Ltd for dedup purposes."""
    s = name.strip().lower()
    s = re.sub(r",?\s*(inc\.?|llc|lp|ltd\.?|limited|corp\.?|plc|co\.?)$", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_searchable_entities(
    deal_fields: dict[str, Any],
    analysis: dict[str, Any] | None = None,
    *,
    ticker: str | None = None,
    instrument_type: str = "UNKNOWN",
) -> list[dict[str, Any]]:
    """Build deduplicated list of entities to search in EDGAR.

    Sources checked (in priority order):
        1. deal_fields["deal_name"]         -> role "fund/vehicle"
        2. deal_fields["sponsor_name"]      -> role "sponsor/manager"
        3. deal_fields["borrower_name"]     -> role "borrower"
        4. analysis.corporateStructure.borrower   -> role "borrower"
        5. analysis.corporateStructure.guarantors -> role "guarantor"
        6. analysis.corporateStructure.spvs       -> role "spv"
        7. analysis.sponsorDetails.investmentManager -> role "investment_manager"
        8. analysis.sponsorDetails.gpEntity        -> role "gp"

    Returns list of dicts:  [{"name": str, "role": str, "ticker": str|None,
                               "is_direct_target": bool, "relationship_desc": str}]
    """
    _ROLE_RELATIONSHIP: dict[str, str] = {
        "fund/vehicle": (
            "This is the investment vehicle under analysis. "
            "EDGAR data for this entity pertains directly to the target."
        ),
        "sponsor/manager": (
            "Manager or sponsor of the target vehicle — a separate legal entity. "
            "Any public fund managed by this sponsor is a DIFFERENT vehicle from "
            "the private fund under review. Financial metrics belong to the "
            "PUBLIC entity, NOT the target vehicle."
        ),
        "borrower": (
            "Underlying borrower in the credit structure. "
            "EDGAR data reflects the borrower's own financials, not the fund's."
        ),
        "guarantor": (
            "Guarantor of obligations within the deal structure. "
            "EDGAR data reflects the guarantor's own financials."
        ),
        "spv": (
            "Special purpose vehicle in the transaction structure. "
            "May or may not be the direct target entity."
        ),
        "investment_manager": (
            "Investment manager / adviser — a separate legal entity. "
            "Any public fund managed by this adviser is a DIFFERENT vehicle. "
            "Financial metrics belong to that public entity, NOT the target."
        ),
        "gp": (
            "General partner of the target vehicle. "
            "EDGAR data reflects the GP entity's own filings."
        ),
    }

    seen_normalized: set[str] = set()
    entities: list[dict[str, Any]] = []

    def _add(
        name: str | None,
        role: str,
        entity_ticker: str | None = None,
        *,
        is_direct_target: bool = False,
    ) -> None:
        if not name or not isinstance(name, str):
            return
        name = name.strip()
        # Sanitize: length cap + control character removal
        sanitized = sanitize_entity_name(name)
        if not sanitized:
            return
        name = sanitized
        if name.lower() in _SKIP_ENTITY_NAMES:
            return
        low = name.lower()
        if low.startswith(("various ", "multiple ", "portfolio companies", "see ")):
            return
        if low.endswith((" tbd", " pending")):
            return
        norm = _normalize_entity_for_dedup(name)
        if not norm or norm in seen_normalized:
            return
        seen_normalized.add(norm)
        entities.append({
            "name": name,
            "role": role,
            "ticker": entity_ticker,
            "is_direct_target": is_direct_target,
            "relationship_desc": _ROLE_RELATIONSHIP.get(role, ""),
        })

    def _is_valid_extracted(val: str | None) -> bool:
        """Check if an LLM-extracted string is a usable entity name."""
        if not val or not isinstance(val, str):
            return False
        low = val.strip().lower()
        return low not in ("", "pending diligence", "n/a", "not specified",
                           "pending", "unknown", "tbd")

    def _names_overlap(a: str, b: str) -> bool:
        """Check if two entity names are substantially the same."""
        na = _normalize_entity_for_dedup(a)
        nb = _normalize_entity_for_dedup(b)
        if not na or not nb:
            return False
        return na == nb or na in nb or nb in na

    # ── Smart target detection ───────────────────────────────────
    deal_name = deal_fields.get("deal_name", "")
    sponsor_name = deal_fields.get("sponsor_name", "")

    target_vehicle_name: str | None = None
    if analysis:
        tv = analysis.get("targetVehicle")
        if _is_valid_extracted(tv):
            target_vehicle_name = tv.strip()  # type: ignore[union-attr]

    deal_is_sponsor = False
    if deal_name and sponsor_name:
        deal_is_sponsor = _names_overlap(deal_name, sponsor_name)
    if not deal_is_sponsor and deal_name and analysis:
        sponsor_det = analysis.get("sponsorDetails") or {}
        if isinstance(sponsor_det, dict):
            firm = sponsor_det.get("firmName")
            if isinstance(firm, str) and _is_valid_extracted(firm) and _names_overlap(deal_name, firm):
                deal_is_sponsor = True

    logger.info(
        "edgar_target_detection",
        deal_name=deal_name,
        target_vehicle=target_vehicle_name,
        deal_is_sponsor=deal_is_sponsor,
    )

    # ── Add entities in priority order ───────────────────────────
    if target_vehicle_name:
        _add(target_vehicle_name, "fund/vehicle", ticker, is_direct_target=True)
        if deal_is_sponsor:
            _add(deal_name, "sponsor/manager")
        else:
            _add(deal_name, "fund/vehicle")
    else:
        if deal_is_sponsor:
            _add(deal_name, "sponsor/manager")
        else:
            _add(deal_name, "fund/vehicle", ticker, is_direct_target=True)

    _add(sponsor_name, "sponsor/manager")
    _add(deal_fields.get("borrower_name"), "borrower")

    if analysis:
        corp = analysis.get("corporateStructure") or {}

        corp_borrower = corp.get("borrower")
        if isinstance(corp_borrower, str) and _is_valid_extracted(corp_borrower):
            borrower_is_target = (
                target_vehicle_name is not None
                and _names_overlap(corp_borrower, target_vehicle_name)
            )
            if borrower_is_target:
                _add(corp_borrower, "fund/vehicle", is_direct_target=True)
            else:
                _add(corp_borrower, "borrower")

        for g in (corp.get("guarantors") or []):
            if isinstance(g, str):
                _add(g, "guarantor")

        for spv in (corp.get("spvs") or []):
            if isinstance(spv, str) and _is_valid_extracted(spv):
                spv_is_target = (
                    target_vehicle_name is not None
                    and _names_overlap(spv, target_vehicle_name)
                )
                if spv_is_target:
                    _add(spv, "fund/vehicle", is_direct_target=True)
                else:
                    _add(spv, "spv")

        sponsor_det = analysis.get("sponsorDetails") or analysis.get("sponsor") or {}
        if isinstance(sponsor_det, dict):
            _add(sponsor_det.get("investmentManager"), "investment_manager")
            _add(sponsor_det.get("gpEntity"), "gp")
            _add(sponsor_det.get("name"), "sponsor/manager")
            _add(sponsor_det.get("firmName"), "sponsor/manager")

    logger.info(
        "edgar_entities_extracted",
        count=len(entities),
        names=[e["name"] for e in entities],
    )
    return entities

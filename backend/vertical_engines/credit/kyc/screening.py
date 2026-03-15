"""Individual entity screening via KYC Spider client.

Imports only from stdlib. Client is injected as parameter.
"""
from __future__ import annotations

import uuid as _uuid
from typing import Any

import structlog

logger = structlog.get_logger()


def run_person_screening(
    client: Any, person: dict, profile_id: str | None, ref_prefix: str = "pipeline",
) -> dict:
    """Screen a single person using the real v3 flow (submit -> check -> result)."""
    reference = f"{ref_prefix}-person-{_uuid.uuid4().hex[:12]}"
    try:
        return client.screen_customer(
            reference=reference,
            customer_type="PERSON",
            first_name=person["first_name"],
            last_name=person["last_name"],
            date_of_birth=None,
            nationality=None,
            datasets=["PEP", "SANCTIONS", "ADVERSE_MEDIA"],
        )
    except Exception as exc:
        logger.warning(
            "kyc_person_screening_failed",
            first_name=person.get("first_name"),
            last_name=person.get("last_name"),
            error=str(exc),
        )
        return {"error": str(exc)}


def run_org_screening(
    client: Any, org: dict, profile_id: str | None, ref_prefix: str = "pipeline",
) -> dict:
    """Screen a single organisation using the real v3 flow."""
    reference = f"{ref_prefix}-org-{_uuid.uuid4().hex[:12]}"
    try:
        return client.screen_customer(
            reference=reference,
            customer_type="ORGANISATION",
            organisation_name=org["name"],
            datasets=["PEP", "SANCTIONS", "ADVERSE_MEDIA"],
        )
    except Exception as exc:
        logger.warning(
            "kyc_org_screening_failed",
            name=org.get("name"),
            error=str(exc),
        )
        return {"error": str(exc)}

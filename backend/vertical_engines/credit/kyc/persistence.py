"""KYC screening DB persistence.

Imports models.py (sibling) for stub ORM classes.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog

from vertical_engines.credit.kyc import models as kyc_models

logger = structlog.get_logger()


def persist_kyc_screenings_to_db(
    db: Any,
    *,
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    kyc_results: dict[str, Any],
    actor_id: str = "ai-engine",
) -> int:
    """Persist pipeline KYC screenings into the KYC Enhanced tables.

    Returns count of screenings persisted.
    """
    count = 0
    all_entries = kyc_results.get("persons", []) + kyc_results.get("organisations", [])

    for entry in all_entries:
        r = entry.get("result", {})
        if r.get("error"):
            continue

        entity_type = entry.get("entity_type", "PERSON")
        name_parts = entry.get("name", "").split(maxsplit=1)

        # Compute per-check-type hit counts
        check_results = r.get("check_results", [])
        pep_count = sum(
            cr.get("hits", 0) for cr in check_results if cr.get("checkId") == "PEP"
        )
        san_count = sum(
            cr.get("hits", 0)
            for cr in check_results
            if cr.get("checkId") in ("SAN", "SANCTIONS")
        )
        adv_count = sum(
            cr.get("hits", 0)
            for cr in check_results
            if cr.get("checkId") in ("AM", "ADVERSE_MEDIA")
        )

        screening = kyc_models.KYCScreening(
            fund_id=fund_id,
            spider_screening_id=r.get("check_id"),
            entity_type=entity_type,
            first_name=name_parts[0]
            if entity_type == "PERSON" and name_parts
            else None,
            last_name=name_parts[1]
            if entity_type == "PERSON" and len(name_parts) > 1
            else (entry.get("name") if entity_type == "PERSON" else None),
            entity_name=entry.get("name") if entity_type == "ORGANISATION" else None,
            profile_id=None,
            datasets=["PEP", "SANCTIONS", "ADVERSE_MEDIA"],
            reference_entity_type="deal",
            reference_entity_id=deal_id,
            reference_label="Deep Review Auto-Screen",
            status="FLAGGED" if r.get("total_hits", 0) > 0 else "CLEARED",
            total_matches=r.get("total_hits", 0),
            pep_hits=pep_count,
            sanctions_hits=san_count,
            adverse_media_hits=adv_count,
            raw_response=r,
            created_by=actor_id,
            updated_by=actor_id,
        )
        db.add(screening)
        db.flush()

        # Add matches from check results
        for cr in check_results:
            check_id = cr.get("checkId", "")
            for mid in cr.get("matchIds", []):
                match_rec = kyc_models.KYCScreeningMatch(
                    fund_id=fund_id,
                    screening_id=screening.id,
                    spider_match_id=mid,
                    matched_name=None,
                    match_score=None,
                    match_type=check_id,
                    dataset_name=check_id,
                    raw_match={"checkId": check_id, "matchId": mid},
                    created_by=actor_id,
                    updated_by=actor_id,
                )
                db.add(match_rec)

        count += 1

    db.flush()
    logger.info("kyc_pipeline_persisted", screenings=count, deal_id=str(deal_id))
    return count

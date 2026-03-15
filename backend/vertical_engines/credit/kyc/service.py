"""KYC screening service — orchestrator.

Never-raises contract: returns dict with summary.skipped=True on failure.
Imports all domain modules (sole orchestrator).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import structlog

from vertical_engines.credit.kyc.entity_extraction import (
    extract_orgs_from_analysis,
    extract_persons_from_analysis,
)
from vertical_engines.credit.kyc.screening import run_org_screening, run_person_screening

logger = structlog.get_logger()


def run_kyc_screenings(
    *,
    analysis: dict[str, Any],
    deal_fields: dict[str, Any],
    index_key_persons: list[str] | None = None,
    sponsor_output: dict[str, Any] | None = None,
    max_persons: int = 30,
    max_orgs: int = 15,
) -> dict[str, Any]:
    """Run KYC Spider screenings for all key persons and organisations.

    Never raises — returns a skipped result on failure.

    Returns a dict with ``persons``, ``organisations``, and ``summary``.
    """
    try:
        return _run_screenings(
            analysis=analysis,
            deal_fields=deal_fields,
            index_key_persons=index_key_persons,
            sponsor_output=sponsor_output,
            max_persons=max_persons,
            max_orgs=max_orgs,
        )
    except Exception:
        logger.error("kyc_pipeline_failed", exc_info=True)
        return {
            "persons": [],
            "organisations": [],
            "summary": {
                "skipped": True,
                "reason": "KYC pipeline encountered an unexpected error",
                "status": "NOT_ASSESSED",
            },
        }


def _run_screenings(
    *,
    analysis: dict[str, Any],
    deal_fields: dict[str, Any],
    index_key_persons: list[str] | None = None,
    sponsor_output: dict[str, Any] | None = None,
    max_persons: int = 30,
    max_orgs: int = 15,
) -> dict[str, Any]:
    """Internal screening logic — may raise."""
    from app.core.config import settings

    if not settings.KYC_SPIDER_PASSWORD:
        logger.info("kyc_pipeline_skip", reason="no KYC_SPIDER_PASSWORD configured")
        return {
            "persons": [],
            "organisations": [],
            "summary": {
                "skipped": True,
                "reason": "KYC Spider credentials not configured",
            },
        }

    from vertical_engines.credit.kyc.client import KYCSpiderClient

    client = KYCSpiderClient(
        base_url=settings.KYC_SPIDER_BASE_URL
        or "https://platform.kycspider.com/api/rest/3.0.0",
        mandator=settings.KYC_SPIDER_MANDATOR,
        user=settings.KYC_SPIDER_USER,
        password=settings.KYC_SPIDER_PASSWORD,
    )
    profile_id = settings.KYC_SPIDER_DEFAULT_PROFILE

    persons = extract_persons_from_analysis(
        analysis, index_key_persons, sponsor_output,
    )[:max_persons]
    orgs = extract_orgs_from_analysis(analysis, deal_fields)[:max_orgs]

    logger.info(
        "kyc_pipeline_start",
        persons=len(persons),
        orgs=len(orgs),
        deal=deal_fields.get("deal_name", "?"),
    )

    person_results: list[dict[str, Any]] = []
    org_results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        person_futures = {
            executor.submit(run_person_screening, client, p, profile_id): ("person", p)
            for p in persons
        }
        org_futures = {
            executor.submit(run_org_screening, client, o, profile_id): ("org", o)
            for o in orgs
        }
        all_futures = {**person_futures, **org_futures}

        for future in as_completed(all_futures):
            entity_type, entity = all_futures[future]
            try:
                result = future.result()
            except Exception as exc:
                logger.warning(
                    "kyc_future_failed",
                    entity_type=entity_type,
                    error=str(exc),
                )
                result = {"error": str(exc)}

            if entity_type == "person":
                person_results.append(
                    {
                        "name": f"{entity['first_name']} {entity['last_name']}".strip(),
                        "entity_type": "PERSON",
                        "result": result,
                    },
                )
            else:
                org_results.append(
                    {
                        "name": entity["name"],
                        "entity_type": "ORGANISATION",
                        "result": result,
                    },
                )

    # Compute summary stats
    total_matches = 0
    pep_hits = 0
    sanctions_hits = 0
    adverse_media_hits = 0
    flagged_entities: list[str] = []

    for entry in person_results + org_results:
        r = entry.get("result", {})
        if r.get("error"):
            continue
        n_hits = r.get("total_hits", 0)
        total_matches += n_hits
        if n_hits > 0:
            flagged_entities.append(entry["name"])
        for cr in r.get("check_results", []):
            check_id = (cr.get("checkId") or "").upper()
            cr_hits = cr.get("hits", 0) or len(cr.get("matchIds", []))
            if check_id == "PEP":
                pep_hits += cr_hits
            elif check_id in ("SAN", "SANCTIONS"):
                sanctions_hits += cr_hits
            elif check_id in ("AM", "ADVERSE_MEDIA"):
                adverse_media_hits += cr_hits

    summary = {
        "skipped": False,
        "total_persons_screened": len(person_results),
        "total_orgs_screened": len(org_results),
        "total_matches": total_matches,
        "pep_hits": pep_hits,
        "sanctions_hits": sanctions_hits,
        "adverse_media_hits": adverse_media_hits,
        "flagged_entities": flagged_entities,
    }

    logger.info(
        "kyc_pipeline_complete",
        persons=len(person_results),
        orgs=len(org_results),
        matches=total_matches,
        pep=pep_hits,
        sanctions=sanctions_hits,
        adverse_media=adverse_media_hits,
    )

    return {
        "persons": person_results,
        "organisations": org_results,
        "summary": summary,
    }

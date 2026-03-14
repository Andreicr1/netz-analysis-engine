"""KYC Pipeline Screening — automated KYC Spider checks for Deep Review.

This module extracts key persons and organisations from the structured
deal analysis and runs KYC Spider screenings (PEP, Sanctions, Adverse Media)
for each entity.  Results are formatted as a Markdown appendix section.

Called from ``deep_review.py`` after Stage 9 (Sponsor & Key Person engine).
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

logger = logging.getLogger("ai_engine.kyc_pipeline")


# ---------------------------------------------------------------------------
# 1. Entity extraction from deal analysis
# ---------------------------------------------------------------------------


def _extract_persons_from_analysis(
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
    from ai_engine.intelligence.sponsor_engine import extract_key_persons_from_analysis

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
            # Single word name — treat as last name
            persons.append(
                {
                    "first_name": "",
                    "last_name": full_name,
                },
            )

    return persons


def _extract_orgs_from_analysis(
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

    # Deal name / target vehicle
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


# ---------------------------------------------------------------------------
# 2. Screening via KYC Spider client
# ---------------------------------------------------------------------------


def _run_person_screening(
    client: Any, person: dict, profile_id: str | None, ref_prefix: str = "pipeline",
) -> dict:
    """Screen a single person using the real v3 flow (submit → check → result)."""
    import uuid as _uuid

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
            "KYC_PERSON_SCREENING_FAILED name=%s %s error=%s",
            person.get("first_name"),
            person.get("last_name"),
            exc,
        )
        return {"error": str(exc)}


def _run_org_screening(
    client: Any, org: dict, profile_id: str | None, ref_prefix: str = "pipeline",
) -> dict:
    """Screen a single organisation using the real v3 flow."""
    import uuid as _uuid

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
            "KYC_ORG_SCREENING_FAILED name=%s error=%s", org.get("name"), exc,
        )
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# 3. Run all screenings
# ---------------------------------------------------------------------------


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

    Returns a dict with ``persons``, ``organisations``, and ``summary``.
    Gracefully handles missing API config by returning an empty result.
    """
    from app.core.config import settings

    if not settings.KYC_SPIDER_PASSWORD:
        logger.info("KYC_PIPELINE_SKIP: no KYC_SPIDER_PASSWORD configured")
        return {
            "persons": [],
            "organisations": [],
            "summary": {
                "skipped": True,
                "reason": "KYC Spider credentials not configured",
            },
        }

    from ai_engine.intelligence.kyc_client import KYCSpiderClient

    client = KYCSpiderClient(
        base_url=settings.KYC_SPIDER_BASE_URL
        or "https://platform.kycspider.com/api/rest/3.0.0",
        mandator=settings.KYC_SPIDER_MANDATOR,
        user=settings.KYC_SPIDER_USER,
        password=settings.KYC_SPIDER_PASSWORD,
    )
    profile_id = settings.KYC_SPIDER_DEFAULT_PROFILE

    persons = _extract_persons_from_analysis(
        analysis, index_key_persons, sponsor_output,
    )[:max_persons]
    orgs = _extract_orgs_from_analysis(analysis, deal_fields)[:max_orgs]

    logger.info(
        "KYC_PIPELINE_START persons=%d orgs=%d deal=%s",
        len(persons),
        len(orgs),
        deal_fields.get("deal_name", "?"),
    )

    person_results: list[dict[str, Any]] = []
    org_results: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        person_futures = {
            executor.submit(_run_person_screening, client, p, profile_id): ("person", p)
            for p in persons
        }
        org_futures = {
            executor.submit(_run_org_screening, client, o, profile_id): ("org", o)
            for o in orgs
        }
        all_futures = {**person_futures, **org_futures}

        for future in as_completed(all_futures):
            entity_type, entity = all_futures[future]
            try:
                result = future.result()
            except Exception as exc:
                if entity_type == "person":
                    logger.warning("KYC_PERSON_FUTURE_FAILED name=%s %s error=%s", entity.get("first_name"), entity.get("last_name"), exc)
                else:
                    logger.warning("KYC_ORG_FUTURE_FAILED name=%s error=%s", entity.get("name"), exc)
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
        # screen_customer() returns total_hits + check_results
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
        "KYC_PIPELINE_COMPLETE persons=%d orgs=%d matches=%d pep=%d sanctions=%d adverse_media=%d",
        len(person_results),
        len(org_results),
        total_matches,
        pep_hits,
        sanctions_hits,
        adverse_media_hits,
    )

    return {
        "persons": person_results,
        "organisations": org_results,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# 4. Build Appendix I — KYC Checks (Markdown)
# ---------------------------------------------------------------------------


def build_kyc_appendix(kyc_results: dict[str, Any], deal_name: str = "") -> str:
    """Format KYC screening results into Markdown for the IC Memorandum appendix.

    Returns a complete ``## Appendix I — KYC Checks`` section.
    """
    summary = kyc_results.get("summary", {})

    if summary.get("skipped"):
        return (
            "## Appendix I — KYC Checks\n\n"
            f"*KYC screening was not performed: {summary.get('reason', 'N/A')}*\n"
        )

    lines: list[str] = [
        "## Appendix I — KYC Checks",
        "",
        f"Automated KYC/AML screening performed via KYC Spider API for deal **{deal_name}**.",
        "",
        "### Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Persons Screened | {summary.get('total_persons_screened', 0)} |",
        f"| Organisations Screened | {summary.get('total_orgs_screened', 0)} |",
        f"| Total Matches | {summary.get('total_matches', 0)} |",
        f"| PEP Hits | {summary.get('pep_hits', 0)} |",
        f"| Sanctions Hits | {summary.get('sanctions_hits', 0)} |",
        f"| Adverse Media Hits | {summary.get('adverse_media_hits', 0)} |",
        "",
    ]

    flagged = summary.get("flagged_entities", [])
    if flagged:
        lines.append("**Flagged Entities:** " + ", ".join(flagged))
        lines.append("")

    # Person results
    person_results = kyc_results.get("persons", [])
    if person_results:
        lines.append("### Person Screenings")
        lines.append("")
        lines.append(
            "| # | Name | Status | Matches | PEP | Sanctions | Adverse Media |",
        )
        lines.append(
            "|---|------|--------|---------|-----|-----------|---------------|",
        )

        for idx, entry in enumerate(person_results, 1):
            r = entry.get("result", {})
            if r.get("error"):
                lines.append(f"| {idx} | {entry['name']} | ERROR | — | — | — | — |")
                continue

            state = r.get("state", "UNKNOWN")
            n_hits = r.get("total_hits", 0)
            pep = sum(
                cr.get("hits", 0)
                for cr in r.get("check_results", [])
                if cr.get("checkId") == "PEP"
            )
            sanc = sum(
                cr.get("hits", 0)
                for cr in r.get("check_results", [])
                if cr.get("checkId") in ("SAN", "SANCTIONS")
            )
            adv = sum(
                cr.get("hits", 0)
                for cr in r.get("check_results", [])
                if cr.get("checkId") in ("AM", "ADVERSE_MEDIA")
            )
            lines.append(
                f"| {idx} | {entry['name']} | {state} | {n_hits} | {pep} | {sanc} | {adv} |",
            )

        lines.append("")

        # Detailed match breakdown for persons with hits
        for entry in person_results:
            r = entry.get("result", {})
            if r.get("error") or r.get("total_hits", 0) == 0:
                continue
            lines.append(f"#### {entry['name']} — Match Details")
            lines.append("")
            lines.append("| Check Type | Match ID | Hits |")
            lines.append("|------------|----------|------|")
            for cr in r.get("check_results", []):
                check_id = cr.get("checkId", "—")
                match_ids = cr.get("matchIds", [])
                hits = cr.get("hits", 0) or len(match_ids)
                if hits > 0:
                    for mid in match_ids or [f"{hits} hit(s)"]:
                        lines.append(f"| {check_id} | {mid} | {hits} |")
            lines.append("")

    # Organisation results
    org_results = kyc_results.get("organisations", [])
    if org_results:
        lines.append("### Organisation Screenings")
        lines.append("")
        lines.append(
            "| # | Entity | Status | Matches | PEP | Sanctions | Adverse Media |",
        )
        lines.append(
            "|---|--------|--------|---------|-----|-----------|---------------|",
        )

        for idx, entry in enumerate(org_results, 1):
            r = entry.get("result", {})
            if r.get("error"):
                lines.append(f"| {idx} | {entry['name']} | ERROR | — | — | — | — |")
                continue

            state = r.get("state", "UNKNOWN")
            n_hits = r.get("total_hits", 0)
            pep = sum(
                cr.get("hits", 0)
                for cr in r.get("check_results", [])
                if cr.get("checkId") == "PEP"
            )
            sanc = sum(
                cr.get("hits", 0)
                for cr in r.get("check_results", [])
                if cr.get("checkId") in ("SAN", "SANCTIONS")
            )
            adv = sum(
                cr.get("hits", 0)
                for cr in r.get("check_results", [])
                if cr.get("checkId") in ("AM", "ADVERSE_MEDIA")
            )
            lines.append(
                f"| {idx} | {entry['name']} | {state} | {n_hits} | {pep} | {sanc} | {adv} |",
            )

        lines.append("")

        # Detailed match breakdown for orgs
        for entry in org_results:
            r = entry.get("result", {})
            if r.get("error") or r.get("total_hits", 0) == 0:
                continue
            lines.append(f"#### {entry['name']} — Match Details")
            lines.append("")
            lines.append("| Check Type | Match ID | Hits |")
            lines.append("|------------|----------|------|")
            for cr in r.get("check_results", []):
                check_id = cr.get("checkId", "—")
                match_ids = cr.get("matchIds", [])
                hits = cr.get("hits", 0) or len(match_ids)
                if hits > 0:
                    for mid in match_ids or [f"{hits} hit(s)"]:
                        lines.append(f"| {check_id} | {mid} | {hits} |")
            lines.append("")

    if not person_results and not org_results:
        lines.append("*No key persons or organisations were identified for screening.*")
        lines.append("")

    lines.append("---")
    lines.append(
        "*Screening powered by KYC Spider v3 API. Results are indicative and require manual review.*",
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 5. Persist KYC results to DB (optional, runs if DB session available)
# ---------------------------------------------------------------------------


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
    from ai_engine.intelligence import kyc_models

    count = 0
    all_entries = kyc_results.get("persons", []) + kyc_results.get("organisations", [])

    for entry in all_entries:
        r = entry.get("result", {})
        if r.get("error"):
            continue

        entity_type = entry.get("entity_type", "PERSON")
        name_parts = entry.get("name", "").split(maxsplit=1)

        # Compute per-check-type hit counts from the new response format
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

        # Add matches from check results (each matchId per check type)
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
    logger.info("KYC_PIPELINE_PERSISTED screenings=%d deal_id=%s", count, deal_id)
    return count

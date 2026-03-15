"""KYC appendix builder — formats screening results as Markdown.

No sibling imports — works on plain dicts.
"""
from __future__ import annotations

from typing import Any


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
        lines.extend(_format_entity_table("Person Screenings", "Name", person_results))

    # Organisation results
    org_results = kyc_results.get("organisations", [])
    if org_results:
        lines.extend(_format_entity_table("Organisation Screenings", "Entity", org_results))

    if not person_results and not org_results:
        lines.append("*No key persons or organisations were identified for screening.*")
        lines.append("")

    lines.append("---")
    lines.append(
        "*Screening powered by KYC Spider v3 API. Results are indicative and require manual review.*",
    )

    return "\n".join(lines)


def _format_entity_table(
    title: str, name_col: str, entries: list[dict[str, Any]],
) -> list[str]:
    """Format a screening results table + match details for a set of entities."""
    lines: list[str] = [
        f"### {title}",
        "",
        f"| # | {name_col} | Status | Matches | PEP | Sanctions | Adverse Media |",
        f"|---|{'---' * len(name_col)}|--------|---------|-----|-----------|---------------|",
    ]

    for idx, entry in enumerate(entries, 1):
        r = entry.get("result", {})
        if r.get("error"):
            lines.append(f"| {idx} | {entry['name']} | ERROR | — | — | — | — |")
            continue

        state = r.get("state", "UNKNOWN")
        n_hits = r.get("total_hits", 0)
        pep = _sum_check_hits(r, "PEP")
        sanc = _sum_check_hits(r, "SAN", "SANCTIONS")
        adv = _sum_check_hits(r, "AM", "ADVERSE_MEDIA")
        lines.append(
            f"| {idx} | {entry['name']} | {state} | {n_hits} | {pep} | {sanc} | {adv} |",
        )

    lines.append("")

    # Detailed match breakdown for entities with hits
    for entry in entries:
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

    return lines


def _sum_check_hits(result: dict, *check_ids: str) -> int:
    """Sum hits across check results matching any of the given check IDs."""
    return sum(
        cr.get("hits", 0)
        for cr in result.get("check_results", [])
        if cr.get("checkId") in check_ids
    )

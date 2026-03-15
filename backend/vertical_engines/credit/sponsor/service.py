"""Sponsor analysis service — orchestrator.

Never-raises contract: returns dict with status='NOT_ASSESSED' on failure.
Keeps existing dict returns — no premature dataclass formalization.

Imports person_extraction (domain module) and external dependencies.
"""
from __future__ import annotations

from typing import Any

import structlog

from vertical_engines.credit.sponsor.person_extraction import (
    extract_key_persons_from_analysis,
)

logger = structlog.get_logger()


def analyze_sponsor(
    *,
    corpus: str,
    deal_fields: dict[str, Any],
    analysis: dict[str, Any] | None = None,
    call_openai_fn: Any = None,
    fund_governance_context: str | None = None,
    index_key_persons: list[str] | None = None,
    sponsor_evidence_text: str | None = None,
    sponsor_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run sponsor & key person analysis on deal documentation.

    Never raises — returns NOT_ASSESSED dict on failure.

    Args:
        corpus: Deal document text (already throttled by caller).
        deal_fields: Dict with deal_name, sponsor_name, etc.
        analysis: Structured analysis dict (for key person extraction).
        call_openai_fn: Callable matching
            ``fn(system, user, *, max_tokens) -> dict`` signature.
        index_key_persons: Pre-identified key person names from the
            Azure Search index ``key_persons_mentioned`` field.
        sponsor_evidence_text: Optional ch04_sponsor-specific evidence text.
        sponsor_chunks: Raw enriched chunks relevant to sponsor analysis.

    Returns:
        Sponsor analysis dict conforming to the output schema.
        Returns a default NOT_ASSESSED dict if inputs are insufficient.
    """
    try:
        return _run_analysis(
            corpus=corpus,
            deal_fields=deal_fields,
            analysis=analysis,
            call_openai_fn=call_openai_fn,
            fund_governance_context=fund_governance_context,
            index_key_persons=index_key_persons,
            sponsor_evidence_text=sponsor_evidence_text,
            sponsor_chunks=sponsor_chunks,
        )
    except Exception:
        logger.error("sponsor_analysis_failed", exc_info=True)
        return _default_output("Sponsor analysis encountered an unexpected error.")


def _run_analysis(
    *,
    corpus: str,
    deal_fields: dict[str, Any],
    analysis: dict[str, Any] | None = None,
    call_openai_fn: Any = None,
    fund_governance_context: str | None = None,
    index_key_persons: list[str] | None = None,
    sponsor_evidence_text: str | None = None,
    sponsor_chunks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Internal analysis logic — may raise."""
    from ai_engine.prompts import prompt_registry
    from app.domains.credit.modules.ai.evidence_selector import (
        curate_chunks_by_chapter,
        deduplicate_governance_red_flags,
    )

    sponsor_name = deal_fields.get("sponsor_name", "").strip()

    # ── Merge key persons from ALL sources ────────────────────────
    all_key_persons: list[str] = []
    if analysis:
        all_key_persons.extend(extract_key_persons_from_analysis(analysis))
    if index_key_persons:
        all_key_persons.extend(index_key_persons)

    # Deduplicate preserving order
    seen_kp: set[str] = set()
    unique_key_persons: list[str] = []
    for name in all_key_persons:
        key = name.lower().strip()
        if key and key not in seen_kp and key != "not specified":
            seen_kp.add(key)
            unique_key_persons.append(name)

    key_persons_text = ""
    if unique_key_persons:
        key_persons_text = (
            f"\n\nKey persons identified from documents ({len(unique_key_persons)} names): "
            f"{', '.join(unique_key_persons)}\n"
            f"You MUST include ALL of these persons in your key_persons output. "
            f"For each person, extract their title, role, and background from "
            f"the evidence below."
        )

    # If no sponsor and no corpus, return default
    if not sponsor_name and not corpus.strip():
        logger.info("sponsor_analysis_skipped", reason="no sponsor or corpus")
        return _default_output("No sponsor information or deal documents available.")

    if call_openai_fn is None:
        logger.warning("sponsor_analysis_no_llm")
        return _default_output("LLM not available for sponsor analysis.")

    # Build user prompt — prefer curated sponsor chunks over raw corpus.
    SPONSOR_CORPUS_LIMIT = 60_000

    if sponsor_chunks:
        curated_result = curate_chunks_by_chapter(
            sponsor_chunks,
            "sponsor",
            max_chunks=12,
            max_chars_per_chunk=2000,
        )
        curated_sponsor_chunks, sponsor_curation_meta = curated_result
        effective_corpus = "\n\n---\n\n".join(
            f"[{c.get('title', c.get('doc_type', 'unknown'))} | "
            f"pages {c.get('page_start', '?')}-{c.get('page_end', '?')}]\n"
            f"{c.get('content', '')}"
            for c in curated_sponsor_chunks
        )
        logger.info(
            "sponsor_evidence_curated",
            original=sponsor_curation_meta.get("original_count", 0),
            final=sponsor_curation_meta.get("final_count", 0),
        )
    else:
        effective_corpus = sponsor_evidence_text if sponsor_evidence_text else corpus

    corpus_trimmed = (
        effective_corpus[:SPONSOR_CORPUS_LIMIT]
        if len(effective_corpus) > SPONSOR_CORPUS_LIMIT
        else effective_corpus
    )

    # Optional fund-governance context (IC composition, board, etc.)
    governance_section = ""
    if fund_governance_context:
        governance_section = (
            f"\n=== FUND GOVERNANCE CONTEXT (from fund constitution / governance docs) ===\n"
            f"{fund_governance_context}\n\n"
        )

    user_content = (
        f"=== DEAL INFORMATION ===\n"
        f"Deal Name: {deal_fields.get('deal_name', 'Unknown')}\n"
        f"Sponsor: {sponsor_name or 'Not identified'}\n"
        f"Currency: {deal_fields.get('currency', 'USD')}\n"
        f"Amount: {deal_fields.get('requested_amount', 'Not specified')}\n"
        f"{key_persons_text}\n\n"
        f"{governance_section}"
        f"=== DEAL DOCUMENTATION (full corpus for sponsor due diligence) ===\n"
        f"{corpus_trimmed}\n"
    )

    logger.info(
        "sponsor_analysis_start",
        sponsor_name=sponsor_name,
        corpus_chars=len(corpus_trimmed),
        using_sponsor_evidence=bool(sponsor_evidence_text),
        index_key_persons_count=len(unique_key_persons),
    )

    system_prompt = prompt_registry.render("intelligence/sponsor_assessment.j2")
    data = call_openai_fn(system_prompt, user_content, max_tokens=6000)

    # Validate output shape
    if not isinstance(data, dict):
        return _default_output("Sponsor analysis returned invalid response.")

    # Ensure required keys
    for key in (
        "sponsor_profile",
        "key_persons",
        "governance_red_flags",
        "reputation_signals",
        "open_due_diligence_requests",
    ):
        if key not in data:
            data[key] = [] if key != "sponsor_profile" else _default_sponsor_profile()

    # ── Governance red flag deduplication ──────────────────────────
    raw_flags = data.get("governance_red_flags", [])
    if raw_flags and len(raw_flags) > 1:
        deduped_flags = deduplicate_governance_red_flags(
            raw_flags,
            similarity_threshold=0.80,
            max_flags=6,
        )
        data["governance_red_flags"] = deduped_flags
        data["_governance_dedup_meta"] = {
            "original_count": len(raw_flags),
            "final_count": len(deduped_flags),
            "removed": len(raw_flags) - len(deduped_flags),
        }
        logger.info(
            "sponsor_governance_dedup",
            original=len(raw_flags),
            final=len(deduped_flags),
        )

    logger.info(
        "sponsor_analysis_complete",
        key_persons_count=len(data.get("key_persons", [])),
        red_flags_count=len(data.get("governance_red_flags", [])),
    )

    return data


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


def _default_sponsor_profile() -> dict[str, str]:
    return {
        "name": "Not specified",
        "entity_type": "Not specified",
        "domicile": "Not specified",
        "role_in_transaction": "Not specified",
        "track_record_summary": "Not specified",
        "aum_or_fund_size": "Not specified",
        "years_active": "Not specified",
    }


def _default_output(reason: str) -> dict[str, Any]:
    return {
        "sponsor_profile": _default_sponsor_profile(),
        "key_persons": [],
        "governance_red_flags": [],
        "reputation_signals": [],
        "open_due_diligence_requests": [],
        "status": "NOT_ASSESSED",
        "reason": reason,
    }

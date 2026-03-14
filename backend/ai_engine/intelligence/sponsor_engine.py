"""Sponsor & Key Person Intelligence Engine — institutional due diligence.

Analyses sponsor identity, key persons, governance structure, and
reputation signals from deal documentation.  Produces an independent
institutional assessment — NOT a deck rewrite.

Design rules:
  • No accusations — only factual risk signals with evidence anchors.
  • No copied deck language — original analytical voice.
  • No fabricated information — if data is absent, say so.
  • No external API calls (future extension) — current version is
    document-only.

Output schema:
    {
        "sponsor_profile": {...},
        "key_persons": [...],
        "governance_red_flags": [...],
        "reputation_signals": [...],
        "open_due_diligence_requests": [...]
    }
"""

from __future__ import annotations

import logging
import re
from typing import Any

from ai_engine.prompts import prompt_registry
from app.domains.credit.modules.ai.evidence_selector import (
    curate_chunks_by_chapter,
    deduplicate_governance_red_flags,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Key person extraction (deterministic)
# ---------------------------------------------------------------------------


def extract_key_persons_from_analysis(analysis: dict[str, Any]) -> list[str]:
    """Extract key person names from the structured deal analysis.

    Sources:
      • corporateStructure.guarantors
      • corporateStructure.ownershipChain
      • corporateStructure.borrower (if a person name)
      • investmentTerms (any named signatories)

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
    """Heuristic: a person name has 2-4 capitalized words, no corp suffixes."""
    if not text or len(text) > 60:
        return False
    corp_suffixes = {
        "llc",
        "ltd",
        "inc",
        "corp",
        "plc",
        "gmbh",
        "sa",
        "ag",
        "lp",
        "llp",
        "fund",
        "trust",
        "holdings",
        "capital",
        "management",
        "partners",
        "group",
        "limited",
        "offshore",
        "advisers",
        "advisors",
        "investments",
        "investors",
        "company",
        "estate",
        "opps",
        "opportunities",
        "credit",
        "equity",
        "preferred",
        "senior",
        "spv",
        "spvs",
        "vehicles",
        "real",
        "project",
        "wealth",
        "housing",
        "international",
        "global",
        "ventures",
        "securities",
        "associates",
        "enterprises",
        "financial",
        "asset",
        "assets",
        "services",
        "advisories",
        "consulting",
    }
    words = text.strip().split()
    if len(words) < 2 or len(words) > 5:
        return False
    lower_words = {w.lower().rstrip(".,") for w in words}
    if lower_words & corp_suffixes:
        return False
    return True


def _extract_names_from_text(text: str) -> list[str]:
    """Extract capitalized multi-word sequences that look like person names."""
    # Pattern: 2-4 consecutive capitalized words
    pattern = r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"
    matches = re.findall(pattern, text)
    return [m for m in matches if _looks_like_person_name(m)]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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

    Args:
        corpus: Deal document text (already throttled by caller).
        deal_fields: Dict with deal_name, sponsor_name, etc.
        analysis: Structured analysis dict (for key person extraction).
        call_openai_fn: Callable matching
            ``fn(system, user, *, max_tokens) → dict`` signature.
            Injected from the orchestrator to reuse the centralised
            OpenAI provider with budget tracking.
        index_key_persons: Pre-identified key person names from the
            Azure Search index ``key_persons_mentioned`` field.
            These names were extracted during chunk enrichment and
            provide high-recall seeding for the LLM.
        sponsor_evidence_text: Optional ch04_sponsor-specific evidence
            text.  When provided, this replaces the generic corpus
            for sponsor analysis — it contains the most relevant
            chunks (management bios, org charts, governance docs)
            already selected by the per-chapter retrieval pipeline.
        sponsor_chunks: Raw enriched chunks relevant to sponsor analysis.
            When provided, these are curated via evidence_selector before
            being passed to the LLM instead of using the raw corpus.

    Returns:
        Sponsor analysis dict conforming to the output schema.
        Returns a default NOT_ASSESSED dict if inputs are insufficient.
    """
    sponsor_name = deal_fields.get("sponsor_name", "").strip()

    # ── Merge key persons from ALL sources ────────────────────────
    # 1) Deterministic extraction from structured analysis
    # 2) Pre-identified names from Azure Search key_persons_mentioned
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
        logger.info("SPONSOR_ANALYSIS_SKIPPED — no sponsor or corpus")
        return _default_output("No sponsor information or deal documents available.")

    if call_openai_fn is None:
        logger.warning("SPONSOR_ANALYSIS_NO_LLM — returning default")
        return _default_output("LLM not available for sponsor analysis.")

    # Build user prompt — prefer curated sponsor chunks over raw corpus.
    # If sponsor_chunks are provided, curate them through evidence_selector
    # for deduplication and relevance maximization.
    SPONSOR_CORPUS_LIMIT = 60_000

    if sponsor_chunks:
        # Curate sponsor chunks via evidence_selector
        curated_result = curate_chunks_by_chapter(
            sponsor_chunks,
            "sponsor",
            max_chunks=12,
            max_chars_per_chunk=2000,
        )
        # curate_chunks_by_chapter returns (chunks, meta)
        curated_sponsor_chunks, sponsor_curation_meta = curated_result
        # Build curated corpus text from curated chunks
        effective_corpus = "\n\n---\n\n".join(
            f"[{c.get('title', c.get('doc_type', 'unknown'))} | "
            f"pages {c.get('page_start', '?')}-{c.get('page_end', '?')}]\n"
            f"{c.get('content', '')}"
            for c in curated_sponsor_chunks
        )
        logger.info(
            "SPONSOR_EVIDENCE_CURATED original=%d final=%d",
            sponsor_curation_meta.get("original_count", 0),
            sponsor_curation_meta.get("final_count", 0),
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
        "SPONSOR_ANALYSIS_START",
        extra={
            "sponsor_name": sponsor_name,
            "corpus_chars": len(corpus_trimmed),
            "using_sponsor_evidence": bool(sponsor_evidence_text),
            "index_key_persons_count": len(unique_key_persons),
        },
    )

    try:
        system_prompt = prompt_registry.render("intelligence/sponsor_assessment.j2")
        data = call_openai_fn(system_prompt, user_content, max_tokens=6000)
    except (ValueError, Exception) as exc:
        logger.warning("SPONSOR_ANALYSIS_FAILED", extra={"error": str(exc)})
        return _default_output(f"Sponsor analysis LLM call failed: {exc}")

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
    # Apply semantic deduplication on governance_red_flags to eliminate
    # near-duplicate structural issues (similarity > 0.80 → merge).
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
            "SPONSOR_GOVERNANCE_DEDUP original=%d final=%d",
            len(raw_flags),
            len(deduped_flags),
        )

    logger.info(
        "SPONSOR_ANALYSIS_COMPLETE",
        extra={
            "key_persons_count": len(data.get("key_persons", [])),
            "red_flags_count": len(data.get("governance_red_flags", [])),
        },
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

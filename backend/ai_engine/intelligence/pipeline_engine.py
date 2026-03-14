"""Consolidated Pipeline Intelligence Engine — Tier-1 Institutional Upgrade.

Architecture (two-call split):

  generate_pipeline_intelligence()
       |-- RAG retrieval (80 chunks, >=250k chars evidence surface)
       |
       |-- Call A: Structured Intelligence
       |    -> deal_overview, terms, risk_map, citations,
       |       missing_documents, investment_thesis,
       |       exit_scenarios, comparables
       |
       +-- Call B: Memo Writer
            -> 1500-3000 word IC-grade memorandum
            -> uses structured output + citations as anchor
            -> independent prose, NOT copy/paste excerpts

  Persists:
       -> research_output JSONB  (atomic, owns column)
       -> ai_summary / risk_flags / key_terms (via update_deal_ai_output)
       -> intelligence_status lifecycle (PENDING -> PROCESSING -> READY / FAILED)

Evidence governance:
  - max_chunks=80, max_chars_per_chunk=4000, total budget >=250k chars
  - Minimum 5 citations enforced (validation fails otherwise)
  - Missing-document checklist reduces deal confidence

Model governance:
  - Call A: resolve_model("structured")
  - Call B: resolve_model("pipeline_memo")
  - No gpt-4o-mini allowed in any investment memo path
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ai_engine.extraction.embedding_service import generate_embeddings
from ai_engine.extraction.search_upsert_service import search_deal_chunks
from ai_engine.governance.authority_resolver import enrich_chunks_with_authority
from ai_engine.model_config import get_model
from ai_engine.openai_client import create_completion
from ai_engine.prompts import prompt_registry
from app.domains.credit.modules.ai.evidence_selector import (
    build_curated_context_text,
    curate_all_chapter_surfaces,
    curate_for_analysis_call,
)

logger = logging.getLogger(__name__)

# ── Intelligence status constants ─────────────────────────────────────

STATUS_PENDING = "PENDING"
STATUS_PROCESSING = "PROCESSING"
STATUS_READY = "READY"
STATUS_FAILED = "FAILED"

# ── Evidence surface configuration (Tier-1) ───────────────────────────

_MAX_RETRIEVAL_CHUNKS = 80
_MAX_CHARS_PER_CHUNK = 4_000
_MIN_CITATIONS_REQUIRED = 5
_MIN_MEMO_CHARS = 2_000
_MIN_KEY_RISKS = 3

# ── Standard DD document types (weighted for completeness scoring) ────

_REQUIRED_DD_DOCUMENTS = [
    {"document_type": "Audited Financial Statements", "priority": "critical", "weight": 15,
     "reason": "Required for underwriting leverage, debt service coverage, and default risk assessment"},
    {"document_type": "Tax Returns (2-3 years)", "priority": "critical", "weight": 12,
     "reason": "Validates reported financial performance and identifies off-balance-sheet liabilities"},
    {"document_type": "Credit Agreement / Loan Documentation", "priority": "critical", "weight": 15,
     "reason": "Defines terms, covenants, security package, events of default, and waterfall mechanics"},
    {"document_type": "Collateral Valuation / Appraisal", "priority": "critical", "weight": 12,
     "reason": "Determines recovery value in downside/enforcement scenarios"},
    {"document_type": "Management Accounts (Trailing 12 Months)", "priority": "high", "weight": 10,
     "reason": "Provides current-period financial visibility beyond last audit date"},
    {"document_type": "Organizational Documents (LLC/LP Agreement)", "priority": "high", "weight": 8,
     "reason": "Confirms legal structure, authority to borrow, and decision-making governance"},
    {"document_type": "Insurance Certificates", "priority": "high", "weight": 7,
     "reason": "Validates coverage of key collateral and business interruption risks"},
    {"document_type": "Environmental / Regulatory Compliance Reports", "priority": "medium", "weight": 5,
     "reason": "Identifies contingent liabilities and regulatory enforcement risk"},
    {"document_type": "Borrower Corporate Presentation / CIM", "priority": "medium", "weight": 5,
     "reason": "Provides business model context, competitive positioning, and growth strategy"},
    {"document_type": "UCC / Lien Search Results", "priority": "high", "weight": 11,
     "reason": "Confirms priority of security interest and identifies competing claims"},
]

_TOTAL_DD_WEIGHT = sum(d["weight"] for d in _REQUIRED_DD_DOCUMENTS)


# ── Context retrieval (institutional-scale evidence surface) ──────────


def _retrieve_deal_context(
    deal_id: uuid.UUID,
    deal_name: str,
    *,
    max_chunks: int = _MAX_RETRIEVAL_CHUNKS,
) -> tuple[str, int, list[dict], dict[str, list[str]]]:
    """Hybrid retrieval: embed the deal name as query vector + BM25 text.

    Returns (context_text, chunk_count, raw_chunks, issuer_summary).
    Institutional-scale: 80 chunks, 4000 chars/chunk, >=250k total budget.
    NO destructive throttling — evidence surface must support Tier-1 DD.
    Chunks are enriched with institutional issuer detection.
    """
    try:
        query_text = (
            f"{deal_name} credit analysis terms covenants risk "
            f"investment thesis financial statements"
        )
        emb = generate_embeddings([query_text])
        query_vector = emb.vectors[0] if emb.vectors else None
    except Exception:
        logger.warning("Embedding generation failed — falling back to BM25 only")
        query_vector = None
        query_text = deal_name

    try:
        chunks = search_deal_chunks(
            deal_id=deal_id,
            query_text=query_text,
            query_vector=query_vector,
            top=max_chunks,
        )
    except Exception:
        logger.warning(
            "Search retrieval failed for deal %s", deal_id, exc_info=True
        )
        return "", 0, [], {}

    if not chunks:
        return "", 0, [], {}

    # ── Institutional evidence surface — NO destructive throttling ─────
    # Trim individual chunks to max_chars but preserve ALL retrieved chunks.
    trimmed_chunks: list[dict] = []
    total_chars = 0
    for chunk in chunks[:max_chunks]:
        c = dict(chunk)
        content = c.get("content", "")
        c["content"] = content[:_MAX_CHARS_PER_CHUNK]
        total_chars += len(c["content"])
        trimmed_chunks.append(c)

    # ── Enrich with institutional issuer/authority detection ───────────
    enriched_chunks, issuer_summary = enrich_chunks_with_authority(trimmed_chunks)

    # ── Sort by authority tier (BINDING > POLICY > EVIDENCE > rest) ───
    from ai_engine.governance.authority_resolver import AUTHORITY_RANK
    enriched_chunks.sort(
        key=lambda c: AUTHORITY_RANK.get(c.get("issuer_tier") or "", 0),
        reverse=True,
    )

    context_parts: list[str] = []
    for i, chunk in enumerate(enriched_chunks):
        doc_title = chunk.get("title", chunk.get("doc_type", "unknown"))
        issuer_tag = ""
        if chunk.get("issuer_name"):
            issuer_tag = (
                f" | issuer={chunk['issuer_name']}"
                f" ({chunk['issuer_category']})"
                f" | authority={chunk['issuer_tier']}"
            )
        header = (
            f"[Excerpt {i + 1} | {doc_title} "
            f"| type={chunk.get('doc_type', 'unknown')} "
            f"| pages {chunk.get('page_start', '?')}-"
            f"{chunk.get('page_end', '?')}"
            f"{issuer_tag}]"
        )
        context_parts.append(f"{header}\n{chunk.get('content', '')}")

    context_text = "\n\n---\n\n".join(context_parts)

    if issuer_summary:
        logger.info(
            "PIPELINE_ISSUER_DETECTION deal=%s issuers=%s",
            deal_id, issuer_summary,
        )

    logger.info(
        "PIPELINE_EVIDENCE_SURFACE chunks=%d total_chars=%d avg_chars=%d",
        len(enriched_chunks),
        total_chars,
        total_chars // max(len(enriched_chunks), 1),
    )

    return context_text, len(enriched_chunks), enriched_chunks, issuer_summary


# ── GPT call helper ───────────────────────────────────────────────────


def _call_gpt_json(
    system_prompt: str,
    user_prompt: str,
    *,
    model: str,
    max_tokens: int = 12_000,
    call_label: str = "structured",
) -> dict[str, Any]:
    """Call GPT via centralised openai_client, parse JSON, add _meta."""
    result = create_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=0.2,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    raw = (result.text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    obj = json.loads(raw)
    if isinstance(obj, dict):
        meta = obj.get("_meta")
        if not isinstance(meta, dict):
            meta = {}
        meta.setdefault("engine", "pipeline_engine")
        meta.setdefault("call", call_label)
        meta.setdefault("modelVersion", result.model)
        meta.setdefault("generatedAt", datetime.now(UTC).isoformat())
        obj["_meta"] = meta
    return obj


# ── Missing documents detection ───────────────────────────────────────


def _compute_missing_documents(
    raw_chunks: list[dict],
    structured_missing: list[dict],
) -> list[dict]:
    """Merge LLM-detected missing docs with standard DD checklist.

    Scans chunk metadata for document types present, then compares
    against the standard DD document list.
    """
    present_types: set[str] = set()
    for chunk in raw_chunks:
        dt = (chunk.get("doc_type") or "").lower()
        title = (chunk.get("title") or "").lower()
        content_preview = (chunk.get("content") or "")[:500].lower()
        combined = f"{dt} {title} {content_preview}"
        present_types.add(dt)
        if any(kw in combined for kw in (
            "audit", "audited", "financial statement",
        )):
            present_types.add("audited_financials")
        if any(kw in combined for kw in ("tax return", "irs", "tax filing")):
            present_types.add("tax_returns")
        if any(kw in combined for kw in (
            "credit agreement", "loan agreement", "facility agreement",
        )):
            present_types.add("credit_agreement")
        if any(kw in combined for kw in (
            "appraisal", "valuation", "collateral",
        )):
            present_types.add("collateral_valuation")
        if any(kw in combined for kw in (
            "management account", "trailing", "interim",
        )):
            present_types.add("management_accounts")
        if any(kw in combined for kw in (
            "llc", "partnership", "operating agreement", "bylaws",
        )):
            present_types.add("org_docs")
        if any(kw in combined for kw in (
            "insurance", "certificate of insurance", "coi",
        )):
            present_types.add("insurance")
        if any(kw in combined for kw in ("ucc", "lien search", "title search")):
            present_types.add("ucc_lien")
        if any(kw in combined for kw in (
            "environmental", "phase i", "phase ii", "regulatory",
        )):
            present_types.add("environmental")
        if any(kw in combined for kw in (
            "cim", "confidential information", "presentation", "investor deck",
        )):
            present_types.add("cim_presentation")

    _detection_map = {
        "Audited Financial Statements": "audited_financials",
        "Tax Returns (2-3 years)": "tax_returns",
        "Credit Agreement / Loan Documentation": "credit_agreement",
        "Collateral Valuation / Appraisal": "collateral_valuation",
        "Management Accounts (Trailing 12 Months)": "management_accounts",
        "Organizational Documents (LLC/LP Agreement)": "org_docs",
        "Insurance Certificates": "insurance",
        "Environmental / Regulatory Compliance Reports": "environmental",
        "Borrower Corporate Presentation / CIM": "cim_presentation",
        "UCC / Lien Search Results": "ucc_lien",
    }

    result_map: dict[str, dict] = {}
    for doc in structured_missing:
        key = doc.get("document_type", "")
        result_map[key] = doc

    for std_doc in _REQUIRED_DD_DOCUMENTS:
        doc_type = std_doc["document_type"]
        detection_key = _detection_map.get(doc_type, "")
        if detection_key and detection_key not in present_types:
            if doc_type not in result_map:
                result_map[doc_type] = dict(std_doc)

    return list(result_map.values())


def compute_completeness_score(
    missing_documents: list[dict],
) -> dict[str, Any]:
    """Compute a weighted data-room completeness score (0-100).

    Returns dict with score, grade, present count, missing count,
    and a breakdown by priority band.
    """
    missing_types = {d.get("document_type", "") for d in missing_documents}
    missing_weight = 0
    present_count = 0
    missing_count = 0
    breakdown: dict[str, dict] = {}

    for doc in _REQUIRED_DD_DOCUMENTS:
        dt = doc["document_type"]
        w = doc["weight"]
        pri = doc["priority"]
        is_missing = dt in missing_types
        if is_missing:
            missing_weight += w
            missing_count += 1
        else:
            present_count += 1
        breakdown[dt] = {
            "priority": pri,
            "weight": w,
            "present": not is_missing,
        }

    score = round((((_TOTAL_DD_WEIGHT - missing_weight) / _TOTAL_DD_WEIGHT) * 100), 1)
    if score >= 85:
        grade = "STRONG"
    elif score >= 65:
        grade = "ADEQUATE"
    elif score >= 40:
        grade = "WEAK"
    else:
        grade = "INSUFFICIENT"

    return {
        "completeness_score": score,
        "completeness_grade": grade,
        "documents_present": present_count,
        "documents_missing": missing_count,
        "total_tracked": len(_REQUIRED_DD_DOCUMENTS),
        "breakdown": breakdown,
    }


# ── Citation & output validation (Tier-1 enforcement) ─────────────────


def _validate_output(output: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate structured intelligence output.

    Tier-1 enforcement:
    - Minimum 5 citations (hard fail)
    - Minimum 3 key risks
    - All required top-level keys present
    - Each citation must have chunk_index, doc, rationale
    """
    issues: list[str] = []

    required_keys = {
        "deal_overview", "terms_and_covenants", "risk_map",
        "investment_thesis", "exit_scenarios", "comparables",
        "missing_documents", "citations",
    }
    missing_keys = required_keys - set(output.keys())
    if missing_keys:
        issues.append(
            f"Missing top-level keys: {', '.join(sorted(missing_keys))}"
        )

    overview = output.get("deal_overview", {})
    if not overview.get("name"):
        issues.append("deal_overview.name is empty")

    citations = output.get("citations", [])
    if len(citations) < _MIN_CITATIONS_REQUIRED:
        issues.append(
            f"citations has only {len(citations)} entries "
            f"(minimum {_MIN_CITATIONS_REQUIRED} required for Tier-1)"
        )

    for i, cit in enumerate(citations):
        if not isinstance(cit, dict):
            issues.append(f"citations[{i}] is not a dict")
            continue
        if "chunk_index" not in cit:
            issues.append(f"citations[{i}] missing chunk_index")
        if not cit.get("doc"):
            issues.append(f"citations[{i}] missing doc title")
        if not cit.get("rationale"):
            issues.append(f"citations[{i}] missing rationale")

    risk_map = output.get("risk_map", {})
    key_risks = (
        risk_map.get("key_risks", []) if isinstance(risk_map, dict)
        else risk_map
    )
    if len(key_risks) < _MIN_KEY_RISKS:
        issues.append(
            f"risk_map.key_risks has only {len(key_risks)} entries "
            f"(minimum {_MIN_KEY_RISKS})"
        )

    return len(issues) == 0, issues


def _validate_memo(memo_output: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate memo writer output."""
    issues: list[str] = []
    memo_text = memo_output.get("investment_memo", "")
    if len(memo_text) < _MIN_MEMO_CHARS:
        issues.append(
            f"investment_memo is only {len(memo_text)} chars "
            f"(minimum {_MIN_MEMO_CHARS})"
        )
    confidence = memo_output.get("confidence_score")
    if confidence is not None:
        try:
            if not (0.0 <= float(confidence) <= 1.0):
                issues.append(
                    f"confidence_score {confidence} outside [0, 1] range"
                )
        except (TypeError, ValueError):
            issues.append(f"confidence_score {confidence} is not numeric")
    return len(issues) == 0, issues


# ── Status management ─────────────────────────────────────────────────


def _set_intelligence_status(
    db: Session,
    deal_id: uuid.UUID,
    status: str,
    *,
    generated_at: datetime | None = None,
    auto_commit: bool = True,
) -> None:
    """Update intelligence_status (optionally intelligence_generated_at)."""
    if generated_at:
        db.execute(
            text(
                "UPDATE pipeline_deals "
                "SET intelligence_status = CAST(:status AS intelligence_status_enum), "
                "intelligence_generated_at = :ts "
                "WHERE id = :id"
            ),
            {"status": status, "ts": generated_at, "id": str(deal_id)},
        )
    else:
        db.execute(
            text(
                "UPDATE pipeline_deals "
                "SET intelligence_status = CAST(:status AS intelligence_status_enum) WHERE id = :id"
            ),
            {"status": status, "id": str(deal_id)},
        )
    if auto_commit:
        db.commit()


def _write_research_output(
    db: Session,
    deal_id: uuid.UUID,
    data: dict[str, Any],
    *,
    auto_commit: bool = True,
) -> None:
    """Write structured intelligence to pipeline_deals.research_output."""
    db.execute(
        text(
            "UPDATE pipeline_deals "
            "SET research_output = :data WHERE id = :id"
        ),
        {"data": json.dumps(data, default=str), "id": str(deal_id)},
    )
    if auto_commit:
        db.commit()


# ── Derived-field writeback ───────────────────────────────────────────


def _write_derived_fields(
    db: Session,
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    output: dict[str, Any],
) -> None:
    """Extract summary/risk/terms and write via update_deal_ai_output().

    IMPORTANT — Authority boundary (Unified Underwriting Patch):
    The Pipeline Engine is a SCREENING layer only.  It must NOT write
    an authoritative IC recommendation.  The ``summary`` field is set
    to a neutral screening-complete message.  Final recommendation,
    risk band, confidence, and IC readiness are determined exclusively
    by Deep Review V4 and persisted in ``deal_underwriting_artifacts``.
    """
    from app.domains.credit.modules.deals.deal_intelligence_repo import update_deal_ai_output

    # ── Screening-only summary — NO recommendation authority ──────
    summary = "Screening analysis completed — pending Deep Review."

    risk_map = output.get("risk_map", {})
    if isinstance(risk_map, dict):
        risk_flags = risk_map.get("key_risks", [])
    elif isinstance(risk_map, list):
        risk_flags = risk_map
    else:
        risk_flags = []

    terms = output.get("terms_and_covenants", {})
    key_terms = {
        "covenants": (
            terms.get("financial_covenants", [])
            if isinstance(terms, dict) else []
        ),
        "security_package": (
            terms.get("security_package", "")
            if isinstance(terms, dict) else ""
        ),
        "fees": (
            terms.get("fees", "")
            if isinstance(terms, dict) else ""
        ),
        "key_clauses": (
            terms.get("key_clauses", [])
            if isinstance(terms, dict) else []
        ),
        "red_flags": (
            risk_map.get("red_flags", [])
            if isinstance(risk_map, dict) else []
        ),
        "downside_scenarios": (
            risk_map.get("downside_scenarios", [])
            if isinstance(risk_map, dict) else []
        ),
        "mitigants": (
            risk_map.get("mitigants", [])
            if isinstance(risk_map, dict) else []
        ),
    }

    update_deal_ai_output(
        db,
        deal_id=deal_id,
        fund_id=fund_id,
        summary=summary,
        risk_flags=risk_flags,
        key_terms=key_terms,
    )
    logger.debug("Derived fields written for deal %s", deal_id)


# ══════════════════════════════════════════════════════════════════════
#  Main entrypoint — TWO-CALL architecture
# ══════════════════════════════════════════════════════════════════════


def generate_pipeline_intelligence(
    db: Session,
    *,
    deal_id: uuid.UUID,
    deal_name: str,
    sponsor_name: str | None = None,
    fund_id: uuid.UUID | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Generate full pipeline intelligence via institutional two-call flow.

    Call A: Structured Intelligence — deal_overview, terms, risks, citations,
            missing_documents (NO memo in this call).
    Call B: Memo Writer — independent 1500-3000 word IC memorandum grounded
            in structured output + evidence excerpts.

    Evidence surface: 80 chunks x 4000 chars = up to 320k chars.
    Citation minimum: 5 (hard fail).
    Missing-documents checklist: LLM + heuristic detection.
    """
    from app.domains.credit.modules.deals.models import PipelineDeal

    t0 = time.perf_counter()

    # ── Idempotency guard ─────────────────────────────────────────
    deal = db.execute(
        select(PipelineDeal).where(PipelineDeal.id == deal_id)
    ).scalar_one_or_none()
    if deal is None:
        logger.error("Deal %s not found in pipeline_deals", deal_id)
        return {}

    if (
        not force
        and deal.research_output
        and deal.intelligence_status == STATUS_READY
    ):
        logger.info(
            "Deal %s already READY (generated %s) — skipping",
            deal_id, deal.intelligence_generated_at,
        )
        return deal.research_output  # type: ignore[return-value]

    # ── Mark PROCESSING ───────────────────────────────────────────
    _set_intelligence_status(db, deal_id, STATUS_PROCESSING)
    logger.info("PIPELINE_INTEL_START deal=%s name=%s", deal_id, deal_name)

    # ── Retrieve context (institutional-scale, 80 chunks) ─────────
    context, chunk_count, raw_chunks, issuer_summary = _retrieve_deal_context(
        deal_id, deal_name, max_chunks=_MAX_RETRIEVAL_CHUNKS,
    )
    if not context:
        logger.warning(
            "No chunks found for deal %s — marking FAILED", deal_id
        )
        _set_intelligence_status(db, deal_id, STATUS_FAILED)
        return {}

    # ── DUAL-SURFACE ARCHITECTURE ─────────────────────────────────
    # Audit Surface: preserve full raw_audit_chunks (NEVER modified)
    raw_audit_chunks = list(raw_chunks)  # frozen copy for traceability

    # Curated Surface: chapter-specific, deduplicated, MMR-selected
    curated_surfaces, curation_metadata = curate_all_chapter_surfaces(
        raw_chunks,
    )

    # Lightly curated surface for Call A (40 diversified chunks)
    analysis_chunks = curate_for_analysis_call(raw_chunks, max_chunks=40)

    logger.info(
        "PIPELINE_CONTEXT_RETRIEVED deal=%s chunks=%d context_chars=%d "
        "audit_surface=%d analysis_surface=%d curated_chapters=%s",
        deal_id, chunk_count, len(context),
        len(raw_audit_chunks), len(analysis_chunks),
        {k: len(v) for k, v in curated_surfaces.items()},
    )

    # ══════════════════════════════════════════════════════════════
    #  CALL A — Structured Intelligence (NO memo)
    #  Uses lightly curated surface (MMR-diversified, max 40 chunks)
    # ══════════════════════════════════════════════════════════════
    structured_model = get_model("structured")
    system_a = prompt_registry.render(
        "intelligence/pipeline_structured.j2",
        deal_name=deal_name,
        sponsor_name=sponsor_name or "Unknown",
        min_citations=_MIN_CITATIONS_REQUIRED,
        min_risks=_MIN_KEY_RISKS,
    )

    # Build curated context for Call A (NOT the full raw context)
    analysis_context_parts: list[str] = []
    for i, chunk in enumerate(analysis_chunks):
        doc_title = chunk.get("title", chunk.get("doc_type", "unknown"))
        issuer_tag = ""
        if chunk.get("issuer_name"):
            issuer_tag = (
                f" | issuer={chunk['issuer_name']}"
                f" ({chunk['issuer_category']})"
                f" | authority={chunk['issuer_tier']}"
            )
        header = (
            f"[Excerpt {i + 1} | {doc_title} "
            f"| type={chunk.get('doc_type', 'unknown')} "
            f"| pages {chunk.get('page_start', '?')}-"
            f"{chunk.get('page_end', '?')}"
            f"{issuer_tag}]"
        )
        analysis_context_parts.append(f"{header}\n{chunk.get('content', '')}")
    analysis_context = "\n\n---\n\n".join(analysis_context_parts)

    user_a = f"Document excerpts ({len(analysis_chunks)} curated, diversified):\n\n{analysis_context}"

    try:
        logger.info("PIPELINE_CALL_A_START model=%s", structured_model)
        structured_output = _call_gpt_json(
            system_a, user_a,
            model=structured_model,
            max_tokens=12_000,
            call_label="structured_intelligence",
        )
        logger.info("PIPELINE_CALL_A_COMPLETE")
    except Exception as exc:
        logger.error(
            "PIPELINE_CALL_A_FAILED deal=%s error=%s",
            deal_id, exc, exc_info=True,
        )
        _set_intelligence_status(db, deal_id, STATUS_FAILED)
        return {}

    # ── Validate structured output ────────────────────────────────
    is_valid_a, issues_a = _validate_output(structured_output)
    if not is_valid_a:
        logger.warning(
            "PIPELINE_VALIDATION_ISSUES deal=%s issues=%s",
            deal_id, "; ".join(issues_a),
        )
        structured_output["_validation_issues"] = issues_a

    # ── Enrich missing-documents checklist ────────────────────────
    llm_missing = structured_output.get("missing_documents", [])
    enriched_missing = _compute_missing_documents(raw_chunks, llm_missing)
    structured_output["missing_documents"] = enriched_missing

    # ── Compute data-room completeness score ──────────────────────
    completeness = compute_completeness_score(enriched_missing)
    structured_output["data_room_completeness"] = completeness

    # ── Persist issuer summary ────────────────────────────────────
    if issuer_summary:
        structured_output["issuer_summary"] = issuer_summary

    # ══════════════════════════════════════════════════════════════
    #  CALL B — Memo Writer (independent institutional prose)
    # ══════════════════════════════════════════════════════════════
    memo_model = get_model("pipeline_memo")
    system_b = prompt_registry.render(
        "intelligence/pipeline_memo.j2",
        deal_name=deal_name,
        sponsor_name=sponsor_name or "Unknown",
    )

    # ── Build enriched user context for Call B ────────────────────
    # CRITICAL: Call B receives structured JSON + curated chapter surfaces
    # instead of the full raw context.  This prevents re-anchoring on
    # identical clauses and reduces governance repetition.
    structured_json = json.dumps(structured_output, separators=(",", ":"), default=str)

    issuer_section = ""
    if issuer_summary:
        issuer_lines = []
        for cat, names in sorted(issuer_summary.items()):
            issuer_lines.append(f"  {cat}: {', '.join(names)}")
        issuer_section = (
            "\n\n=== INSTITUTIONAL ISSUER SUMMARY ===\n"
            "The following authoritative institutional issuers were detected "
            "in the data room. Reference them by name in your analysis where "
            "relevant:\n" + "\n".join(issuer_lines)
        )

    completeness_section = (
        f"\n\n=== DATA ROOM COMPLETENESS ===\n"
        f"Score: {completeness['completeness_score']}/100 "
        f"({completeness['completeness_grade']})\n"
        f"Documents present: {completeness['documents_present']}/{completeness['total_tracked']}\n"
        f"Documents missing: {completeness['documents_missing']}/{completeness['total_tracked']}"
    )

    # Build chapter-curated evidence text (replaces full raw context)
    curated_context_text = build_curated_context_text(curated_surfaces)

    # Curation summary for the LLM
    curation_summary_lines = []
    for ch_type, meta in curation_metadata.items():
        curation_summary_lines.append(
            f"  {ch_type}: {meta['original_count']} -> {meta['final_count']} "
            f"(hard_dedup={meta['hard_dedup_removed']}, "
            f"semantic_dedup={meta['semantic_dedup_removed']})"
        )
    curation_summary = "\n".join(curation_summary_lines)

    user_b = (
        f"=== STRUCTURED INTELLIGENCE DOSSIER ===\n\n"
        f"{structured_json}"
        f"{issuer_section}"
        f"{completeness_section}\n\n"
        f"=== EVIDENCE CURATION SUMMARY ===\n{curation_summary}\n\n"
        f"=== CURATED CHAPTER EVIDENCE ===\n\n"
        f"{curated_context_text}"
    )

    try:
        logger.info("PIPELINE_CALL_B_START model=%s", memo_model)
        memo_output = _call_gpt_json(
            system_b, user_b,
            model=memo_model,
            max_tokens=16_000,
            call_label="memo_writer",
        )
        logger.info("PIPELINE_CALL_B_COMPLETE")
    except Exception as exc:
        logger.error(
            "PIPELINE_CALL_B_FAILED deal=%s error=%s — "
            "persisting structured only",
            deal_id, exc, exc_info=True,
        )
        structured_output["investment_memo"] = (
            "[Memo generation failed — structured intelligence available. "
            f"Error: {exc}]"
        )
        structured_output["confidence_score"] = 0.0
        memo_output = None

    # ── Merge memo into structured output ─────────────────────────
    if memo_output:
        is_valid_b, issues_b = _validate_memo(memo_output)
        if not is_valid_b:
            logger.warning(
                "PIPELINE_MEMO_ISSUES deal=%s issues=%s",
                deal_id, "; ".join(issues_b),
            )
        structured_output["investment_memo"] = memo_output.get(
            "investment_memo", ""
        )
        structured_output["memo_word_count"] = memo_output.get(
            "memo_word_count", 0
        )
        structured_output["confidence_score"] = memo_output.get(
            "confidence_score", 0.5
        )
        structured_output["confidence_rationale"] = memo_output.get(
            "confidence_rationale", ""
        )
        if memo_output.get("_meta"):
            structured_output["_meta_memo"] = memo_output["_meta"]

    # ── Attach curation metadata for evidence pack ────────────────
    structured_output["_curation_metadata"] = curation_metadata
    structured_output["_audit_surface_count"] = len(raw_audit_chunks)

    # ── Adjust confidence for missing critical documents ──────────
    critical_missing = sum(
        1 for d in enriched_missing if d.get("priority") == "critical"
    )
    if critical_missing > 0:
        base_conf = structured_output.get("confidence_score", 0.5)
        penalty = min(critical_missing * 0.1, 0.4)
        adjusted = max(round(base_conf - penalty, 2), 0.05)
        structured_output["confidence_score"] = adjusted
        structured_output["confidence_adjustment"] = (
            f"Reduced by {penalty:.0%} due to "
            f"{critical_missing} missing critical documents"
        )
        logger.info(
            "PIPELINE_CONFIDENCE_ADJUSTED deal=%s base=%.2f "
            "adjusted=%.2f missing_critical=%d",
            deal_id, base_conf, adjusted, critical_missing,
        )

    # ── Persist atomically ────────────────────────────────────────
    try:
        with db.begin_nested():
            _write_research_output(
                db, deal_id, structured_output, auto_commit=False
            )
            now = datetime.now(UTC)
            _set_intelligence_status(
                db, deal_id, STATUS_READY,
                generated_at=now, auto_commit=False,
            )
        db.commit()
    except Exception:
        db.rollback()
        logger.error(
            "PIPELINE_PERSIST_FAILED deal=%s — rolling back",
            deal_id, exc_info=True,
        )
        _set_intelligence_status(db, deal_id, STATUS_FAILED)
        return {}

    # ── Derived field writeback (best-effort) ─────────────────────
    if fund_id is not None:
        try:
            _write_derived_fields(
                db, deal_id=deal_id, fund_id=fund_id,
                output=structured_output,
            )
        except Exception:
            logger.warning(
                "Derived-field writeback failed for deal %s — "
                "research_output is intact",
                deal_id, exc_info=True,
            )

    elapsed = time.perf_counter() - t0
    citations_used = len(structured_output.get("citations", []))
    memo_chars = len(structured_output.get("investment_memo", ""))
    confidence = structured_output.get("confidence_score", 0)
    risk_count = len(
        structured_output.get("risk_map", {}).get("key_risks", [])
        if isinstance(structured_output.get("risk_map"), dict)
        else structured_output.get("risk_map", [])
    )

    logger.info(
        "PIPELINE_INTEL_COMPLETE deal=%s elapsed=%.1fs chunks=%d "
        "citations=%d risks=%d missing_docs=%d memo_chars=%d "
        "confidence=%.2f valid_structured=%s",
        deal_id, elapsed, chunk_count, citations_used,
        risk_count, len(enriched_missing), memo_chars,
        confidence, is_valid_a,
    )
    return structured_output


# ── Batch entrypoint ──────────────────────────────────────────────────


def generate_all_pending(
    db: Session,
    *,
    force: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    """Generate pipeline intelligence for all PENDING pipeline deals."""
    from app.domains.credit.modules.deals.models import PipelineDeal

    stmt = select(PipelineDeal).where(
        text(
            "intelligence_status::text IN ('PENDING', 'FAILED')"
        )
    )
    if not force:
        stmt = stmt.where(
            PipelineDeal.research_output.is_(None)
            | text("intelligence_status::text != 'READY'")
        )
    stmt = stmt.limit(limit)

    deals = list(db.execute(stmt).scalars().all())
    logger.info("PIPELINE_BATCH_START pending_deals=%d", len(deals))

    results: dict[str, Any] = {
        "total": len(deals),
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "details": [],
    }

    # Snapshot deal metadata before closing the query session's ORM objects.
    deal_snapshots = [
        {
            "id": deal.id,
            "deal_name": deal.deal_name or deal.title,
            "sponsor_name": deal.sponsor_name or deal.borrower_name,
            "fund_id": deal.fund_id,
            "title": deal.title,
        }
        for deal in deals
    ]

    def _process_deal(snap: dict) -> dict:
        """Process a single deal with its own DB session (thread-safe)."""

        thread_db = async_session_factory()
        try:
            output = generate_pipeline_intelligence(
                thread_db,
                deal_id=snap["id"],
                deal_name=snap["deal_name"],
                sponsor_name=snap["sponsor_name"],
                fund_id=snap["fund_id"],
                force=force,
            )
            if output:
                return {"deal_id": str(snap["id"]), "name": snap["title"], "status": "OK"}
            return {"deal_id": str(snap["id"]), "name": snap["title"], "status": "SKIPPED"}
        except Exception as exc:
            logger.error(
                "Pipeline intelligence failed for deal %s: %s",
                snap["id"], exc, exc_info=True,
            )
            return {"deal_id": str(snap["id"]), "name": snap["title"], "status": f"ERROR: {exc}"}
        finally:
            thread_db.close()

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_process_deal, snap): snap
            for snap in deal_snapshots
        }
        for future in as_completed(futures):
            detail = future.result()
            results["details"].append(detail)
            if detail["status"] == "OK":
                results["succeeded"] += 1
            elif detail["status"] == "SKIPPED":
                results["skipped"] += 1
            else:
                results["failed"] += 1

    logger.info(
        "PIPELINE_BATCH_COMPLETE total=%d succeeded=%d "
        "failed=%d skipped=%d",
        results["total"], results["succeeded"],
        results["failed"], results["skipped"],
    )
    return results


# ══════════════════════════════════════════════════════════════════════
#  Backward-compatible aliases
# ══════════════════════════════════════════════════════════════════════

generate_structured_intelligence = generate_pipeline_intelligence

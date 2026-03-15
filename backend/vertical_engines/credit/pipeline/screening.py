"""Context retrieval, missing-document detection, and completeness scoring.

Implements _retrieve_deal_context(), _compute_missing_documents(), and
compute_completeness_score().
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog

from ai_engine.extraction.embedding_service import generate_embeddings
from ai_engine.extraction.search_upsert_service import search_deal_chunks
from ai_engine.governance.authority_resolver import enrich_chunks_with_authority
from vertical_engines.credit.pipeline.models import (
    MAX_CHARS_PER_CHUNK,
    MAX_RETRIEVAL_CHUNKS,
    REQUIRED_DD_DOCUMENTS,
    TOTAL_DD_WEIGHT,
)

logger = structlog.get_logger()


def _retrieve_deal_context(
    deal_id: uuid.UUID,
    deal_name: str,
    *,
    max_chunks: int = MAX_RETRIEVAL_CHUNKS,
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
        logger.warning("embedding_generation_failed", fallback="BM25 only")
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
            "search_retrieval_failed",
            deal_id=str(deal_id),
            exc_info=True,
        )
        return "", 0, [], {}

    if not chunks:
        return "", 0, [], {}

    # ── Institutional evidence surface — NO destructive throttling ─────
    trimmed_chunks: list[dict] = []
    total_chars = 0
    for chunk in chunks[:max_chunks]:
        c = dict(chunk)
        content = c.get("content", "")
        c["content"] = content[:MAX_CHARS_PER_CHUNK]
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
            "pipeline_issuer_detection",
            deal_id=str(deal_id),
            issuers=issuer_summary,
        )

    logger.info(
        "pipeline_evidence_surface",
        chunks=len(enriched_chunks),
        total_chars=total_chars,
        avg_chars=total_chars // max(len(enriched_chunks), 1),
    )

    return context_text, len(enriched_chunks), enriched_chunks, issuer_summary


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

    for std_doc in REQUIRED_DD_DOCUMENTS:
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

    for doc in REQUIRED_DD_DOCUMENTS:
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

    score = round((((TOTAL_DD_WEIGHT - missing_weight) / TOTAL_DD_WEIGHT) * 100), 1)
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
        "total_tracked": len(REQUIRED_DD_DOCUMENTS),
        "breakdown": breakdown,
    }

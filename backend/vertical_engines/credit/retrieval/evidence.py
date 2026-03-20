"""Per-chapter evidence retrieval and provenance validation.

Implements gather_chapter_evidence() (the per-chapter retrieval pipeline)
and validate_provenance() (chunk integrity gate).

Error contract: never-raises. Returns result dict with warnings on failure.
"""
from __future__ import annotations

import uuid
from typing import Any

import structlog

from ai_engine.extraction.retrieval_signal import RetrievalSignal
from app.core.config import settings
from vertical_engines.credit.retrieval.models import (
    CHAPTER_EVIDENCE_THRESHOLDS,
    CHAPTER_RETRIEVAL_MODE,
    COVERAGE_CONTESTED,
    COVERAGE_MISSING,
    COVERAGE_PARTIAL,
    COVERAGE_SATURATED,
    DEFAULT_SEARCH_TIER,
    DESIRED_PROVENANCE_FIELDS,
    EXPANDED_SEARCH_TIER,
    REQUIRED_PROVENANCE_FIELDS,
    ChapterEvidenceThreshold,
)
from vertical_engines.credit.retrieval.query_map import build_chapter_query_map

logger = structlog.get_logger()


def _shared_auxiliary_fund_ids() -> set[str]:
    """Return configured shared auxiliary scope ids allowed across deals.

    These are global/shared evidence domains such as fund constitution,
    regulatory libraries, and service-provider materials. They are not
    deal-specific and must survive the last-line contamination filter.
    """
    raw = getattr(settings, "SEARCH_AUXILIARY_INDEXES", None) or ""
    allowed: set[str] = set()
    for entry in raw.split(","):
        parts = [part.strip() for part in entry.split(":")]
        if len(parts) >= 2 and parts[1]:
            allowed.add(parts[1].lower())
    return allowed


def validate_provenance(chunk: dict) -> bool:
    """Validate that a chunk has sufficient provenance for IC-grade use.

    Hard requirement: blob_name, content, chunk_index must be present.
    Soft requirement: doc_type, authority, page_start, page_end,
        container_name are expected but not fatal if absent.

    Returns True if chunk passes, False if it should be discarded.
    """
    for f in REQUIRED_PROVENANCE_FIELDS:
        val = chunk.get(f)
        if val is None or (isinstance(val, str) and not val.strip()):
            logger.warning(
                "provenance_rejected",
                chunk_id=chunk.get("chunk_id", "?"),
                missing_field=f,
            )
            return False

    missing_soft = [f for f in DESIRED_PROVENANCE_FIELDS if not chunk.get(f)]
    if missing_soft:
        logger.debug(
            "provenance_soft_missing",
            chunk_id=chunk.get("chunk_id", "?"),
            fields=missing_soft,
        )

    return True


def gather_chapter_evidence(
    *,
    chapter_key: str,
    deal_name: str,
    fund_id: str,
    deal_id: str | None = None,
    organization_id: str | None = None,
) -> dict[str, Any]:
    """Retrieve evidence for a single chapter using specialized queries.

    Fires all queries in the CHAPTER_QUERY_MAP for this chapter,
    deduplicates by (blob_name, chunk_index), validates provenance,
    and returns the chapter's evidence corpus.

    Error contract: never-raises. Returns result dict with empty chunks
    and warnings list on failure.

    Parameters
    ----------
    chapter_key : str
        e.g. "ch01_exec", "ch08_returns"
    deal_name : str
        Deal name for query anchoring.
    fund_id : str
        Mandatory fund scope.
    deal_id : str
        Deal ID for scoping (UUID string).
    organization_id : str
        Organization ID for tenant isolation (mandatory for pgvector).

    Returns
    -------
    dict with keys:
        "chunks"          — deduplicated, provenance-validated chunks
        "queries"         — list of queries fired
        "coverage_status" — SATURATED | PARTIAL | MISSING_EVIDENCE
        "retrieval_mode"  — PIPELINE_SCREENING | LEGAL_PACK | UNDERWRITING | IC_GRADE
        "doc_type_filter" — None (pgvector doesn't use OData filters)
        "stats"           — {chunk_count, unique_docs, doc_types}

    """
    from ai_engine.extraction.embedding_service import generate_embeddings
    from ai_engine.extraction.pgvector_search_service import search_and_rerank_deal_sync

    query_map = build_chapter_query_map(deal_name)
    queries   = query_map.get(chapter_key, [])

    if not queries:
        return {
            "chunks":          [],
            "queries":         [],
            "coverage_status": COVERAGE_MISSING,
            "retrieval_mode":  CHAPTER_RETRIEVAL_MODE.get(chapter_key, "IC_GRADE"),
            "doc_type_filter": None,
            "stats":           {"chunk_count": 0, "unique_docs": 0, "doc_types": []},
        }

    retrieval_mode = CHAPTER_RETRIEVAL_MODE.get(chapter_key, "IC_GRADE")

    # ── Batch-embed all chapter queries in one API call ───────────
    try:
        emb_result = generate_embeddings(queries)
        query_vectors = emb_result.vectors
    except Exception:
        logger.warning(
            "chapter_embedding_failed",
            chapter=chapter_key,
            exc_info=True,
        )
        query_vectors = [None] * len(queries)

    # Chapter-local pool only — global dedup is done in build_ic_corpus.
    chapter_hits: dict[str, dict] = {}

    _tier_top, _tier_k = DEFAULT_SEARCH_TIER

    per_query_counts: list[int] = [0] * len(queries)

    # Parse deal_id as UUID for pgvector
    deal_uuid: uuid.UUID | None = None
    if deal_id:
        try:
            deal_uuid = uuid.UUID(deal_id)
        except (ValueError, AttributeError):
            logger.warning("invalid_deal_id_uuid", deal_id=deal_id)

    def _execute_query(
        q_idx: int,
        query: str,
        tier_top: int = _tier_top,
        tier_k: int = _tier_k,
    ) -> tuple[int, list[dict]]:
        """Execute a single search query — thread-safe (no shared mutable state)."""
        hits_data: list[dict] = []
        if deal_uuid is None or not organization_id:
            return q_idx, hits_data
        try:
            q_vector = query_vectors[q_idx] if q_idx < len(query_vectors) else None
            result = search_and_rerank_deal_sync(
                deal_id=deal_uuid,
                organization_id=organization_id,
                query_text=query,
                query_vector=q_vector,
                top=tier_top,
                candidates=tier_k,
            )
            for chunk in result.chunks:
                title      = chunk.get("title", "")
                chunk_idx  = chunk.get("chunk_index", 0) or 0
                score      = chunk.get("score", 0.0)
                reranker_score = chunk.get("reranker_score", score)
                hits_data.append({
                    "chunk_id":            chunk.get("id", ""),
                    "title":               title,
                    "blob_name":           title,
                    "doc_type":            chunk.get("doc_type", "unknown"),
                    "authority":           "",
                    "page_start":          chunk.get("page_start", 0) or 0,
                    "page_end":            chunk.get("page_end", 0) or 0,
                    "chunk_index":         chunk_idx,
                    "content":             chunk.get("content", ""),
                    "score":               score,
                    "reranker_score":      reranker_score,
                    "_best_score":         reranker_score or score,
                    "_query_origin":       query[:80],
                    "_chapter_key":        chapter_key,
                    "_retrieval_mode":     retrieval_mode,
                    "container_name":      "",
                    "retrieval_timestamp": "",
                    "fund_id":             chunk.get("fund_id", ""),
                    "deal_id":             chunk.get("deal_id", ""),
                    "section_type":        chunk.get("section_type"),
                    "vehicle_type":        None,
                    "governance_critical": chunk.get("governance_critical", False),
                    "governance_flags":    [],
                    "breadcrumb":          chunk.get("breadcrumb"),
                })
            logger.info(
                "chapter_retrieval",
                chapter=chapter_key,
                mode=retrieval_mode,
                query_idx=q_idx + 1,
                query_total=len(queries),
                query=query[:60],
                hits=len(result.chunks),
            )
        except Exception:
            logger.warning(
                "chapter_retrieval_failed",
                chapter=chapter_key,
                query_idx=q_idx,
                query=query[:60],
                exc_info=True,
            )
        return q_idx, hits_data

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(_execute_query, q_idx, query)
            for q_idx, query in enumerate(queries)
        ]
        for future in futures:
            q_idx, hits_data = future.result()
            query_hit_count = 0
            for chunk_data in hits_data:
                dedup_key = f"{chunk_data['title']}::{chunk_data['chunk_index']}"
                new_score = chunk_data["_best_score"]
                existing_local = chapter_hits.get(dedup_key)
                if (existing_local is None
                        or new_score > existing_local.get("_best_score", 0.0)):
                    chapter_hits[dedup_key] = chunk_data
                    query_hit_count += 1
            per_query_counts[q_idx] = query_hit_count

    # Provenance validation
    valid_chunks = [
        c for c in chapter_hits.values()
        if validate_provenance(c)
    ]

    # ── Cross-deal contamination detection ──────────────────────────
    if deal_name:
        clean_chunks: list[dict] = []
        contaminated_count = 0
        shared_aux_ids = _shared_auxiliary_fund_ids()
        for c in valid_chunks:
            chunk_deal = c.get("deal_id", "")
            chunk_fund = str(c.get("fund_id", "") or "").lower()
            if (
                not chunk_deal
                or chunk_deal.lower() == deal_name.lower()
                or chunk_fund in shared_aux_ids
            ):
                clean_chunks.append(c)
            else:
                contaminated_count += 1
                logger.error(
                    "cross_deal_contamination_blocked",
                    chapter=chapter_key,
                    deal=deal_name,
                    chunk_deal_id=chunk_deal,
                    chunk_id=c.get("chunk_id", "?"),
                    blob=c.get("blob_name", "?"),
                    fund_id=c.get("fund_id", "?"),
                )
        if contaminated_count > 0:
            logger.critical(
                "contamination_summary",
                chapter=chapter_key,
                deal=deal_name,
                blocked=contaminated_count,
                kept=len(clean_chunks),
            )
        valid_chunks = clean_chunks

    # Coverage stats
    unique_docs = len({c["blob_name"] for c in valid_chunks})
    doc_types   = list({c.get("doc_type", "unknown") for c in valid_chunks})
    chunk_count = len(valid_chunks)
    fallback_count = sum(1 for c in valid_chunks if c.get("_fallback"))

    threshold = CHAPTER_EVIDENCE_THRESHOLDS.get(
        chapter_key,
        ChapterEvidenceThreshold(min_chunks=4, min_docs=2),
    )

    if threshold.is_satisfied(chunk_count, unique_docs, set(doc_types)):
        coverage_status = COVERAGE_SATURATED
    elif chunk_count > 0:
        coverage_status = COVERAGE_PARTIAL
    else:
        coverage_status = COVERAGE_MISSING

    # Compute retrieval confidence signal from chapter results
    retrieval_signal = RetrievalSignal.from_results(
        valid_chunks,
        score_key="reranker_score",
    )

    # ── Signal-based search expansion ────────────────────────────────
    search_expanded = False
    if (
        retrieval_signal.confidence in ("LOW", "AMBIGUOUS")
        and coverage_status != COVERAGE_MISSING
    ):
        logger.info(
            "search_tier_expanded",
            chapter=chapter_key,
            confidence=retrieval_signal.confidence,
        )
        _exp_top, _exp_k = EXPANDED_SEARCH_TIER
        with ThreadPoolExecutor(max_workers=4) as executor:
            exp_futures = [
                executor.submit(_execute_query, q_idx, query, _exp_top, _exp_k)
                for q_idx, query in enumerate(queries)
            ]
            for future in exp_futures:
                _, exp_hits = future.result()
                for chunk_data in exp_hits:
                    dedup_key = f"{chunk_data['title']}::{chunk_data['chunk_index']}"
                    new_score = chunk_data["_best_score"]
                    existing = chapter_hits.get(dedup_key)
                    if (existing is None
                            or new_score > existing.get("_best_score", 0.0)):
                        chapter_hits[dedup_key] = chunk_data

        # Re-validate provenance on expanded results
        valid_chunks = [
            c for c in chapter_hits.values()
            if validate_provenance(c)
        ]

        # Re-apply cross-deal contamination filter
        if deal_name:
            clean_chunks = []
            for c in valid_chunks:
                chunk_deal = c.get("deal_id", "")
                chunk_fund = str(c.get("fund_id", "") or "").lower()
                if (
                    not chunk_deal
                    or chunk_deal.lower() == deal_name.lower()
                    or chunk_fund in shared_aux_ids
                ):
                    clean_chunks.append(c)
            valid_chunks = clean_chunks

        # Recompute coverage stats
        unique_docs = len({c["blob_name"] for c in valid_chunks})
        doc_types = list({c.get("doc_type", "unknown") for c in valid_chunks})
        chunk_count = len(valid_chunks)
        fallback_count = sum(1 for c in valid_chunks if c.get("_fallback"))

        if threshold.is_satisfied(chunk_count, unique_docs, set(doc_types)):
            coverage_status = COVERAGE_SATURATED
        elif chunk_count > 0:
            coverage_status = COVERAGE_PARTIAL
        else:
            coverage_status = COVERAGE_MISSING

        # Recompute signal on expanded results
        retrieval_signal = RetrievalSignal.from_results(
            valid_chunks,
            score_key="reranker_score",
        )
        search_expanded = True

    # Override to EVIDENCE_CONTESTED when signal is AMBIGUOUS
    if retrieval_signal.confidence == "AMBIGUOUS" and coverage_status != COVERAGE_MISSING:
        coverage_status = COVERAGE_CONTESTED
        logger.warning(
            "evidence_contested",
            chapter=chapter_key,
            signal_confidence=retrieval_signal.confidence,
            delta=retrieval_signal.delta_top1_top2,
        )

    return {
        "chunks":          valid_chunks,
        "queries":         queries,
        "coverage_status": coverage_status,
        "retrieval_mode":  retrieval_mode,
        "doc_type_filter": None,
        "search_expanded": search_expanded,
        "retrieval_signal": {
            "confidence":      retrieval_signal.confidence,
            "top1_score":      retrieval_signal.top1_score,
            "delta_top1_top2": retrieval_signal.delta_top1_top2,
            "result_count":    retrieval_signal.result_count,
        },
        "stats": {
            "chunk_count":    chunk_count,
            "unique_docs":    unique_docs,
            "doc_types":      doc_types,
            "fallback_count": fallback_count,
        },
    }

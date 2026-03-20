"""Per-chapter evidence retrieval and provenance validation.

Implements gather_chapter_evidence() (the per-chapter retrieval pipeline)
and validate_provenance() (chunk integrity gate).

Error contract: never-raises. Returns result dict with warnings on failure.
"""
from __future__ import annotations

from typing import Any

import structlog

from ai_engine.extraction.retrieval_signal import RetrievalSignal
from app.core.config import settings
from vertical_engines.credit.retrieval.models import (
    CHAPTER_DOC_TYPE_FILTERS,
    CHAPTER_EVIDENCE_THRESHOLDS,
    CHAPTER_RETRIEVAL_MODE,
    CHAPTER_SEARCH_TIERS,
    COVERAGE_MISSING,
    COVERAGE_PARTIAL,
    COVERAGE_SATURATED,
    DEFAULT_SEARCH_TIER,
    DESIRED_PROVENANCE_FIELDS,
    FILTER_FALLBACK_THRESHOLD,
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
    searcher: Any,  # AzureSearchChunksClient
    global_dedup: dict[str, dict] | None = None,  # kept for API compat, no longer used
    doc_type_filter: str | None = None,
    override_filter: bool = False,
    scope_mode: str = "STRICT",
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
        Deal ID for scoping.
    searcher : AzureSearchChunksClient
        Configured retrieval client.
    global_dedup : dict, optional
        Shared dedup dict across chapters (kept for API compat).
    doc_type_filter : str | None, optional
        OData filter expression for doc_type scoping.
    override_filter : bool
        If True, use caller-provided doc_type_filter instead of map default.
    scope_mode : str
        Scope mode for search (STRICT or RELAXED).

    Returns
    -------
    dict with keys:
        "chunks"          — deduplicated, provenance-validated chunks
        "queries"         — list of queries fired
        "coverage_status" — SATURATED | PARTIAL | MISSING_EVIDENCE
        "retrieval_mode"  — PIPELINE_SCREENING | LEGAL_PACK | UNDERWRITING | IC_GRADE
        "doc_type_filter" — the OData filter string used (or None)
        "stats"           — {chunk_count, unique_docs, doc_types}

    """
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

    # Resolve doc_type_filter — use map default unless override_filter=True
    if not override_filter:
        active_filter = CHAPTER_DOC_TYPE_FILTERS.get(chapter_key)
    else:
        active_filter = doc_type_filter

    retrieval_mode = CHAPTER_RETRIEVAL_MODE.get(chapter_key, "IC_GRADE")

    # Chapter-local pool only — global dedup is done in build_ic_corpus.
    chapter_hits: dict[str, dict] = {}

    _tier_top, _tier_k = CHAPTER_SEARCH_TIERS.get(chapter_key, DEFAULT_SEARCH_TIER)

    per_query_counts: list[int] = [0] * len(queries)

    def _execute_query(q_idx: int, query: str) -> tuple[int, list[dict]]:
        """Execute a single search query — thread-safe (no shared mutable state)."""
        hits_data: list[dict] = []
        try:
            hits = searcher.search_institutional_hybrid(
                query=query,
                fund_id=fund_id,
                deal_id=deal_id,
                top=_tier_top,
                k=_tier_k,
                doc_type_filter=active_filter,
                scope_mode=scope_mode,
            )
            for hit in hits:
                title      = hit.title or hit.blob_name or ""
                chunk_idx  = hit.chunk_index or 0
                new_score  = hit.reranker_score or hit.score or 0.0
                hits_data.append({
                    "chunk_id":            hit.chunk_id,
                    "title":               title,
                    "blob_name":           hit.blob_name or title,
                    "doc_type":            hit.doc_type or "unknown",
                    "authority":           hit.authority or "",
                    "page_start":          hit.page_start or 0,
                    "page_end":            hit.page_end or 0,
                    "chunk_index":         chunk_idx,
                    "content":             hit.content_text or "",
                    "score":               hit.score or 0.0,
                    "reranker_score":      hit.reranker_score or 0.0,
                    "_best_score":         new_score,
                    "_query_origin":       query[:80],
                    "_chapter_key":        chapter_key,
                    "_retrieval_mode":     retrieval_mode,
                    "container_name":      hit.container_name or "",
                    "retrieval_timestamp": hit.retrieval_timestamp or "",
                    "fund_id":             hit.fund_id or "",
                    "deal_id":             hit.deal_id or "",
                    "section_type":        getattr(hit, "section_type", None),
                    "vehicle_type":        getattr(hit, "vehicle_type", None),
                    "governance_critical": getattr(hit, "governance_critical", False),
                    "governance_flags":    getattr(hit, "governance_flags", []) or [],
                    "breadcrumb":          getattr(hit, "breadcrumb", None),
                })
            logger.info(
                "chapter_retrieval",
                chapter=chapter_key,
                mode=retrieval_mode,
                query_idx=q_idx + 1,
                query_total=len(queries),
                query=query[:60],
                hits=len(hits),
                filter=f"'{active_filter[:60]}'" if active_filter else "NONE",
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

    # ── Automatic filter broadening (v3.1 — smart per-query fallback) ──
    _QUERY_FALLBACK_MIN = 3
    if active_filter is not None and len(valid_chunks) < FILTER_FALLBACK_THRESHOLD:
        queries_to_retry = [
            i for i, cnt in enumerate(per_query_counts)
            if cnt < _QUERY_FALLBACK_MIN
        ]
        logger.warning(
            "filter_fallback_triggered",
            chapter=chapter_key,
            filtered_chunks=len(valid_chunks),
            threshold=FILTER_FALLBACK_THRESHOLD,
            retrying_queries=len(queries_to_retry),
            total_queries=len(queries),
        )
        for q_idx in queries_to_retry:
            query = queries[q_idx]
            try:
                fallback_hits = searcher.search_institutional_hybrid(
                    query=query,
                    fund_id=fund_id,
                    deal_id=deal_id,
                    top=_tier_top,
                    k=_tier_k,
                    doc_type_filter=None,  # IC_GRADE — no filter
                    scope_mode=scope_mode,
                )
                for hit in fallback_hits:
                    title     = hit.title or hit.blob_name or ""
                    chunk_idx = hit.chunk_index or 0
                    dedup_key = f"{title}::{chunk_idx}"
                    new_score = hit.reranker_score or hit.score or 0.0
                    if dedup_key not in chapter_hits:
                        chapter_hits[dedup_key] = {
                            "chunk_id":            hit.chunk_id,
                            "title":               title,
                            "blob_name":           hit.blob_name or title,
                            "doc_type":            hit.doc_type or "unknown",
                            "authority":           hit.authority or "",
                            "page_start":          hit.page_start or 0,
                            "page_end":            hit.page_end or 0,
                            "chunk_index":         chunk_idx,
                            "content":             hit.content_text or "",
                            "score":               hit.score or 0.0,
                            "reranker_score":      hit.reranker_score or 0.0,
                            "_best_score":         new_score,
                            "_query_origin":       query[:80],
                            "_chapter_key":        chapter_key,
                            "_retrieval_mode":     "IC_GRADE_FALLBACK",
                            "_fallback":           True,
                            "container_name":      hit.container_name or "",
                            "retrieval_timestamp": hit.retrieval_timestamp or "",
                            "fund_id":             hit.fund_id or "",
                            "deal_id":             hit.deal_id or "",
                            "section_type":        getattr(hit, "section_type", None),
                            "vehicle_type":        getattr(hit, "vehicle_type", None),
                            "governance_critical": getattr(hit, "governance_critical", False),
                            "governance_flags":    getattr(hit, "governance_flags", []) or [],
                            "breadcrumb":          getattr(hit, "breadcrumb", None),
                        }
            except Exception:
                logger.warning(
                    "filter_fallback_failed",
                    chapter=chapter_key,
                    query_idx=q_idx,
                    exc_info=True,
                )

        # Re-validate with fallback chunks merged in
        valid_chunks = [
            c for c in chapter_hits.values()
            if validate_provenance(c)
        ]
        logger.info(
            "filter_fallback_result",
            chapter=chapter_key,
            chunks_after_fallback=len(valid_chunks),
        )

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
        "doc_type_filter": active_filter,
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

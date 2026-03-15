"""IC-Grade corpus assembly and coverage-aware reranking.

Implements build_ic_corpus() (merges per-chapter evidence into a single
IC-grade corpus) and ic_coverage_rerank() (coverage-governed reranking).

Error contract: never-raises. Returns result dict with warnings on failure.
"""
from __future__ import annotations

from collections import Counter
from math import sqrt
from typing import Any

import structlog

from vertical_engines.credit.retrieval.models import (
    COVERAGE_MISSING,
    CRITICAL_DOC_TYPES,
    DEPTH_FREE,
    LAMBDA,
    RETRIEVAL_POLICY_NAME,
    TOTAL_BUDGET_CHARS,
)

logger = structlog.get_logger()


def ic_coverage_rerank(chunks: list[dict]) -> list[dict]:
    """Apply IC-Grade coverage-aware reranking.

    Policy (from underwriting-standard.md Stage 5):
        - First DEPTH_FREE chunks from any document: bonus = 0
          (pure semantic ordering preserved).
        - After DEPTH_FREE: bonus = LAMBDA / sqrt(freq - DEPTH_FREE + 1)
          (marginal correction for diversity, not dominance).

    The semantic_score (reranker_score) remains the PRIMARY authority.
    Coverage bonus is a small corrective additive term.
    """
    if not chunks:
        return chunks

    doc_counter = Counter(
        c.get("blob_name", c.get("title", "unknown")) for c in chunks
    )

    for chunk in chunks:
        blob = chunk.get("blob_name", chunk.get("title", "unknown"))
        freq = doc_counter.get(blob, 1)

        if freq <= DEPTH_FREE:
            coverage_bonus = 0.0
        else:
            coverage_bonus = LAMBDA / sqrt(freq - DEPTH_FREE + 1)

        semantic = chunk.get("reranker_score") or chunk.get("score") or 0.0
        chunk["_coverage_bonus"]  = round(coverage_bonus, 6)
        chunk["_semantic_score"]  = round(semantic, 6)
        chunk["_final_score"]     = round(semantic + coverage_bonus, 6)

    chunks.sort(key=lambda c: c.get("_final_score", 0.0), reverse=True)
    return chunks


def build_ic_corpus(
    chapter_evidence: dict[str, dict],
) -> dict[str, Any]:
    """Build IC-grade corpus from per-chapter evidence.

    Merges all chapter chunks, applies IC-grade coverage reranking,
    and assembles the final corpus with provenance headers.
    """
    all_chunks:    dict[str, dict] = {}
    chapter_stats: dict[str, dict] = {}

    for ch_key, ch_data in chapter_evidence.items():
        chapter_stats[ch_key] = {
            "queries":         ch_data.get("queries", []),
            "coverage_status": ch_data.get("coverage_status", COVERAGE_MISSING),
            "retrieval_mode":  ch_data.get("retrieval_mode", "IC_GRADE"),
            "doc_type_filter": ch_data.get("doc_type_filter"),
            "stats":           ch_data.get("stats", {}),
        }

        for chunk in ch_data.get("chunks", []):
            blob      = chunk.get("blob_name", chunk.get("title", ""))
            chunk_idx = chunk.get("chunk_index", 0)
            dedup_key = f"{blob}::{chunk_idx}"
            existing  = all_chunks.get(dedup_key)
            new_score = chunk.get("_best_score", 0.0)
            if existing is None or new_score > existing.get("_best_score", 0.0):
                all_chunks[dedup_key] = chunk

    merged = list(all_chunks.values())
    ranked = ic_coverage_rerank(merged)

    # ── Critical document type forced inclusion ───────────────────
    critical:  list[dict] = []
    standard:  list[dict] = []
    for chunk in ranked:
        dt = (chunk.get("doc_type") or "").lower()
        if dt in CRITICAL_DOC_TYPES:
            critical.append(chunk)
        else:
            standard.append(chunk)

    if critical:
        logger.info(
            "ic_corpus_critical_docs",
            forced=len(critical),
            doc_types=list({c.get("doc_type", "?") for c in critical}),
        )

    # Process critical chunks first, then standard
    ordered = critical + standard

    max_chars = TOTAL_BUDGET_CHARS
    consumed  = 0
    parts:         list[str]  = []
    evidence_map:  list[dict] = []
    raw_chunks:    list[dict] = []

    for chunk in ordered:
        content = chunk.get("content", "")
        if not content:
            continue
        remaining = max_chars - consumed
        if remaining <= 0:
            break
        snippet = content[:remaining]

        blob_name = chunk.get("blob_name", chunk.get("title", ""))
        chunk_id  = chunk.get(
            "chunk_id",
            chunk.get("id", f"{blob_name}::p{chunk.get('page_start', 0)}"),
        )

        header = (
            f"--- [{blob_name}] "
            f"pages {chunk.get('page_start', '?')}-{chunk.get('page_end', '?')} "
            f"| mode={chunk.get('_retrieval_mode', '?')} "
            f"semantic={chunk.get('_semantic_score', 0):.3f} "
            f"cvg_bonus={chunk.get('_coverage_bonus', 0):.3f} "
            f"final={chunk.get('_final_score', 0):.3f} ---"
        )
        parts.append(f"{header}\n{snippet}")
        consumed += len(snippet) + len(header) + 1

        evidence_map.append({
            "blob_name":           blob_name,
            "chunk_index":         chunk.get("chunk_index", 0),
            "page_start":          chunk.get("page_start", 0),
            "page_end":            chunk.get("page_end", 0),
            "doc_type":            chunk.get("doc_type", "unknown"),
            "authority":           chunk.get("authority", ""),
            "container_name":      chunk.get("container_name", ""),
            "chunk_id":            chunk_id,
            "query_origin":        chunk.get("_query_origin", ""),
            "chapter_key":         chunk.get("_chapter_key", ""),
            "retrieval_mode":      chunk.get("_retrieval_mode", ""),
            "retrieval_timestamp": chunk.get("retrieval_timestamp", ""),
        })

        raw_chunks.append({
            "chunk_id":       chunk_id,
            "blob_name":      blob_name,
            "doc_type":       chunk.get("doc_type", "unknown"),
            "authority":      chunk.get("authority", ""),
            "page_start":     chunk.get("page_start", 0),
            "page_end":       chunk.get("page_end", 0),
            "content":        snippet,
            "semantic_score": chunk.get("_semantic_score", 0),
            "coverage_bonus": chunk.get("_coverage_bonus", 0),
            "final_score":    chunk.get("_final_score", 0),
            "query_origin":   chunk.get("_query_origin", ""),
            "chapter_key":    chunk.get("_chapter_key", ""),
            "retrieval_mode": chunk.get("_retrieval_mode", ""),
        })

    corpus = "\n\n".join(parts)

    # Word-count overflow guard
    word_count = len(corpus.split())
    max_words  = max_chars // 5
    if word_count > max_words:
        words  = corpus.split()
        corpus = " ".join(words[:max_words])
        logger.warning(
            "ic_corpus_truncated",
            original_words=word_count,
            truncated_to=max_words,
        )

    unique_docs = len({c["blob_name"] for c in raw_chunks})

    global_stats = {
        "unique_docs":      unique_docs,
        "total_chunks":     len(raw_chunks),
        "corpus_chars":     len(corpus),
        "retrieval_policy": RETRIEVAL_POLICY_NAME,
    }

    logger.info(
        "ic_corpus_built",
        chunks=len(raw_chunks),
        unique_docs=unique_docs,
        corpus_chars=len(corpus),
        policy=RETRIEVAL_POLICY_NAME,
    )

    return {
        "corpus_text":   corpus,
        "evidence_map":  evidence_map,
        "raw_chunks":    raw_chunks,
        "chapter_stats": chapter_stats,
        "global_stats":  global_stats,
    }

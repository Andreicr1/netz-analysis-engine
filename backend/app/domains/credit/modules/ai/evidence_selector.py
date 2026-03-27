"""Evidence selection and chunk curation for IC memo generation.

Curates raw retrieval chunks into chapter-specific surfaces for
dual-surface architecture: audit surface (full) + analysis surface (filtered).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def curate_all_chapter_surfaces(
    raw_chunks: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]]]:
    """Curate raw chunks into per-chapter surfaces with metadata.

    Returns:
        (curated_surfaces, curation_metadata)
        - curated_surfaces: {chapter_type: [chunks]}
        - curation_metadata: {chapter_type: {original_count, final_count, ...}}

    """
    if not raw_chunks:
        return {}, {}

    # Group by doc_type as a simple chapter proxy
    by_type: dict[str, list[dict[str, Any]]] = {}
    for chunk in raw_chunks:
        doc_type = chunk.get("doc_type", "unknown")
        by_type.setdefault(doc_type, []).append(chunk)

    surfaces: dict[str, list[dict[str, Any]]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    for chapter_type, chunks in by_type.items():
        surfaces[chapter_type] = chunks
        metadata[chapter_type] = {
            "original_count": len(chunks),
            "final_count": len(chunks),
        }

    return surfaces, metadata


def curate_for_analysis_call(
    raw_chunks: list[dict[str, Any]],
    max_chunks: int = 40,
) -> list[dict[str, Any]]:
    """Select top chunks for LLM analysis call (token-budget aware).

    Sorts by relevance score descending, truncates to max_chunks.
    """
    if not raw_chunks:
        return []

    sorted_chunks = sorted(
        raw_chunks,
        key=lambda c: float(c.get("score", c.get("relevance_score", 0))),
        reverse=True,
    )
    return sorted_chunks[:max_chunks]


def build_curated_context_text(
    curated_surfaces: dict[str, list[dict[str, Any]]],
) -> str:
    """Flatten curated chapter surfaces into a single text block for prompts."""
    if not curated_surfaces:
        return ""

    sections: list[str] = []
    for chapter_type, chunks in curated_surfaces.items():
        header = f"=== {chapter_type.upper()} ==="
        body = "\n\n".join(
            chunk.get("content", chunk.get("text", ""))
            for chunk in chunks
            if chunk.get("content") or chunk.get("text")
        )
        if body:
            sections.append(f"{header}\n{body}")

    return "\n\n".join(sections)


def curate_chunks_by_chapter(
    chunks: list[dict[str, Any]],
    chapter: str,
    max_chunks: int = 12,
    max_chars_per_chunk: int = 2000,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Curate chunks for a specific chapter with size limits.

    Returns:
        (curated_chunks, curation_metadata)

    """
    if not chunks:
        return [], {"original_count": 0, "final_count": 0, "chapter": chapter}

    # Truncate content per chunk
    curated: list[dict[str, Any]] = []
    for chunk in chunks[:max_chunks]:
        c = dict(chunk)
        content = c.get("content", c.get("text", ""))
        if len(content) > max_chars_per_chunk:
            c["content"] = content[:max_chars_per_chunk]
        curated.append(c)

    metadata = {
        "original_count": len(chunks),
        "final_count": len(curated),
        "chapter": chapter,
        "truncated": len(chunks) > max_chunks,
    }
    return curated, metadata


def deduplicate_governance_red_flags(
    flags: list[dict[str, Any]],
    similarity_threshold: float = 0.80,
    max_flags: int = 6,
) -> list[dict[str, Any]]:
    """Deduplicate governance red flags by text similarity.

    Simple dedup: normalize text, skip near-duplicates, cap at max_flags.
    """
    if not flags:
        return []

    seen_texts: list[str] = []
    deduped: list[dict[str, Any]] = []

    for flag in flags:
        text = (flag.get("description", "") or flag.get("text", "")).strip().lower()
        if not text:
            continue

        # Simple overlap check — skip if >threshold fraction of words overlap
        is_dup = False
        text_words = set(text.split())
        for seen in seen_texts:
            seen_words = set(seen.split())
            if not text_words or not seen_words:
                continue
            overlap = len(text_words & seen_words) / max(len(text_words), len(seen_words))
            if overlap >= similarity_threshold:
                is_dup = True
                break

        if not is_dup:
            deduped.append(flag)
            seen_texts.append(text)

        if len(deduped) >= max_flags:
            break

    return deduped

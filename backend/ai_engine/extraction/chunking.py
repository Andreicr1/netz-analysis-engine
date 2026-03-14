"""Document chunking — semantic-first with simple fallback.

Primary: Semantic chunker (adaptive sizing by doc_type, breadcrumb,
section_type, has_table, has_numbers). Requires markdown text + doc_type.

Fallback: Page-boundary chunking (~4,000 chars per chunk, 1-page overlap).
Used for non-PDF files or when semantic chunker is unavailable.

Both paths produce chunks compatible with the search document builder.
"""
from __future__ import annotations

import logging
from typing import TypedDict

logger = logging.getLogger(__name__)


class Chunk(TypedDict):
    chunk_index: int
    page_start: int
    page_end: int
    content: str


class EnrichedChunk(TypedDict, total=False):
    """Extended chunk with semantic metadata from the semantic chunker."""
    chunk_index: int
    page_start: int
    page_end: int
    content: str
    breadcrumb: str
    section_type: str
    has_table: bool
    has_numbers: bool
    char_count: int
    token_estimate: int


class PageInput(TypedDict):
    page_start: int
    page_end: int
    text: str


# Maximum characters per chunk (simple chunker)
_TARGET_CHUNK_SIZE = 4_000
_OVERLAP_PAGES = 1


def chunk_document_simple(pages: list[PageInput]) -> list[Chunk]:
    """Simple page-boundary chunking (~4,000 chars).

    Legacy chunker — used as fallback when doc_type or markdown text
    is not available (e.g. non-PDF files processed via pypdf).
    """
    if not pages:
        return []

    chunks: list[Chunk] = []
    chunk_index = 0
    current_text_parts: list[str] = []
    current_char_count = 0
    current_page_start: int | None = None
    current_page_end: int = 0

    for page in pages:
        page_text = page["text"]
        page_start = page["page_start"]
        page_end = page["page_end"]
        page_len = len(page_text)

        if current_page_start is None:
            current_page_start = page_start

        # If adding this page would exceed target and we have content, flush
        if current_char_count > 0 and (current_char_count + page_len) > _TARGET_CHUNK_SIZE:
            if current_page_start is None:
                current_page_start = page_start
            chunks.append(Chunk(
                chunk_index=chunk_index,
                page_start=current_page_start,
                page_end=current_page_end,
                content="\n\n".join(current_text_parts),
            ))
            chunk_index += 1

            if _OVERLAP_PAGES > 0 and current_text_parts:
                overlap_text = current_text_parts[-1]
                current_text_parts = [overlap_text]
                current_char_count = len(overlap_text)
                current_page_start = current_page_end
            else:
                current_text_parts = []
                current_char_count = 0
                current_page_start = page_start

        current_text_parts.append(page_text)
        current_char_count += page_len
        current_page_end = page_end

    if current_text_parts and current_page_start is not None:
        chunks.append(Chunk(
            chunk_index=chunk_index,
            page_start=current_page_start,
            page_end=current_page_end,
            content="\n\n".join(current_text_parts),
        ))

    return chunks


# Preserve backward compatibility — existing callers use chunk_document(pages)
def chunk_document(pages: list[PageInput]) -> list[Chunk]:
    """Backward-compatible entry point. Delegates to simple chunker."""
    return chunk_document_simple(pages)


def chunk_document_semantic(
    pages: list[PageInput],
    *,
    doc_id: str,
    doc_type: str,
    metadata: dict | None = None,
) -> list[EnrichedChunk]:
    """Semantic chunking with adaptive sizing, breadcrumb, section_type.

    Uses the semantic chunker when available, falls back to simple chunking.

    Args:
        pages: List of page dicts with page_start, page_end, text.
        doc_id: Unique document identifier.
        doc_type: Classified document type (e.g. "legal_lpa").
        metadata: Additional metadata to propagate into each chunk.

    Returns:
        List of EnrichedChunk dicts with semantic metadata.

    """
    if not pages:
        return []

    # Combine pages into markdown text
    markdown = "\n\n".join(p["text"] for p in pages)
    if not markdown.strip():
        return []

    # Compute page range
    all_page_starts = [p["page_start"] for p in pages]
    all_page_ends = [p["page_end"] for p in pages]
    doc_page_start = min(all_page_starts) if all_page_starts else 1
    doc_page_end = max(all_page_ends) if all_page_ends else 1

    try:
        from ai_engine.extraction.semantic_chunker import chunk_document as semantic_chunk

        raw_chunks = semantic_chunk(
            ocr_markdown=markdown,
            doc_id=doc_id,
            doc_type=doc_type,
            metadata=metadata or {},
        )

        if not raw_chunks:
            logger.warning("Semantic chunker returned empty — falling back to simple: %s", doc_id)
            return _simple_to_enriched(pages, doc_type)

        enriched: list[EnrichedChunk] = []
        for c in raw_chunks:
            enriched.append(EnrichedChunk(
                chunk_index=c.get("chunk_index", 0),
                page_start=doc_page_start,
                page_end=doc_page_end,
                content=c.get("content", ""),
                breadcrumb=c.get("breadcrumb", ""),
                section_type=c.get("section_type", "other"),
                has_table=c.get("has_table", False),
                has_numbers=c.get("has_numbers", False),
                char_count=c.get("char_count", len(c.get("content", ""))),
                token_estimate=c.get("token_estimate", 0),
            ))

        logger.info(
            "Semantic chunker produced %d chunks for %s (doc_type=%s)",
            len(enriched), doc_id, doc_type,
        )
        return enriched

    except Exception:
        logger.warning(
            "Semantic chunker failed — falling back to simple: %s",
            doc_id, exc_info=True,
        )
        return _simple_to_enriched(pages, doc_type)


def _simple_to_enriched(pages: list[PageInput], doc_type: str = "other") -> list[EnrichedChunk]:
    """Convert simple chunks to EnrichedChunk format with default metadata."""
    simple = chunk_document_simple(pages)
    return [
        EnrichedChunk(
            chunk_index=c["chunk_index"],
            page_start=c["page_start"],
            page_end=c["page_end"],
            content=c["content"],
            breadcrumb="",
            section_type="other",
            has_table=False,
            has_numbers=False,
            char_count=len(c["content"]),
            token_estimate=len(c["content"]) // 4,
        )
        for c in simple
    ]

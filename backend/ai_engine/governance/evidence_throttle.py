"""Evidence Throttling - Top-K institutional limit on context chunks.

Prevents unlimited chunk injection into LLM prompts.  Every engine
that builds a prompt from RAG chunks MUST pass them through
``throttle_chunks()`` before concatenation.

Limits:
  MAX_EVIDENCE_CHUNKS = 200   (no prompt ever sees more than 20 chunks)
  MAX_CHUNK_CHARS     = 50000 (each chunk trimmed to 1 200 chars)
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Institutional limits
# ---------------------------------------------------------------------------
MAX_EVIDENCE_CHUNKS = 200
"""Maximum number of evidence chunks in any single LLM prompt."""

MAX_CHUNK_CHARS = 50_000
"""Maximum character length per individual chunk."""


def throttle_chunks(chunks: list[str], *, max_chunks: int | None = None, max_chars: int | None = None) -> list[str]:
    """Trim and cap a list of text chunks."""
    limit_n = max_chunks if max_chunks is not None else MAX_EVIDENCE_CHUNKS
    limit_c = max_chars if max_chars is not None else MAX_CHUNK_CHARS
    original_count = len(chunks)
    trimmed = [c[:limit_c] for c in chunks]
    capped = trimmed[:limit_n]
    if original_count > limit_n or any(len(c) > limit_c for c in chunks):
        logger.info("EVIDENCE_THROTTLED chunks_in=%d chunks_out=%d max_chars=%d", original_count, len(capped), limit_c)
    return capped


def throttle_chunk_dicts(
    chunks: list[dict],
    *,
    content_key: str = "content",
    max_chunks: int | None = None,
    max_chars: int | None = None,
) -> list[dict]:
    """Throttle a list of chunk dicts (preserving metadata)."""
    limit_n = max_chunks if max_chunks is not None else MAX_EVIDENCE_CHUNKS
    limit_c = max_chars if max_chars is not None else MAX_CHUNK_CHARS
    original_count = len(chunks)
    result = []
    for chunk in chunks[:limit_n]:
        c = dict(chunk)
        content = c.get(content_key, "")
        c[content_key] = content[:limit_c]
        result.append(c)
    if original_count > limit_n:
        logger.info("EVIDENCE_THROTTLED_DICTS chunks_in=%d chunks_out=%d", original_count, len(result))
    return result

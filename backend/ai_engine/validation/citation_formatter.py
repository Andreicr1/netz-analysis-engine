"""Citation formatting utilities for AI engine outputs."""
from __future__ import annotations

from typing import Any


def format_citations(chunks: list[Any]) -> list[dict[str, Any]]:
    """Format evidence chunks into a list of citation dicts for API responses.

    Each citation includes chunk_id, source_blob, doc_type, domain,
    and a short excerpt.
    """
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()

    for c in chunks:
        cid = getattr(c, "chunk_id", None) or "UNKNOWN"
        if cid in seen:
            continue
        seen.add(cid)

        text = getattr(c, "chunk_text", "") or ""
        excerpt = text[:300] + ("..." if len(text) > 300 else "")

        citations.append({
            "chunk_id": cid,
            "source_blob": getattr(c, "source_blob", "") or "",
            "doc_type": getattr(c, "doc_type", "") or "",
            "domain": getattr(c, "domain", "") or "",
            "excerpt": excerpt,
            "search_score": getattr(c, "search_score", None),
        })

    return citations

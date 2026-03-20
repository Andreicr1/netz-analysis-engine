"""Local cross-encoder reranker — replaces Cohere Rerank.

Uses sentence-transformers CrossEncoder for re-scoring (query, passage) pairs.
Model runs locally on CPU — zero external API calls.

Usage:
    from ai_engine.extraction.local_reranker import rerank

    results = rerank(
        query="What are the management fees?",
        documents=[{"content": "The GP charges 1.5%...", ...}, ...],
        top_k=10,
    )

The reranker adds a ``reranker_score`` field to each document and returns
them sorted by descending reranker_score.  Original ``score`` (cosine) is
preserved for downstream consumers that inspect both.
"""
from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

# ── Model config ─────────────────────────────────────────────────────

# Proven performer for information-retrieval reranking.
# ~80 MB, runs on CPU in < 100ms for 50 pairs.
_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# ── Lazy singleton (never at module level — asyncio safety) ──────────

_cross_encoder = None
_load_failed = False


def _get_cross_encoder():
    """Load the CrossEncoder model lazily on first call.

    Returns None if sentence-transformers is not installed (graceful
    degradation — cosine score is used as-is).
    """
    global _cross_encoder, _load_failed

    if _load_failed:
        return None
    if _cross_encoder is not None:
        return _cross_encoder

    try:
        from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]

        t0 = time.time()
        _cross_encoder = CrossEncoder(_MODEL_NAME)
        logger.info(
            "CrossEncoder loaded: model=%s, time=%.1fs",
            _MODEL_NAME,
            time.time() - t0,
        )
        return _cross_encoder
    except ImportError:
        logger.warning(
            "sentence-transformers not installed — reranker disabled, "
            "falling back to cosine similarity scores. "
            "Install with: pip install -e '.[reranker]'"
        )
        _load_failed = True
        return None
    except Exception:
        logger.exception("Failed to load CrossEncoder model %s", _MODEL_NAME)
        _load_failed = True
        return None


# ── Public API ───────────────────────────────────────────────────────


def rerank(
    query: str,
    documents: list[dict[str, Any]],
    *,
    top_k: int | None = None,
    content_key: str = "content",
    score_key: str = "reranker_score",
) -> list[dict[str, Any]]:
    """Re-score and re-sort documents using a cross-encoder.

    Parameters
    ----------
    query : str
        The search query.
    documents : list[dict]
        Retrieved documents.  Each must have ``content_key`` field.
    top_k : int | None
        If set, return only the top-k results after reranking.
        If None, return all documents (sorted).
    content_key : str
        Dict key containing the passage text (default ``"content"``).
    score_key : str
        Dict key where the reranker score is written (default
        ``"reranker_score"``).

    Returns
    -------
    list[dict]
        Documents sorted by descending reranker_score.  Each dict is
        mutated in-place with the new ``score_key`` field.  If the model
        is unavailable, documents are returned unchanged (sorted by
        original ``score``).
    """
    if not documents:
        return documents

    encoder = _get_cross_encoder()

    if encoder is None:
        # Graceful degradation — use cosine score as reranker_score
        for doc in documents:
            doc[score_key] = doc.get("score", 0.0)
        documents.sort(key=lambda d: d.get(score_key, 0.0), reverse=True)
        if top_k:
            return documents[:top_k]
        return documents

    # Build (query, passage) pairs
    pairs = []
    for doc in documents:
        passage = doc.get(content_key) or ""
        # Truncate passages to ~512 tokens (~2000 chars) for the model's
        # max sequence length.  MiniLM-L-6-v2 has 512 token limit.
        pairs.append((query, passage[:2000]))

    t0 = time.time()
    scores = encoder.predict(pairs, show_progress_bar=False)
    elapsed = time.time() - t0

    logger.debug(
        "Reranked %d documents in %.2fs (model=%s)",
        len(documents),
        elapsed,
        _MODEL_NAME,
    )

    for doc, score in zip(documents, scores, strict=False):
        doc[score_key] = float(score)

    documents.sort(key=lambda d: d.get(score_key, 0.0), reverse=True)

    if top_k:
        return documents[:top_k]
    return documents


def rerank_sync(
    query: str,
    documents: list[dict[str, Any]],
    *,
    top_k: int | None = None,
    content_key: str = "content",
) -> list[dict[str, Any]]:
    """Sync alias — same as rerank() (model inference is sync)."""
    return rerank(
        query, documents, top_k=top_k, content_key=content_key,
    )

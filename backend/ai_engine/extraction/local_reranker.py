"""Local cross-encoder reranker — replaces Cohere Rerank for RAG chunk relevance.

Uses ``cross-encoder/ms-marco-MiniLM-L-6-v2`` via ``sentence-transformers``.
22 MB weights, ~250-350 MB total RSS with PyTorch runtime.

NOT used for classification (that's ``hybrid_classifier``).  This is
strictly for reranking chunks by relevance to a query in the RAG pipeline.

Thread safety:
    ``CrossEncoder.predict()`` is NOT thread-safe — shared state in the
    tokenizer can collide under concurrent calls.  All predict calls are
    serialized with ``asyncio.Lock`` (lazy-init per CLAUDE.md) and wrapped
    in ``asyncio.to_thread()`` to avoid blocking the event loop.
"""
from __future__ import annotations

import asyncio
import logging
import math
import threading
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Model identifier — pinned to known-good commit.
_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_MODEL_REVISION = "c510bff"  # Pin to known-good commit


@dataclass(frozen=True)
class RerankResult:
    """Single rerank result."""
    index: int
    score: float        # 0.0–1.0 (sigmoid-normalized)
    text: str


# ── Lazy model loading ───────────────────────────────────────────────
# Double-checked locking: _model is guarded by _init_lock.
# Both are created lazily inside async functions (not module-level)
# per CLAUDE.md rule against module-level asyncio primitives.

_model = None
_init_lock: asyncio.Lock | None = None
_predict_lock: asyncio.Lock | None = None
_bootstrap_lock = threading.Lock()  # Not an asyncio primitive — safe at module level


def _get_init_lock() -> asyncio.Lock:
    """Get or create the init lock (lazy, not module-level)."""
    global _init_lock
    if _init_lock is None:
        with _bootstrap_lock:
            if _init_lock is None:
                _init_lock = asyncio.Lock()
    return _init_lock


def _get_predict_lock() -> asyncio.Lock:
    """Get or create the predict lock (lazy, not module-level)."""
    global _predict_lock
    if _predict_lock is None:
        with _bootstrap_lock:
            if _predict_lock is None:
                _predict_lock = asyncio.Lock()
    return _predict_lock


async def _ensure_model():
    """Load cross-encoder model with double-checked locking."""
    global _model
    if _model is not None:
        return _model

    async with _get_init_lock():
        # Double-check after acquiring lock
        if _model is not None:
            return _model

        logger.info("Loading cross-encoder model: %s", _MODEL_NAME)

        def _load():
            from sentence_transformers import CrossEncoder
            return CrossEncoder(_MODEL_NAME, revision=_MODEL_REVISION)

        _model = await asyncio.to_thread(_load)
        logger.info("Cross-encoder model loaded successfully")
        return _model


# ── Score normalization ──────────────────────────────────────────────

def _stable_sigmoid(x: float) -> float:
    """Numerically stable sigmoid for both positive and negative logits.

    Raw cross-encoder logits range ~-11 to +11.
    Do NOT use ``apply_softmax=True`` (single-label model returns 1.0 always).
    """
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    # For negative x, use the numerically stable form
    exp_x = math.exp(x)
    return exp_x / (1.0 + exp_x)


# ── Public API ───────────────────────────────────────────────────────

async def rerank(
    query: str,
    documents: list[str],
    *,
    top_n: int | None = None,
) -> list[RerankResult]:
    """Rerank documents by relevance to query using local cross-encoder.

    Returns results sorted by score descending.

    Threshold guidance for IC memo evidence:
        >0.8 = high confidence
        0.5-0.8 = include with caveats
        <0.3 = filter out
    These differ from Cohere scales — downstream consumers must recalibrate.
    """
    if not documents:
        return []

    model = await _ensure_model()

    # Build pairs for cross-encoder
    pairs = [[query, doc] for doc in documents]

    # Serialize predict calls — CrossEncoder.predict() is NOT thread-safe.
    async with _get_predict_lock():
        raw_scores = await asyncio.to_thread(model.predict, pairs)

    # Normalize scores via sigmoid and build results
    results = []
    for i, (raw_score, doc) in enumerate(zip(raw_scores, documents, strict=True)):
        score = _stable_sigmoid(float(raw_score))
        results.append(RerankResult(index=i, score=score, text=doc))

    # Sort by score descending
    results.sort(key=lambda r: r.score, reverse=True)

    if top_n is not None:
        results = results[:top_n]

    return results

"""Embedding generation — centralised via openai_client.

REFACTOR (Phase 1, Step 2): Consolidated from app.services.embeddings
(which used get_foundry_client()) to ai_engine.openai_client.create_embedding().

Uses text-embedding-3-large (3072 dimensions) via OpenAI API.
Provides batch-aware generation with configurable batch size.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# OpenAI embedding batch limit
_MAX_BATCH_SIZE = 500


@dataclass(frozen=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    model: str | None
    count: int


def generate_embeddings(texts: list[str], *, batch_size: int = _MAX_BATCH_SIZE) -> EmbeddingBatch:
    """Generate embeddings for a list of texts in batches.

    Returns all vectors in order, matching the input list indices.
    Raises if the embedding service is not configured.
    """
    from ai_engine.openai_client import create_embedding

    if not texts:
        return EmbeddingBatch(vectors=[], model=None, count=0)

    all_vectors: list[list[float]] = []
    model: str | None = None

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        result = create_embedding(inputs=batch)

        if result.vectors is None or len(result.vectors) == 0:
            raise RuntimeError("Embedding generation returned no vectors")

        all_vectors.extend(result.vectors)
        model = result.model

    return EmbeddingBatch(vectors=all_vectors, model=model, count=len(all_vectors))


async def async_generate_embeddings(
    texts: list[str], *, batch_size: int = _MAX_BATCH_SIZE,
) -> EmbeddingBatch:
    """Async version of ``generate_embeddings`` using ``async_create_embedding``.

    Returns all vectors in order, matching the input list indices.
    """
    from ai_engine.openai_client import async_create_embedding

    if not texts:
        return EmbeddingBatch(vectors=[], model=None, count=0)

    all_vectors: list[list[float]] = []
    model: str | None = None

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        result = await async_create_embedding(inputs=batch)

        if result.vectors is None or len(result.vectors) == 0:
            raise RuntimeError("Embedding generation returned no vectors")

        all_vectors.extend(result.vectors)
        model = result.model

    return EmbeddingBatch(vectors=all_vectors, model=model, count=len(all_vectors))

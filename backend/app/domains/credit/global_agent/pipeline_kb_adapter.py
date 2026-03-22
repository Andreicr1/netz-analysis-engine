"""pgvector adapter for the pipeline chunks index.

Replaces the former Azure AI Search adapter. Queries vector_chunks
table filtered by domain='PIPELINE' and organization_id for tenant isolation.
"""
from __future__ import annotations

import logging
import re
import uuid as _uuid
from typing import Any

from ai_engine.extraction.kb_schema import ComplianceChunk, DocType
from ai_engine.extraction.pgvector_search_service import (
    _get_sync_engine,
    validate_domain,
    validate_uuid,
)
from sqlalchemy import text

logger = logging.getLogger(__name__)

PIPELINE_DOMAIN: str = "PIPELINE"

# Pre-compute the set of accepted DocType values for fast lookup
_VALID_DOC_TYPES: set[str] = set(DocType.__args__)  # type: ignore[attr-defined]

# Patterns that indicate the user wants a broad overview (all deals),
# not a specific deal search. In these cases we do a wildcard search
# grouped by deal_id to get diverse coverage.
_OVERVIEW_PATTERNS = re.compile(
    r"(pipeline|todos os deals|all deals|overview|visão geral|carteira"
    r"|portf[oó]lio.*completo|quantos deals|how many deals"
    r"|resumo.*fundo|fund summary|pipeline.*atual|current.*pipeline)",
    re.IGNORECASE,
)


class PipelineKBAdapter:
    """Retrieves chunks from pgvector vector_chunks table.
    Results are mapped to ComplianceChunk so the global agent can merge
    pipeline evidence with regulatory evidence seamlessly.
    """

    @staticmethod
    def search_live(
        query: str,
        organization_id: _uuid.UUID | str,
        deal_folder: str | None = None,
        top: int = 20,
    ) -> list[ComplianceChunk]:
        """Semantic search against pgvector for pipeline chunks.

        For overview questions (pipeline summary, all deals, etc.), performs
        a broad search and ensures diverse deal coverage by selecting top
        chunks from each unique deal_id.

        All queries include organization_id for tenant isolation.
        """
        from ai_engine.extraction.embedding_service import generate_embeddings

        safe_org = validate_uuid(organization_id, "organization_id")

        is_overview = not deal_folder and bool(_OVERVIEW_PATTERNS.search(query))

        try:
            # Generate query embedding
            batch = generate_embeddings([query])
            if not batch.embeddings:
                logger.warning("PIPELINE_KB empty embedding for query=%r", query[:80])
                return []
            query_vector = batch.embeddings[0]

            if is_overview:
                chunks = _overview_search(safe_org, query_vector, top)
            else:
                chunks = _standard_search(safe_org, query_vector, top, deal_folder)

            logger.info(
                "PIPELINE_KB query=%r deal_folder=%s is_overview=%s hits=%d",
                query[:80],
                deal_folder,
                is_overview,
                len(chunks),
            )
            return chunks

        except Exception as exc:
            logger.warning(
                "SEARCH_INDEX_UNAVAILABLE: pipeline search degraded, "
                "RAG query returned empty results. error=%s: %s",
                type(exc).__name__,
                exc,
            )
            return []


def _standard_search(
    org_id: str,
    query_vector: list[float],
    top: int,
    deal_folder: str | None,
) -> list[ComplianceChunk]:
    """Targeted cosine similarity search, optionally scoped to a deal."""
    from ai_engine.pipeline.storage_routing import _SAFE_PATH_SEGMENT_RE

    params: dict[str, Any] = {
        "embedding": str(query_vector),
        "org_id": org_id,
        "domain": PIPELINE_DOMAIN,
        "top": top,
    }

    if deal_folder:
        if not _SAFE_PATH_SEGMENT_RE.match(deal_folder):
            raise ValueError(f"Invalid deal_folder: {deal_folder!r}")
        # deal_folder is typically the deal_id in pgvector
        params["deal_id"] = deal_folder
        sql = text("""
            SELECT id, deal_id, domain, doc_type, doc_id, title, content,
                   page_start, page_end, chunk_index,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM vector_chunks
            WHERE organization_id = CAST(:org_id AS uuid)
              AND deal_id = :deal_id
              AND domain = :domain
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top
        """)
    else:
        sql = text("""
            SELECT id, deal_id, domain, doc_type, doc_id, title, content,
                   page_start, page_end, chunk_index,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS score
            FROM vector_chunks
            WHERE organization_id = CAST(:org_id AS uuid)
              AND domain = :domain
              AND embedding IS NOT NULL
            ORDER BY embedding <=> CAST(:embedding AS vector)
            LIMIT :top
        """)

    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(sql, params)
        rows = result.mappings().all()
        return [_to_chunk(dict(r)) for r in rows]


def _overview_search(
    org_id: str,
    query_vector: list[float],
    top: int,
) -> list[ComplianceChunk]:
    """Broad search that ensures coverage of all deals.

    Fetches a large candidate set, groups by deal_id, and picks the
    best chunks from each deal to ensure the LLM sees all deals.
    """
    fetch_size = max(top * 5, 100)

    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT id, deal_id, domain, doc_type, doc_id, title, content,
                       page_start, page_end, chunk_index,
                       1 - (embedding <=> CAST(:embedding AS vector)) AS score
                FROM vector_chunks
                WHERE organization_id = CAST(:org_id AS uuid)
                  AND domain = :domain
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :top
            """),
            {
                "embedding": str(query_vector),
                "org_id": org_id,
                "domain": PIPELINE_DOMAIN,
                "top": fetch_size,
            },
        )
        rows = result.mappings().all()

    # Group by deal_id
    by_deal: dict[str, list[dict]] = {}
    for r in rows:
        row = dict(r)
        deal = row.get("deal_id") or "unknown"
        by_deal.setdefault(deal, []).append(row)

    num_deals = len(by_deal)
    if num_deals == 0:
        return []

    chunks_per_deal = max(2, top // num_deals)
    selected: list[ComplianceChunk] = []

    for _folder, results in sorted(by_deal.items()):
        # Already sorted by score from SQL
        for r in results[:chunks_per_deal]:
            selected.append(_to_chunk(r))

    # Sort all selected by score, cap at top
    selected.sort(key=lambda c: c.search_score or 0.0, reverse=True)

    logger.info(
        "PIPELINE_KB overview_search deals_found=%d chunks_selected=%d",
        num_deals,
        len(selected),
    )
    return selected[:top]


def _to_chunk(r: dict) -> ComplianceChunk:
    """Convert a pgvector result dict to a ComplianceChunk."""
    raw_doc_type = r.get("doc_type") or "OTHER"
    safe_doc_type = raw_doc_type if raw_doc_type in _VALID_DOC_TYPES else "OTHER"

    return ComplianceChunk(
        chunk_id=r.get("id", "UNKNOWN"),
        doc_id=r.get("doc_id") or r.get("id") or "UNKNOWN",
        domain=PIPELINE_DOMAIN,
        doc_type=safe_doc_type,
        source_blob=r.get("title") or "unknown",
        chunk_text=r.get("content", ""),
        search_score=r.get("score"),
    )

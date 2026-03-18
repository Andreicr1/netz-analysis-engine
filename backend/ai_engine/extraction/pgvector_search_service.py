"""pgvector search service — drop-in replacement for Azure AI Search.

Exposes the same function signatures as search_upsert_service.py:
- upsert_chunks()
- search_deal_chunks()
- search_fund_policy_chunks()

All queries enforce organization_id filter (RLS complement).
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Lazy sync engine for callers that don't have an AsyncSession ──────

_sync_engine: Engine | None = None


def _get_sync_engine() -> Engine:
    """Create a sync SQLAlchemy engine lazily (for sync search callers)."""
    global _sync_engine
    if _sync_engine is None:
        from app.core.config.settings import settings
        sync_url = settings.database_url.replace("+asyncpg", "+psycopg")
        _sync_engine = create_engine(
            sync_url,
            pool_size=5,
            max_overflow=5,
            pool_pre_ping=True,
            pool_recycle=300,
        )
    return _sync_engine


@dataclass(frozen=True)
class UpsertResult:
    """Structured result from a pgvector upsert operation."""

    attempted_chunk_count: int
    successful_chunk_count: int
    failed_chunk_count: int
    retryable: bool
    batch_errors: list[str] = field(default_factory=list)

    @property
    def is_full_success(self) -> bool:
        return self.failed_chunk_count == 0 and self.successful_chunk_count > 0

    @property
    def is_degraded(self) -> bool:
        return self.failed_chunk_count > 0 and self.successful_chunk_count > 0

    @property
    def is_total_failure(self) -> bool:
        return self.successful_chunk_count == 0 and self.attempted_chunk_count > 0


@dataclass(frozen=True)
class ChunkSearchResult:
    """Single result from a pgvector similarity search."""

    id: str
    deal_id: str | None
    fund_id: str | None
    domain: str
    doc_type: str | None
    title: str | None
    content: str
    page_start: int | None
    page_end: int | None
    chunk_index: int | None
    score: float


# ── ID sanitization (same as Azure Search service) ────────────────────


def _safe_id(raw: str) -> str:
    """Sanitize a document id (alphanumeric, dash, underscore only)."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)


# ── Validation helpers (re-exported for callers that imported them) ────


_VALID_DOMAINS = frozenset({
    "credit", "wealth", "macro", "benchmark",
    "POLICY", "REGULATORY", "CONSTITUTION", "SERVICE_PROVIDER",
    "PIPELINE",
})


def validate_uuid(value: str | uuid.UUID, field_name: str = "id") -> str:
    """Validate and normalize UUID. Returns lowercase hyphenated form."""
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid UUID for {field_name}: {value!r}")


def validate_domain(domain: str) -> str:
    """Validate domain against allowlist."""
    if domain not in _VALID_DOMAINS:
        raise ValueError(f"Invalid domain filter: {domain!r}")
    return domain


# ── Build search document ─────────────────────────────────────────────


def build_search_document(
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    domain: str,
    doc_type: str,
    authority: str,
    title: str,
    chunk_index: int,
    content: str,
    embedding: list[float],
    page_start: int,
    page_end: int,
    document_id: uuid.UUID | None = None,
    doc_summary: str | None = None,
    doc_metadata: str | None = None,
    vehicle_type: str | None = None,
    section_type: str | None = None,
    breadcrumb: str | None = None,
    has_table: bool | None = None,
    has_numbers: bool | None = None,
    char_count: int | None = None,
    governance_critical: bool | None = None,
    governance_flags: list[str] | None = None,
    borrower_sector: str | None = None,
    loan_structure: str | None = None,
    key_persons_mentioned: list[str] | None = None,
    financial_metric_type: str | None = None,
    risk_flags: list[str] | None = None,
    organization_id: uuid.UUID | None = None,
    extraction_degraded: bool | None = None,
    extraction_quality: dict[str, str] | None = None,
    container_name: str | None = None,
    blob_name: str | None = None,
) -> dict[str, Any]:
    """Build a document dict for pgvector upsert.

    Chunk ID formula: {deal_id}_{document_id}_{chunk_index} (v2).
    Falls back to {deal_id}_{doc_type}_{chunk_index} if no document_id.
    """
    if document_id is not None:
        doc_id = _safe_id(f"{deal_id}_{document_id}_{chunk_index}")
    else:
        doc_id = _safe_id(f"{deal_id}_{doc_type}_{chunk_index}")

    return {
        "id": doc_id,
        "organization_id": str(organization_id) if organization_id else None,
        "deal_id": str(deal_id),
        "fund_id": str(fund_id),
        "domain": domain,
        "doc_type": doc_type,
        "doc_id": str(document_id) if document_id else None,
        "title": title,
        "content": content,
        "page_start": page_start,
        "page_end": page_end,
        "chunk_index": chunk_index,
        "section_type": section_type,
        "breadcrumb": breadcrumb,
        "governance_critical": governance_critical or False,
        "embedding": embedding,
        "embedding_model": None,  # set by caller or from env
    }


# ── Upsert ────────────────────────────────────────────────────────────


async def upsert_chunks(
    db: AsyncSession,
    documents: list[dict[str, Any]],
) -> UpsertResult:
    """Upsert chunks into vector_chunks via INSERT ... ON CONFLICT DO UPDATE."""
    if not documents:
        return UpsertResult(
            attempted_chunk_count=0,
            successful_chunk_count=0,
            failed_chunk_count=0,
            retryable=False,
        )

    # Duplicate ID guard
    ids = [d["id"] for d in documents]
    seen: set[str] = set()
    duplicates: list[str] = []
    for doc_id in ids:
        if doc_id in seen:
            duplicates.append(doc_id)
        seen.add(doc_id)
    if duplicates:
        raise RuntimeError(
            f"Duplicate chunk IDs in batch ({len(duplicates)} collisions). "
            f"First: {duplicates[0]}."
        )

    succeeded = 0
    failed = 0
    errors: list[str] = []

    for doc in documents:
        try:
            embedding = doc.get("embedding")
            embedding_str = str(embedding) if embedding else None

            await db.execute(
                text("""
                    INSERT INTO vector_chunks (
                        id, organization_id, deal_id, fund_id, domain, doc_type,
                        doc_id, title, content, page_start, page_end, chunk_index,
                        section_type, breadcrumb, governance_critical,
                        embedding, embedding_model
                    ) VALUES (
                        :id, :organization_id::uuid, :deal_id, :fund_id, :domain,
                        :doc_type, :doc_id, :title, :content, :page_start, :page_end,
                        :chunk_index, :section_type, :breadcrumb, :governance_critical,
                        :embedding::vector, :embedding_model
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        content = EXCLUDED.content,
                        embedding = EXCLUDED.embedding,
                        embedding_model = EXCLUDED.embedding_model,
                        updated_at = NOW()
                """),
                {
                    "id": doc["id"],
                    "organization_id": doc.get("organization_id"),
                    "deal_id": doc.get("deal_id"),
                    "fund_id": doc.get("fund_id"),
                    "domain": doc.get("domain"),
                    "doc_type": doc.get("doc_type"),
                    "doc_id": doc.get("doc_id"),
                    "title": doc.get("title"),
                    "content": doc.get("content", ""),
                    "page_start": doc.get("page_start"),
                    "page_end": doc.get("page_end"),
                    "chunk_index": doc.get("chunk_index"),
                    "section_type": doc.get("section_type"),
                    "breadcrumb": doc.get("breadcrumb"),
                    "governance_critical": doc.get("governance_critical", False),
                    "embedding": embedding_str,
                    "embedding_model": doc.get("embedding_model"),
                },
            )
            succeeded += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{doc.get('id', '?')}: {exc}")
            logger.warning("pgvector upsert failed for chunk %s: %s", doc.get("id"), exc)

    logger.info("pgvector upserted %d/%d chunks", succeeded, len(documents))
    return UpsertResult(
        attempted_chunk_count=len(documents),
        successful_chunk_count=succeeded,
        failed_chunk_count=failed,
        retryable=failed > 0,
        batch_errors=errors,
    )


# ── Search ────────────────────────────────────────────────────────────


async def search_deal_chunks(
    db: AsyncSession,
    *,
    deal_id: uuid.UUID,
    organization_id: uuid.UUID | str,
    query_text: str | None = None,
    query_vector: list[float] | None = None,
    top: int = 20,
    domain_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Semantic search over deal chunks using cosine similarity.

    Returns list[dict] matching the Azure Search return format for
    backward compatibility with callers.
    """
    safe_deal = validate_uuid(deal_id, "deal_id")
    safe_org = validate_uuid(organization_id, "organization_id")

    if query_vector is None:
        return []

    if domain_filter:
        safe_domain = validate_domain(domain_filter)
        result = await db.execute(
            text("""
                SELECT
                    id, deal_id, domain, doc_type, title, content,
                    page_start, page_end, chunk_index,
                    1 - (embedding <=> :embedding::vector) AS score
                FROM vector_chunks
                WHERE organization_id = :org_id::uuid
                  AND deal_id = :deal_id
                  AND domain = :domain
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top
            """),
            {
                "embedding": str(query_vector),
                "org_id": safe_org,
                "deal_id": safe_deal,
                "domain": safe_domain,
                "top": top,
            },
        )
    else:
        result = await db.execute(
            text("""
                SELECT
                    id, deal_id, domain, doc_type, title, content,
                    page_start, page_end, chunk_index,
                    1 - (embedding <=> :embedding::vector) AS score
                FROM vector_chunks
                WHERE organization_id = :org_id::uuid
                  AND deal_id = :deal_id
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top
            """),
            {
                "embedding": str(query_vector),
                "org_id": safe_org,
                "deal_id": safe_deal,
                "top": top,
            },
        )

    rows = result.mappings().all()
    return [dict(row) for row in rows]


async def search_fund_policy_chunks(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID,
    organization_id: uuid.UUID | str,
    query_text: str | None = None,
    query_vector: list[float] | None = None,
    top: int = 30,
    domain_filter: str = "POLICY",
) -> list[dict[str, Any]]:
    """Semantic search over fund policy chunks using cosine similarity.

    Returns list[dict] matching the Azure Search return format.
    """
    safe_fund = validate_uuid(fund_id, "fund_id")
    safe_org = validate_uuid(organization_id, "organization_id")
    safe_domain = validate_domain(domain_filter)

    if query_vector is None:
        return []

    result = await db.execute(
        text("""
            SELECT
                id, deal_id, fund_id, domain, doc_type, title, content,
                page_start, page_end, chunk_index,
                1 - (embedding <=> :embedding::vector) AS score
            FROM vector_chunks
            WHERE organization_id = :org_id::uuid
              AND fund_id = :fund_id
              AND domain = :domain
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :embedding::vector
            LIMIT :top
        """),
        {
            "embedding": str(query_vector),
            "org_id": safe_org,
            "fund_id": safe_fund,
            "domain": safe_domain,
            "top": top,
        },
    )

    rows = result.mappings().all()
    return [dict(row) for row in rows]


# ── Sync search wrappers (for callers without AsyncSession) ───────────
#
# These mirror the Azure Search interface: no db parameter, standalone.
# Used by vertical_engines/ callers that are sync functions.


def upsert_chunks_sync(
    documents: list[dict[str, Any]],
) -> UpsertResult:
    """Sync upsert for callers without AsyncSession (e.g. search_rebuild)."""
    if not documents:
        return UpsertResult(
            attempted_chunk_count=0,
            successful_chunk_count=0,
            failed_chunk_count=0,
            retryable=False,
        )

    succeeded = 0
    failed = 0
    errors: list[str] = []

    engine = _get_sync_engine()
    with engine.begin() as conn:
        for doc in documents:
            try:
                embedding = doc.get("embedding")
                embedding_str = str(embedding) if embedding else None

                conn.execute(
                    text("""
                        INSERT INTO vector_chunks (
                            id, organization_id, deal_id, fund_id, domain, doc_type,
                            doc_id, title, content, page_start, page_end, chunk_index,
                            section_type, breadcrumb, governance_critical,
                            embedding, embedding_model
                        ) VALUES (
                            :id, :organization_id::uuid, :deal_id, :fund_id, :domain,
                            :doc_type, :doc_id, :title, :content, :page_start, :page_end,
                            :chunk_index, :section_type, :breadcrumb, :governance_critical,
                            :embedding::vector, :embedding_model
                        )
                        ON CONFLICT (id) DO UPDATE SET
                            content = EXCLUDED.content,
                            embedding = EXCLUDED.embedding,
                            embedding_model = EXCLUDED.embedding_model,
                            updated_at = NOW()
                    """),
                    {
                        "id": doc["id"],
                        "organization_id": doc.get("organization_id"),
                        "deal_id": doc.get("deal_id"),
                        "fund_id": doc.get("fund_id"),
                        "domain": doc.get("domain"),
                        "doc_type": doc.get("doc_type"),
                        "doc_id": doc.get("doc_id"),
                        "title": doc.get("title"),
                        "content": doc.get("content", ""),
                        "page_start": doc.get("page_start"),
                        "page_end": doc.get("page_end"),
                        "chunk_index": doc.get("chunk_index"),
                        "section_type": doc.get("section_type"),
                        "breadcrumb": doc.get("breadcrumb"),
                        "governance_critical": doc.get("governance_critical", False),
                        "embedding": embedding_str,
                        "embedding_model": doc.get("embedding_model"),
                    },
                )
                succeeded += 1
            except Exception as exc:
                failed += 1
                errors.append(f"{doc.get('id', '?')}: {exc}")

    return UpsertResult(
        attempted_chunk_count=len(documents),
        successful_chunk_count=succeeded,
        failed_chunk_count=failed,
        retryable=failed > 0,
        batch_errors=errors,
    )


def search_deal_chunks_sync(
    *,
    deal_id: uuid.UUID,
    organization_id: uuid.UUID | str,
    query_text: str | None = None,
    query_vector: list[float] | None = None,
    top: int = 20,
    domain_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Sync search over deal chunks — drop-in replacement for Azure Search."""
    safe_deal = validate_uuid(deal_id, "deal_id")
    safe_org = validate_uuid(organization_id, "organization_id")

    if query_vector is None:
        return []

    params: dict[str, Any] = {
        "embedding": str(query_vector),
        "org_id": safe_org,
        "deal_id": safe_deal,
        "top": top,
    }

    if domain_filter:
        safe_domain = validate_domain(domain_filter)
        params["domain"] = safe_domain
        query = text("""
            SELECT id, deal_id, domain, doc_type, title, content,
                   page_start, page_end, chunk_index,
                   1 - (embedding <=> :embedding::vector) AS score
            FROM vector_chunks
            WHERE organization_id = :org_id::uuid
              AND deal_id = :deal_id
              AND domain = :domain
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :embedding::vector
            LIMIT :top
        """)
    else:
        query = text("""
            SELECT id, deal_id, domain, doc_type, title, content,
                   page_start, page_end, chunk_index,
                   1 - (embedding <=> :embedding::vector) AS score
            FROM vector_chunks
            WHERE organization_id = :org_id::uuid
              AND deal_id = :deal_id
              AND embedding IS NOT NULL
            ORDER BY embedding <=> :embedding::vector
            LIMIT :top
        """)

    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(query, params)
        rows = result.mappings().all()
        return [dict(row) for row in rows]


def search_fund_policy_chunks_sync(
    *,
    fund_id: uuid.UUID,
    organization_id: uuid.UUID | str,
    query_text: str | None = None,
    query_vector: list[float] | None = None,
    top: int = 30,
    domain_filter: str = "POLICY",
) -> list[dict[str, Any]]:
    """Sync search over fund policy chunks — drop-in replacement for Azure Search."""
    safe_fund = validate_uuid(fund_id, "fund_id")
    safe_org = validate_uuid(organization_id, "organization_id")
    safe_domain = validate_domain(domain_filter)

    if query_vector is None:
        return []

    engine = _get_sync_engine()
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT id, deal_id, fund_id, domain, doc_type, title, content,
                       page_start, page_end, chunk_index,
                       1 - (embedding <=> :embedding::vector) AS score
                FROM vector_chunks
                WHERE organization_id = :org_id::uuid
                  AND fund_id = :fund_id
                  AND domain = :domain
                  AND embedding IS NOT NULL
                ORDER BY embedding <=> :embedding::vector
                LIMIT :top
            """),
            {
                "embedding": str(query_vector),
                "org_id": safe_org,
                "fund_id": safe_fund,
                "domain": safe_domain,
                "top": top,
            },
        )
        rows = result.mappings().all()
        return [dict(row) for row in rows]

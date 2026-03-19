"""Rebuild pgvector index from silver layer Parquet files.

Reads ``chunks.parquet`` from ``silver/{org_id}/{vertical}/chunks/{doc_id}/``
and upserts each chunk + embedding to pgvector.  No OCR, no
classification, no LLM calls — purely data movement.

Use cases:
  - Search schema changes
  - Embedding model upgrades (will reject incompatible files)
  - Index corruption recovery
  - Re-indexing after vector store migration
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from ai_engine.validation.vector_integrity_guard import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL_NAME,
)

logger = logging.getLogger(__name__)

try:
    from app.services.duckdb_client import get_duckdb_client

    _DUCKDB_AVAILABLE = True
except ImportError:
    _DUCKDB_AVAILABLE = False


@dataclass
class RebuildResult:
    """Summary of a search rebuild operation."""
    documents_processed: int = 0
    chunks_upserted: int = 0
    documents_skipped: int = 0
    resolved_index_name: str = ""
    errors: list[str] = field(default_factory=list)


async def rebuild_search_index(
    org_id: UUID,
    vertical: str,
    *,
    doc_ids: list[UUID] | None = None,
    deal_id: UUID | None = None,
    fund_id: UUID | None = None,
) -> RebuildResult:
    """Rebuild pgvector index from silver layer chunks.

    Args:
        org_id: Organization ID (tenant).
        vertical: Vertical name (``"credit"`` or ``"wealth"``).
        doc_ids: Optional list of specific document IDs to rebuild.
            When ``None``, rebuilds ALL documents for the org+vertical.
        deal_id: Deal ID to use in search documents.  Falls back to
            each document's ``doc_id`` if not provided.
        fund_id: Fund ID to use in search documents.  Falls back to
            each document's ``doc_id`` if not provided.

    Returns:
        ``RebuildResult`` with counts and any errors.
    """

    import redis.asyncio as aioredis

    from app.core.jobs.tracker import get_redis_pool

    # ── Advisory lock: prevent concurrent rebuilds for same org/vertical ──
    lock_key = f"rebuild:{org_id}:{vertical}"
    lock_ttl = 3600  # 1 hour
    rconn = aioredis.Redis(connection_pool=get_redis_pool())
    try:
        acquired = await rconn.set(lock_key, "1", nx=True, ex=lock_ttl)
    except Exception:
        logger.warning("[rebuild] Redis unavailable — proceeding without advisory lock")
        acquired = True  # degrade open: allow rebuild if Redis is down
    if not acquired:
        logger.warning(
            "[rebuild] Rebuild already in progress for %s/%s — skipping",
            org_id,
            vertical,
        )
        return RebuildResult(
            errors=[f"Rebuild already in progress for {org_id}/{vertical}"],
        )

    try:
        return await _do_rebuild(
            org_id=org_id,
            vertical=vertical,
            doc_ids=doc_ids,
            deal_id=deal_id,
            fund_id=fund_id,
        )
    finally:
        try:
            await rconn.delete(lock_key)
        except Exception:
            logger.warning("[rebuild] Failed to clear advisory lock key %s", lock_key)


async def _do_rebuild(
    org_id: UUID,
    vertical: str,
    *,
    doc_ids: list[UUID] | None = None,
    deal_id: UUID | None = None,
    fund_id: UUID | None = None,
) -> RebuildResult:
    """Inner rebuild logic, extracted for advisory-lock wrapper."""
    import asyncio

    from ai_engine.pipeline.storage_routing import silver_chunks_path
    from app.services.storage_client import get_storage_client

    storage = get_storage_client()
    result = RebuildResult(resolved_index_name="vector_chunks (pgvector)")

    logger.info(
        "[rebuild] Starting rebuild for %s/%s using pgvector",
        org_id,
        vertical,
    )

    # Determine which doc_ids to process
    if doc_ids is not None:
        target_ids = [str(d) for d in doc_ids]
    else:
        # List all chunk directories under the silver path
        prefix = f"silver/{org_id}/{vertical}/chunks/"
        all_files = await storage.list_files(prefix)
        # Extract doc_ids from paths like silver/{org}/credit/chunks/{doc_id}/chunks.parquet
        seen: set[str] = set()
        target_ids = []
        for path in all_files:
            parts = path.split("/")
            # Expected: silver / org_id / vertical / chunks / doc_id / chunks.parquet
            if len(parts) >= 6:
                did = parts[4]
                if did not in seen:
                    seen.add(did)
                    target_ids.append(did)

    if not target_ids:
        logger.info("[rebuild] No documents found for %s/%s", org_id, vertical)
        return result

    # ── DuckDB pre-rebuild audit (observability, never blocks) ────
    if _DUCKDB_AVAILABLE:
        try:
            duckdb = get_duckdb_client()
            stale = duckdb.stale_embeddings(
                org_id, vertical, EMBEDDING_MODEL_NAME, EMBEDDING_DIMENSIONS
            )
            dim_mismatches = duckdb.embedding_dimension_audit(
                org_id, vertical, EMBEDDING_DIMENSIONS
            )
            logger.info(
                "[rebuild] Pre-rebuild audit: stale=%d docs, dim_mismatch=%d docs",
                len(stale),
                len(dim_mismatches),
            )
        except Exception:
            logger.debug("[rebuild] DuckDB pre-rebuild audit failed", exc_info=True)
    else:
        logger.debug("[rebuild] DuckDB not available, skipping pre-rebuild audit")

    logger.info("[rebuild] Processing %d documents for %s/%s", len(target_ids), org_id, vertical)

    for doc_id_str in target_ids:
        try:
            path = silver_chunks_path(org_id, vertical, doc_id_str)
            parquet_bytes = await storage.read(path)
            chunks_upserted = await asyncio.to_thread(
                _rebuild_single_document,
                parquet_bytes=parquet_bytes,
                doc_id_str=doc_id_str,
                org_id=org_id,
                vertical=vertical,
                deal_id=deal_id,
                fund_id=fund_id,
            )
            result.documents_processed += 1
            result.chunks_upserted += chunks_upserted
        except FileNotFoundError:
            logger.warning("[rebuild] Parquet not found for doc %s", doc_id_str)
            result.documents_skipped += 1
            result.errors.append(f"Parquet not found: {doc_id_str}")
        except ValueError as exc:
            # Embedding dimension mismatch
            logger.error("[rebuild] Rejected doc %s: %s", doc_id_str, exc)
            result.documents_skipped += 1
            result.errors.append(f"Rejected {doc_id_str}: {exc}")
        except Exception:
            logger.error("[rebuild] Failed to rebuild doc %s", doc_id_str, exc_info=True)
            result.documents_skipped += 1
            result.errors.append(f"Failed: {doc_id_str}")

    logger.info(
        "[rebuild] Done: %d docs, %d chunks upserted, %d skipped",
        result.documents_processed,
        result.chunks_upserted,
        result.documents_skipped,
    )
    return result


def _rebuild_single_document(
    *,
    parquet_bytes: bytes,
    doc_id_str: str,
    org_id: UUID,
    vertical: str,
    deal_id: UUID | None,
    fund_id: UUID | None,
) -> int:
    """Read Parquet, validate embedding dims, upsert to pgvector.

    This is a sync function — called via ``asyncio.to_thread()``.
    Raises ``ValueError`` if embedding dimensions don't match.
    """
    import io
    import json

    import pyarrow.parquet as pq

    from ai_engine.extraction.pgvector_search_service import (
        build_search_document,
        upsert_chunks_sync,
    )

    table = pq.read_table(io.BytesIO(parquet_bytes))

    # ── Validate embedding dimensions ─────────────────────────────
    if "embedding_dim" in table.column_names:
        dims = table.column("embedding_dim").to_pylist()
        mismatched = [d for d in dims if d != EMBEDDING_DIMENSIONS]
        if mismatched:
            raise ValueError(
                f"Embedding dimension mismatch: file has {mismatched[0]}, "
                f"current model expects {EMBEDDING_DIMENSIONS}. "
                f"Re-embed the document before rebuilding."
            )

    # ── Build search documents ────────────────────────────────────
    doc_uuid = UUID(doc_id_str)
    effective_deal_id = deal_id or doc_uuid
    effective_fund_id = fund_id or doc_uuid

    search_docs: list[dict[str, Any]] = []
    for row in table.to_pylist():
        search_doc = build_search_document(
            deal_id=effective_deal_id,
            fund_id=effective_fund_id,
            domain=vertical,
            doc_type=row.get("doc_type", ""),
            authority="rebuild_service",
            title="",
            chunk_index=row.get("chunk_index", 0),
            content=row.get("content", ""),
            embedding=row.get("embedding", []),
            page_start=row.get("page_start", 0),
            page_end=row.get("page_end", 0),
            document_id=doc_uuid,
            vehicle_type=row.get("vehicle_type"),
            section_type=row.get("section_type"),
            breadcrumb=row.get("breadcrumb"),
            has_table=row.get("has_table"),
            has_numbers=row.get("has_numbers"),
            char_count=row.get("char_count"),
            governance_critical=row.get("governance_critical"),
            governance_flags=json.loads(row.get("governance_flags", "[]")) if row.get("governance_flags") else None,
            organization_id=org_id,
        )
        search_docs.append(search_doc)

    if not search_docs:
        return 0

    result = upsert_chunks_sync(search_docs)
    return result.successful_chunk_count

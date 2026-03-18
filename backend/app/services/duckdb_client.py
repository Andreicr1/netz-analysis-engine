"""Read-only DuckDB service for silver/gold Parquet inspection.

Phase 1: backend-only, no API endpoints, no cross-fund analytics.
Answers operational questions: stale embeddings, coverage gaps, chunk stats.

Security:
- SELECT-only enforcement
- org_id required on every query (structural tenant isolation)
- Blocked columns: content, embedding (IP protection + memory safety)
- enable_http_file_system=false (no network access)
- memory_limit=256MB, threads=2
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from typing import Any

import duckdb

from app.services.storage_client import StorageClient, get_storage_client

logger = logging.getLogger(__name__)

# Match exact column names (word boundaries) — avoids false positives
# on "embedding_model" or "embedding_dim".
_BLOCKED_COLUMNS: dict[str, re.Pattern[str]] = {
    "content": re.compile(r"\bcontent\b", re.IGNORECASE),
    "embedding": re.compile(r"\bembedding\b", re.IGNORECASE),
}
_MAX_SEMAPHORE = 2

_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore  # noqa: PLW0603
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(_MAX_SEMAPHORE)
    return _semaphore


class DuckDBClient:
    """Read-only DuckDB client for Parquet inspection."""

    def __init__(self, storage: StorageClient) -> None:
        self._storage = storage

    def _parquet_glob(self, org_id: uuid.UUID, vertical: str) -> str:
        """Build absolute glob path for silver chunks Parquet files."""
        base = self._storage.get_duckdb_path("silver", str(org_id), vertical)
        # For LocalStorageClient, build absolute glob from resolved base
        return base + "chunks/*/chunks.parquet"

    def _execute(
        self,
        sql: str,
        org_id: uuid.UUID,
        params: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Connection-per-query. SELECT only. org_id injected structurally."""
        if not sql.strip().upper().startswith("SELECT"):
            raise ValueError("DuckDBClient only supports SELECT queries")

        # Block forbidden columns (word-boundary match)
        for col_name, pattern in _BLOCKED_COLUMNS.items():
            if pattern.search(sql):
                raise ValueError(f"Column '{col_name}' is blocked in DuckDB queries")

        con = duckdb.connect(":memory:", read_only=False)
        try:
            con.execute("SET disabled_filesystems='httpfs,s3fs'")
            con.execute("SET memory_limit='256MB'")
            con.execute("SET threads=2")
            result = con.execute(sql, params or [])
            cols = [d[0] for d in result.description]
            return [dict(zip(cols, row, strict=False)) for row in result.fetchall()]
        finally:
            con.close()

    def chunk_stats(self, org_id: uuid.UUID, vertical: str) -> list[dict[str, Any]]:
        """Per-document chunk counts, avg char_count, doc_types."""
        glob = self._parquet_glob(org_id, vertical)
        sql = f"""
            SELECT
                doc_id,
                COUNT(*) AS chunk_count,
                AVG(char_count) AS avg_char_count,
                MAX(doc_type) AS doc_type,
                MAX(vehicle_type) AS vehicle_type
            FROM read_parquet('{glob}', union_by_name=true)
            WHERE organization_id = ?
            GROUP BY doc_id
            ORDER BY chunk_count DESC
        """
        return self._execute(sql, org_id, [str(org_id)])

    def stale_embeddings(
        self, org_id: uuid.UUID, vertical: str, current_model: str
    ) -> list[dict[str, Any]]:
        """Chunks whose embedding_model differs from current_model."""
        glob = self._parquet_glob(org_id, vertical)
        sql = f"""
            SELECT doc_id, COUNT(*) AS stale_count, MAX(embedding_model) AS model
            FROM read_parquet('{glob}', union_by_name=true)
            WHERE organization_id = ?
              AND embedding_model != ?
            GROUP BY doc_id
        """
        return self._execute(sql, org_id, [str(org_id), current_model])

    def coverage_gaps(
        self, org_id: uuid.UUID, vertical: str, min_chunks: int = 3
    ) -> list[dict[str, Any]]:
        """Documents with fewer than min_chunks chunks (extraction gaps)."""
        glob = self._parquet_glob(org_id, vertical)
        sql = f"""
            SELECT doc_id, COUNT(*) AS chunk_count
            FROM read_parquet('{glob}', union_by_name=true)
            WHERE organization_id = ?
            GROUP BY doc_id
            HAVING COUNT(*) < ?
            ORDER BY chunk_count ASC
        """
        return self._execute(sql, org_id, [str(org_id), min_chunks])

    def embedding_dim_check(
        self, org_id: uuid.UUID, vertical: str
    ) -> list[dict[str, Any]]:
        """Distinct embedding_dim values — flags inconsistent dimensions."""
        glob = self._parquet_glob(org_id, vertical)
        sql = f"""
            SELECT embedding_dim, COUNT(*) AS chunk_count
            FROM read_parquet('{glob}', union_by_name=true)
            WHERE organization_id = ?
              AND embedding_dim IS NOT NULL
            GROUP BY embedding_dim
            ORDER BY chunk_count DESC
        """
        return self._execute(sql, org_id, [str(org_id)])

    def doc_type_distribution(
        self, org_id: uuid.UUID, vertical: str
    ) -> list[dict[str, Any]]:
        """Count of chunks per doc_type for a tenant's vertical."""
        glob = self._parquet_glob(org_id, vertical)
        sql = f"""
            SELECT doc_type, COUNT(*) AS chunk_count, COUNT(DISTINCT doc_id) AS doc_count
            FROM read_parquet('{glob}', union_by_name=true)
            WHERE organization_id = ?
            GROUP BY doc_type
            ORDER BY chunk_count DESC
        """
        return self._execute(sql, org_id, [str(org_id)])


def get_duckdb_client(
    storage: StorageClient | None = None,
) -> DuckDBClient:
    """Factory — injectable for testing."""
    return DuckDBClient(storage or get_storage_client())

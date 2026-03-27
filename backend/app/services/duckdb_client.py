"""Read-only DuckDB service for silver/gold Parquet inspection.

Phase 1: backend-only, no API endpoints, no cross-fund analytics.
Answers operational questions: stale embeddings, coverage gaps, chunk stats.

Security:
- SELECT-only enforcement
- org_id required on every query (structural tenant isolation)
- Blocked columns: content, embedding (IP protection + memory safety)
- disabled_filesystems for network isolation
- memory_limit=256MB, threads=2
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import duckdb

from app.services.storage_client import StorageClient, get_storage_client

logger = logging.getLogger(__name__)

_BLOCKED_COLUMNS = frozenset({"content", "embedding"})


# ── Result dataclasses ────────────────────────────────────────────


@dataclass(frozen=True)
class StaleEmbeddingResult:
    doc_id: str
    chunk_count: int
    embedding_model: str


@dataclass(frozen=True)
class DocumentCoverageResult:
    doc_id: str
    doc_type: str
    chunk_count: int
    total_chars: int
    has_embeddings: bool


@dataclass(frozen=True)
class ExtractionQualityResult:
    doc_id: str
    doc_type: str
    total_chunks: int
    empty_chunks: int
    governance_flagged: int
    avg_char_count: float


@dataclass(frozen=True)
class ChunkStatsResult:
    total_chunks: int
    total_documents: int
    total_chars: int
    avg_chunk_chars: float
    median_chunk_chars: float
    p95_chunk_chars: float
    doc_type_distribution: dict[str, int]


@dataclass(frozen=True)
class DimensionMismatchResult:
    doc_id: str
    chunk_count: int
    embedding_dim: int


# ── Client ────────────────────────────────────────────────────────


class DuckDBClient:
    """Read-only DuckDB client for Parquet inspection."""

    _semaphore: asyncio.Semaphore | None = None

    def __init__(self, storage: StorageClient) -> None:
        self._storage = storage

    # ── Internal helpers ──────────────────────────────────────────

    def _parquet_glob(self, org_id: uuid.UUID, vertical: str) -> str:
        """Build absolute glob path for silver chunks Parquet files."""
        base = self._storage.get_duckdb_path("silver", org_id, vertical)
        return base + "chunks/*/chunks.parquet"

    def _execute(
        self,
        sql: str,
        org_id: uuid.UUID,
        params: list[Any] | None = None,
        *,
        method: str = "",
    ) -> list[dict[str, Any]]:
        """Connection-per-query. SELECT only. org_id injected structurally."""
        if not sql.strip().upper().startswith("SELECT"):
            raise ValueError("DuckDBClient only supports SELECT queries")

        conn = duckdb.connect(":memory:", read_only=False)
        try:
            conn.execute("SET memory_limit='256MB'")
            conn.execute("SET threads=2")
            conn.execute("SET enable_object_cache=true")
            conn.execute("SET allow_community_extensions=false")
            conn.execute("SET autoinstall_known_extensions=false")
            conn.execute("SET disabled_filesystems='httpfs,s3fs'")

            result = conn.execute(sql, params or [])
            cols = [d[0] for d in result.description]

            # Check blocked columns in result
            blocked_found = _BLOCKED_COLUMNS & set(cols)
            if blocked_found:
                raise ValueError(
                    f"Blocked column(s) in result: {', '.join(sorted(blocked_found))}",
                )

            return [dict(zip(cols, row, strict=False)) for row in result.fetchall()]
        except (duckdb.IOException, duckdb.BinderException) as exc:
            label = method or "query"
            logger.warning("[duckdb] %s failed: %s", label, exc)
            return []
        except duckdb.InvalidInputException as exc:
            label = method or "query"
            logger.error("[duckdb] %s invalid input: %s", label, exc)
            return []
        except duckdb.Error as exc:
            # Don't swallow ValueError (blocked columns, SELECT-only)
            if isinstance(exc, ValueError):
                raise
            label = method or "query"
            logger.error("[duckdb] %s error: %s", label, exc)
            return []
        finally:
            conn.close()

    # ── Sync query methods ────────────────────────────────────────

    def stale_embeddings(
        self,
        org_id: uuid.UUID,
        vertical: str,
        current_model: str,
        expected_dim: int,
    ) -> list[StaleEmbeddingResult]:
        """Documents with embedding_model different from current_model."""
        sql = """
            SELECT doc_id, COUNT(*) as chunk_count, embedding_model
            FROM read_parquet(?, union_by_name = true)
            WHERE organization_id = ? AND embedding_model != ?
            GROUP BY doc_id, embedding_model
            LIMIT 10000
        """
        rows = self._execute(
            sql,
            org_id,
            [self._parquet_glob(org_id, vertical), str(org_id), current_model],
            method="stale_embeddings",
        )
        return [
            StaleEmbeddingResult(
                doc_id=r["doc_id"],
                chunk_count=r["chunk_count"],
                embedding_model=r["embedding_model"],
            )
            for r in rows
        ]

    def document_coverage(
        self,
        org_id: uuid.UUID,
        vertical: str,
    ) -> list[DocumentCoverageResult]:
        """Per-document coverage stats."""
        sql = """
            SELECT doc_id, doc_type, COUNT(*) as chunk_count,
                   SUM(char_count) as total_chars,
                   BOOL_OR(embedding_dim IS NOT NULL AND embedding_dim > 0) as has_embeddings
            FROM read_parquet(?, union_by_name = true)
            WHERE organization_id = ?
            GROUP BY doc_id, doc_type
            LIMIT 10000
        """
        rows = self._execute(
            sql,
            org_id,
            [self._parquet_glob(org_id, vertical), str(org_id)],
            method="document_coverage",
        )
        return [
            DocumentCoverageResult(
                doc_id=r["doc_id"],
                doc_type=r["doc_type"],
                chunk_count=r["chunk_count"],
                total_chars=r["total_chars"],
                has_embeddings=bool(r["has_embeddings"]),
            )
            for r in rows
        ]

    def extraction_quality(
        self,
        org_id: uuid.UUID,
        vertical: str,
        min_chars: int = 50,
    ) -> list[ExtractionQualityResult]:
        """Per-document extraction quality metrics."""
        sql = """
            SELECT doc_id, doc_type, COUNT(*) as total_chunks,
                   SUM(CASE WHEN char_count < ? THEN 1 ELSE 0 END) as empty_chunks,
                   SUM(CASE WHEN governance_critical THEN 1 ELSE 0 END) as governance_flagged,
                   AVG(char_count) as avg_char_count
            FROM read_parquet(?, union_by_name = true)
            WHERE organization_id = ?
            GROUP BY doc_id, doc_type
            LIMIT 10000
        """
        rows = self._execute(
            sql,
            org_id,
            [min_chars, self._parquet_glob(org_id, vertical), str(org_id)],
            method="extraction_quality",
        )
        return [
            ExtractionQualityResult(
                doc_id=r["doc_id"],
                doc_type=r["doc_type"],
                total_chunks=r["total_chunks"],
                empty_chunks=r["empty_chunks"],
                governance_flagged=r["governance_flagged"],
                avg_char_count=float(r["avg_char_count"]),
            )
            for r in rows
        ]

    def chunk_stats(
        self,
        org_id: uuid.UUID,
        vertical: str,
    ) -> ChunkStatsResult:
        """Aggregate chunk statistics for a tenant's vertical."""
        glob = self._parquet_glob(org_id, vertical)

        # Query A: aggregates
        sql_a = """
            SELECT COUNT(*) as total_chunks, COUNT(DISTINCT doc_id) as total_documents,
                   SUM(char_count) as total_chars, AVG(char_count) as avg_chunk_chars,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY char_count) as median_chunk_chars,
                   PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY char_count) as p95_chunk_chars
            FROM read_parquet(?, union_by_name = true)
            WHERE organization_id = ?
        """
        rows_a = self._execute(
            sql_a, org_id, [glob, str(org_id)], method="chunk_stats.aggregates",
        )

        # Query B: doc_type distribution
        sql_b = """
            SELECT doc_type, COUNT(*) as cnt
            FROM read_parquet(?, union_by_name = true)
            WHERE organization_id = ?
            GROUP BY doc_type
        """
        rows_b = self._execute(
            sql_b, org_id, [glob, str(org_id)], method="chunk_stats.distribution",
        )

        if not rows_a:
            return ChunkStatsResult(
                total_chunks=0,
                total_documents=0,
                total_chars=0,
                avg_chunk_chars=0.0,
                median_chunk_chars=0.0,
                p95_chunk_chars=0.0,
                doc_type_distribution={},
            )

        row = rows_a[0]
        return ChunkStatsResult(
            total_chunks=row["total_chunks"],
            total_documents=row["total_documents"],
            total_chars=row["total_chars"],
            avg_chunk_chars=float(row["avg_chunk_chars"]),
            median_chunk_chars=float(row["median_chunk_chars"]),
            p95_chunk_chars=float(row["p95_chunk_chars"]),
            doc_type_distribution={r["doc_type"]: r["cnt"] for r in rows_b},
        )

    def embedding_dimension_audit(
        self,
        org_id: uuid.UUID,
        vertical: str,
        expected_dim: int,
    ) -> list[DimensionMismatchResult]:
        """Documents with embedding_dim different from expected."""
        sql = """
            SELECT doc_id, COUNT(*) as chunk_count, embedding_dim
            FROM read_parquet(?, union_by_name = true)
            WHERE organization_id = ? AND embedding_dim != ?
            GROUP BY doc_id, embedding_dim
            LIMIT 10000
        """
        rows = self._execute(
            sql,
            org_id,
            [self._parquet_glob(org_id, vertical), str(org_id), expected_dim],
            method="embedding_dimension_audit",
        )
        return [
            DimensionMismatchResult(
                doc_id=r["doc_id"],
                chunk_count=r["chunk_count"],
                embedding_dim=r["embedding_dim"],
            )
            for r in rows
        ]

    # ── Async wrappers ────────────────────────────────────────────

    async def async_stale_embeddings(
        self,
        org_id: uuid.UUID,
        vertical: str,
        current_model: str,
        expected_dim: int,
    ) -> list[StaleEmbeddingResult]:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(2)
        async with self._semaphore:
            return await asyncio.to_thread(
                self.stale_embeddings, org_id, vertical, current_model, expected_dim,
            )

    async def async_document_coverage(
        self,
        org_id: uuid.UUID,
        vertical: str,
    ) -> list[DocumentCoverageResult]:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(2)
        async with self._semaphore:
            return await asyncio.to_thread(self.document_coverage, org_id, vertical)

    async def async_extraction_quality(
        self,
        org_id: uuid.UUID,
        vertical: str,
        min_chars: int = 50,
    ) -> list[ExtractionQualityResult]:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(2)
        async with self._semaphore:
            return await asyncio.to_thread(
                self.extraction_quality, org_id, vertical, min_chars,
            )

    async def async_chunk_stats(
        self,
        org_id: uuid.UUID,
        vertical: str,
    ) -> ChunkStatsResult:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(2)
        async with self._semaphore:
            return await asyncio.to_thread(self.chunk_stats, org_id, vertical)

    async def async_embedding_dimension_audit(
        self,
        org_id: uuid.UUID,
        vertical: str,
        expected_dim: int,
    ) -> list[DimensionMismatchResult]:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(2)
        async with self._semaphore:
            return await asyncio.to_thread(
                self.embedding_dimension_audit, org_id, vertical, expected_dim,
            )


# ── Singleton ─────────────────────────────────────────────────────

_client: DuckDBClient | None = None


def get_duckdb_client() -> DuckDBClient:
    """Singleton accessor for DuckDBClient."""
    global _client  # noqa: PLW0603
    if _client is None:
        _client = DuckDBClient(get_storage_client())
    return _client

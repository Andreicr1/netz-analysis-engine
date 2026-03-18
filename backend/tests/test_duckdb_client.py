"""Tests for DuckDBClient — uses in-memory Parquet fixtures on disk."""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.services.duckdb_client import DuckDBClient
from app.services.storage_client import LocalStorageClient


def _make_parquet_bytes(
    org_id: str,
    doc_id: str = "doc1",
    embedding_model: str = "text-embedding-3-large",
    embedding_dim: int = 3072,
) -> bytes:
    """Build a minimal silver Parquet fixture."""
    table = pa.table({
        "doc_id": pa.array([doc_id, doc_id], type=pa.string()),
        "chunk_index": pa.array([0, 1], type=pa.int32()),
        "char_count": pa.array([100, 200], type=pa.int32()),
        "doc_type": pa.array(["CRI", "CRI"], type=pa.string()),
        "vehicle_type": pa.array(["CRI", "CRI"], type=pa.string()),
        "embedding_model": pa.array([embedding_model, embedding_model], type=pa.string()),
        "embedding_dim": pa.array([embedding_dim, embedding_dim], type=pa.int32()),
        "organization_id": pa.array([org_id, org_id], type=pa.string()),
    })
    buf = pa.BufferOutputStream()
    pq.write_table(table, buf)
    return buf.getvalue().to_pybytes()


@pytest.fixture()
def duckdb_env():
    """Create a temp directory with silver Parquet files and return (client, org_id)."""
    org_id = uuid.uuid4()
    org_str = str(org_id)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Build silver/org_id/credit/chunks/doc1/chunks.parquet
        chunks_dir = Path(tmpdir) / "silver" / org_str / "credit" / "chunks" / "doc1"
        chunks_dir.mkdir(parents=True)
        parquet_path = chunks_dir / "chunks.parquet"
        parquet_path.write_bytes(_make_parquet_bytes(org_str, "doc1"))

        # Second doc with fewer chunks (1 chunk)
        chunks_dir2 = Path(tmpdir) / "silver" / org_str / "credit" / "chunks" / "doc2"
        chunks_dir2.mkdir(parents=True)
        table_single = pa.table({
            "doc_id": pa.array(["doc2"], type=pa.string()),
            "chunk_index": pa.array([0], type=pa.int32()),
            "char_count": pa.array([50], type=pa.int32()),
            "doc_type": pa.array(["LPA"], type=pa.string()),
            "vehicle_type": pa.array(["FIP"], type=pa.string()),
            "embedding_model": pa.array(["text-embedding-3-large"], type=pa.string()),
            "embedding_dim": pa.array([3072], type=pa.int32()),
            "organization_id": pa.array([org_str], type=pa.string()),
        })
        buf = pa.BufferOutputStream()
        pq.write_table(table_single, buf)
        (chunks_dir2 / "chunks.parquet").write_bytes(buf.getvalue().to_pybytes())

        storage = LocalStorageClient(root=tmpdir)
        client = DuckDBClient(storage)
        yield client, org_id


class TestChunkStats:
    def test_returns_rows(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        result = client.chunk_stats(org_id, "credit")
        assert len(result) == 2
        doc_ids = {r["doc_id"] for r in result}
        assert doc_ids == {"doc1", "doc2"}
        # doc1 has 2 chunks
        doc1 = next(r for r in result if r["doc_id"] == "doc1")
        assert doc1["chunk_count"] == 2


class TestSelectOnlyEnforcement:
    def test_update_rejected(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        with pytest.raises(ValueError, match="only supports SELECT"):
            client._execute("UPDATE foo SET x = 1", org_id)

    def test_insert_rejected(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        with pytest.raises(ValueError, match="only supports SELECT"):
            client._execute("INSERT INTO foo VALUES (1)", org_id)

    def test_delete_rejected(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        with pytest.raises(ValueError, match="only supports SELECT"):
            client._execute("DELETE FROM foo", org_id)


class TestBlockedColumns:
    def test_content_blocked(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        with pytest.raises(ValueError, match="blocked"):
            client._execute("SELECT content FROM foo WHERE organization_id = ?", org_id, [str(org_id)])

    def test_embedding_blocked(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        with pytest.raises(ValueError, match="blocked"):
            client._execute("SELECT embedding FROM foo WHERE organization_id = ?", org_id, [str(org_id)])


class TestStaleEmbeddings:
    def test_empty_when_current(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        result = client.stale_embeddings(org_id, "credit", "text-embedding-3-large")
        assert result == []

    def test_detects_stale(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        result = client.stale_embeddings(org_id, "credit", "text-embedding-4-large")
        assert len(result) == 2  # both doc1 and doc2 are stale


class TestCoverageGaps:
    def test_finds_gaps(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        result = client.coverage_gaps(org_id, "credit", min_chunks=2)
        assert len(result) == 1
        assert result[0]["doc_id"] == "doc2"
        assert result[0]["chunk_count"] == 1


class TestEmbeddingDimCheck:
    def test_consistent_dims(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        result = client.embedding_dim_check(org_id, "credit")
        assert len(result) == 1
        assert result[0]["embedding_dim"] == 3072


class TestDocTypeDistribution:
    def test_returns_distribution(self, duckdb_env: tuple[DuckDBClient, uuid.UUID]) -> None:
        client, org_id = duckdb_env
        result = client.doc_type_distribution(org_id, "credit")
        assert len(result) == 2
        types = {r["doc_type"] for r in result}
        assert types == {"CRI", "LPA"}

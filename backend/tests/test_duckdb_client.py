"""Tests for DuckDBClient — uses real Parquet fixtures on disk (integration tests)."""
from __future__ import annotations

import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from app.services.duckdb_client import (
    ChunkStatsResult,
    DuckDBClient,
    get_duckdb_client,
)
from app.services.storage_client import LocalStorageClient

# ── Helpers ───────────────────────────────────────────────────────


def _make_test_parquet(
    base_path: Path,
    org_id: str,
    doc_id: str,
    *,
    vertical: str = "credit",
    doc_type: str = "legal_lpa",
    vehicle_type: str = "standalone_fund",
    num_chunks: int = 2,
    char_counts: list[int] | None = None,
    embedding_model: str = "text-embedding-3-large",
    embedding_dim: int = 3072,
    governance_critical: list[bool] | None = None,
    include_org_id: bool = True,
) -> Path:
    """Create an 18-column Parquet file at the expected silver path."""
    if char_counts is None:
        char_counts = [100] * num_chunks
    if governance_critical is None:
        governance_critical = [False] * num_chunks
    assert len(char_counts) == num_chunks
    assert len(governance_critical) == num_chunks

    cols: dict[str, pa.Array] = {
        "doc_id": pa.array([doc_id] * num_chunks, type=pa.string()),
        "chunk_index": pa.array(list(range(num_chunks)), type=pa.int32()),
        "content": pa.array([f"chunk {i}" for i in range(num_chunks)], type=pa.string()),
        "page_start": pa.array([1] * num_chunks, type=pa.int32()),
        "page_end": pa.array([2] * num_chunks, type=pa.int32()),
        "section_type": pa.array(["body"] * num_chunks, type=pa.string()),
        "breadcrumb": pa.array([""] * num_chunks, type=pa.string()),
        "has_table": pa.array([False] * num_chunks, type=pa.bool_()),
        "has_numbers": pa.array([False] * num_chunks, type=pa.bool_()),
        "char_count": pa.array(char_counts, type=pa.int32()),
        "doc_type": pa.array([doc_type] * num_chunks, type=pa.string()),
        "vehicle_type": pa.array([vehicle_type] * num_chunks, type=pa.string()),
        "governance_critical": pa.array(governance_critical, type=pa.bool_()),
        "governance_flags": pa.array(["[]"] * num_chunks, type=pa.string()),
        "embedding": pa.array(
            [[0.1] * 3 for _ in range(num_chunks)], type=pa.list_(pa.float32())
        ),
        "embedding_model": pa.array([embedding_model] * num_chunks, type=pa.string()),
        "embedding_dim": pa.array([embedding_dim] * num_chunks, type=pa.int32()),
    }
    if include_org_id:
        cols["organization_id"] = pa.array([org_id] * num_chunks, type=pa.string())

    table = pa.table(cols)
    chunks_dir = base_path / "silver" / org_id / vertical / "chunks" / doc_id
    chunks_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = chunks_dir / "chunks.parquet"
    pq.write_table(table, parquet_path, compression="zstd")
    return parquet_path


# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture()
def setup(tmp_path):
    """Standard fixture with 3 docs: doc-A (3 chunks), doc-B (2 chunks), doc-C (1 chunk)."""
    org_id = str(uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"))

    _make_test_parquet(tmp_path, org_id, "doc-A", num_chunks=3, char_counts=[100, 200, 300])
    _make_test_parquet(
        tmp_path,
        org_id,
        "doc-B",
        num_chunks=2,
        char_counts=[50, 150],
        doc_type="financial_model",
    )
    _make_test_parquet(
        tmp_path,
        org_id,
        "doc-C",
        num_chunks=1,
        char_counts=[10],
        governance_critical=[True],
    )

    storage = LocalStorageClient(root=tmp_path)
    client = DuckDBClient(storage)
    return client, uuid.UUID(org_id)


@pytest.fixture()
def tenant_isolation_setup(tmp_path):
    """Two tenants: org_A and org_B with separate data."""
    org_a = str(uuid.UUID("aaaa0000-0000-0000-0000-000000000001"))
    org_b = str(uuid.UUID("bbbb0000-0000-0000-0000-000000000002"))

    _make_test_parquet(tmp_path, org_a, "doc-alpha", num_chunks=2, char_counts=[100, 200])
    _make_test_parquet(tmp_path, org_b, "doc-beta", num_chunks=3, char_counts=[300, 400, 500])

    storage = LocalStorageClient(root=tmp_path)
    client = DuckDBClient(storage)
    return client, uuid.UUID(org_a), uuid.UUID(org_b)


# ── stale_embeddings ──────────────────────────────────────────────


class TestStaleEmbeddings:
    def test_empty_when_all_current(self, setup):
        client, org_id = setup
        result = client.stale_embeddings(org_id, "credit", "text-embedding-3-large", 3072)
        assert result == []

    def test_detects_stale_model(self, tmp_path):
        org_id = str(uuid.UUID("aaaa0000-0000-0000-0000-000000000099"))
        _make_test_parquet(
            tmp_path, org_id, "doc-old", embedding_model="old-model", num_chunks=2
        )
        storage = LocalStorageClient(root=tmp_path)
        client = DuckDBClient(storage)
        result = client.stale_embeddings(
            uuid.UUID(org_id), "credit", "text-embedding-3-large", 3072
        )
        assert len(result) == 1
        assert result[0].doc_id == "doc-old"
        assert result[0].chunk_count == 2
        assert result[0].embedding_model == "old-model"


# ── document_coverage ─────────────────────────────────────────────


class TestDocumentCoverage:
    def test_returns_correct_stats(self, setup):
        client, org_id = setup
        result = client.document_coverage(org_id, "credit")
        assert len(result) == 3
        by_id = {r.doc_id: r for r in result}

        assert by_id["doc-A"].chunk_count == 3
        assert by_id["doc-A"].total_chars == 600  # 100+200+300
        assert by_id["doc-A"].has_embeddings is True

        assert by_id["doc-B"].chunk_count == 2
        assert by_id["doc-B"].doc_type == "financial_model"

        assert by_id["doc-C"].chunk_count == 1
        assert by_id["doc-C"].total_chars == 10


# ── extraction_quality ────────────────────────────────────────────


class TestExtractionQuality:
    def test_identifies_empty_chunks_and_governance(self, setup):
        client, org_id = setup
        result = client.extraction_quality(org_id, "credit", min_chars=50)
        by_id = {r.doc_id: r for r in result}

        # doc-C has 1 chunk with char_count=10, below min_chars=50
        assert by_id["doc-C"].empty_chunks == 1
        assert by_id["doc-C"].governance_flagged == 1

        # doc-A has no empty chunks (all >= 100) and no governance flags
        assert by_id["doc-A"].empty_chunks == 0
        assert by_id["doc-A"].governance_flagged == 0


# ── chunk_stats ───────────────────────────────────────────────────


class TestChunkStats:
    def test_returns_correct_aggregates(self, setup):
        client, org_id = setup
        result = client.chunk_stats(org_id, "credit")

        assert isinstance(result, ChunkStatsResult)
        # 3 + 2 + 1 = 6 total chunks
        assert result.total_chunks == 6
        assert result.total_documents == 3
        # 100+200+300+50+150+10 = 810
        assert result.total_chars == 810
        assert result.avg_chunk_chars == pytest.approx(135.0)
        assert result.doc_type_distribution["legal_lpa"] == 4  # doc-A(3) + doc-C(1)
        assert result.doc_type_distribution["financial_model"] == 2  # doc-B

    def test_empty_when_no_parquet(self, tmp_path):
        org_id = uuid.uuid4()
        storage = LocalStorageClient(root=tmp_path)
        client = DuckDBClient(storage)
        result = client.chunk_stats(org_id, "credit")
        assert result.total_chunks == 0
        assert result.doc_type_distribution == {}


# ── embedding_dimension_audit ─────────────────────────────────────


class TestEmbeddingDimensionAudit:
    def test_empty_when_all_correct(self, setup):
        client, org_id = setup
        result = client.embedding_dimension_audit(org_id, "credit", expected_dim=3072)
        assert result == []

    def test_detects_wrong_dim(self, tmp_path):
        org_id = str(uuid.UUID("aaaa0000-0000-0000-0000-000000000077"))
        _make_test_parquet(
            tmp_path, org_id, "doc-bad-dim", embedding_dim=1536, num_chunks=3
        )
        storage = LocalStorageClient(root=tmp_path)
        client = DuckDBClient(storage)
        result = client.embedding_dimension_audit(
            uuid.UUID(org_id), "credit", expected_dim=3072
        )
        assert len(result) == 1
        assert result[0].doc_id == "doc-bad-dim"
        assert result[0].chunk_count == 3
        assert result[0].embedding_dim == 1536


# ── Empty/missing Parquet ─────────────────────────────────────────


class TestEmptyParquet:
    def test_all_methods_return_empty_when_no_files(self, tmp_path):
        org_id = uuid.uuid4()
        storage = LocalStorageClient(root=tmp_path)
        client = DuckDBClient(storage)

        assert client.stale_embeddings(org_id, "credit", "model", 3072) == []
        assert client.document_coverage(org_id, "credit") == []
        assert client.extraction_quality(org_id, "credit") == []
        assert client.embedding_dimension_audit(org_id, "credit", 3072) == []

    def test_zero_row_parquet(self, tmp_path):
        """Valid Parquet with schema but zero rows."""
        org_id = str(uuid.uuid4())
        _make_test_parquet(tmp_path, org_id, "doc-empty", num_chunks=0, char_counts=[], governance_critical=[])
        storage = LocalStorageClient(root=tmp_path)
        client = DuckDBClient(storage)
        result = client.document_coverage(uuid.UUID(org_id), "credit")
        assert result == []


# ── Legacy file (no organization_id column) ───────────────────────


class TestLegacyFile:
    def test_legacy_parquet_filtered_by_where(self, tmp_path):
        """Parquet without organization_id column → DuckDB returns empty (IOException or no match)."""
        org_id = str(uuid.uuid4())
        _make_test_parquet(
            tmp_path, org_id, "doc-legacy", num_chunks=2, include_org_id=False
        )
        storage = LocalStorageClient(root=tmp_path)
        client = DuckDBClient(storage)
        # union_by_name=true fills missing cols with NULL, WHERE filters them out
        result = client.document_coverage(uuid.UUID(org_id), "credit")
        assert result == []


# ── Tenant isolation (CRITICAL) ───────────────────────────────────


class TestTenantIsolation:
    def test_org_a_cannot_see_org_b_data(self, tenant_isolation_setup):
        client, org_a, org_b = tenant_isolation_setup

        result_a = client.document_coverage(org_a, "credit")
        result_b = client.document_coverage(org_b, "credit")

        doc_ids_a = {r.doc_id for r in result_a}
        doc_ids_b = {r.doc_id for r in result_b}

        assert doc_ids_a == {"doc-alpha"}
        assert doc_ids_b == {"doc-beta"}
        assert doc_ids_a & doc_ids_b == set()


# ── Singleton ─────────────────────────────────────────────────────


class TestSingleton:
    def test_get_duckdb_client_is_singleton(self):
        import app.services.duckdb_client as mod

        # Reset singleton
        mod._client = None
        a = get_duckdb_client()
        b = get_duckdb_client()
        assert a is b
        # Clean up
        mod._client = None


# ── SELECT-only enforcement ───────────────────────────────────────


class TestSelectOnly:
    def test_update_rejected(self, setup):
        client, org_id = setup
        with pytest.raises(ValueError, match="only supports SELECT"):
            client._execute("UPDATE foo SET x = 1", org_id)

    def test_insert_rejected(self, setup):
        client, org_id = setup
        with pytest.raises(ValueError, match="only supports SELECT"):
            client._execute("INSERT INTO foo VALUES (1)", org_id)

    def test_delete_rejected(self, setup):
        client, org_id = setup
        with pytest.raises(ValueError, match="only supports SELECT"):
            client._execute("DELETE FROM foo", org_id)


# ── Blocked columns ──────────────────────────────────────────────


class TestBlockedColumns:
    def test_blocked_column_in_result_raises(self, setup):
        """Blocked columns checked on result set, not SQL text."""
        client, org_id = setup
        glob = client._parquet_glob(org_id, "credit")
        sql = f"SELECT doc_id, content FROM read_parquet('{glob}', union_by_name = true) WHERE organization_id = ? LIMIT 1"
        with pytest.raises(ValueError, match="Blocked column"):
            client._execute(sql, org_id, [str(org_id)])


# ── UUID validation ───────────────────────────────────────────────


class TestUUIDValidation:
    def test_path_traversal_org_id_rejected(self, tmp_path):
        """Path traversal via org_id is rejected by _validate_segment."""
        storage = LocalStorageClient(root=tmp_path)
        client = DuckDBClient(storage)
        with pytest.raises(ValueError):
            client._storage.get_duckdb_path("silver", "../evil", "credit")

    def test_path_traversal_vertical_rejected(self, tmp_path):
        """Invalid vertical is rejected."""
        storage = LocalStorageClient(root=tmp_path)
        client = DuckDBClient(storage)
        with pytest.raises(ValueError):
            client._storage.get_duckdb_path("silver", "org-1", "insurance")

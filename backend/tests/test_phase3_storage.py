"""Tests for Phase 3 — StorageClient integration, path routing, search rebuild."""
from __future__ import annotations

import json
import uuid

import pytest

# ── storage_routing tests ──────────────────────────────────────────


class TestStorageRouting:
    """Test path routing functions from pipeline/storage_routing.py."""

    def _org_id(self) -> uuid.UUID:
        return uuid.UUID("00000000-1111-2222-3333-444444444444")

    def test_bronze_document_path(self):
        from ai_engine.pipeline.storage_routing import bronze_document_path
        path = bronze_document_path(self._org_id(), "credit", "doc-123")
        assert path == "bronze/00000000-1111-2222-3333-444444444444/credit/documents/doc-123.json"

    def test_silver_chunks_path(self):
        from ai_engine.pipeline.storage_routing import silver_chunks_path
        path = silver_chunks_path(self._org_id(), "wealth", "doc-456")
        assert path == "silver/00000000-1111-2222-3333-444444444444/wealth/chunks/doc-456/chunks.parquet"

    def test_silver_metadata_path(self):
        from ai_engine.pipeline.storage_routing import silver_metadata_path
        path = silver_metadata_path(self._org_id(), "credit", "doc-789")
        assert path == "silver/00000000-1111-2222-3333-444444444444/credit/documents/doc-789/metadata.json"

    def test_gold_memo_path(self):
        from ai_engine.pipeline.storage_routing import gold_memo_path
        path = gold_memo_path(self._org_id(), "credit", "memo-001")
        assert path == "gold/00000000-1111-2222-3333-444444444444/credit/memos/memo-001.json"

    def test_global_reference_path(self):
        from ai_engine.pipeline.storage_routing import global_reference_path
        path = global_reference_path("fred_indicators", "gdp.parquet")
        assert path == "gold/_global/fred_indicators/gdp.parquet"

    def test_invalid_vertical_raises(self):
        from ai_engine.pipeline.storage_routing import bronze_document_path
        with pytest.raises(ValueError, match="Invalid vertical"):
            bronze_document_path(self._org_id(), "insurance", "doc-1")

    def test_empty_doc_id_raises(self):
        from ai_engine.pipeline.storage_routing import bronze_document_path
        with pytest.raises(ValueError, match="must not be empty"):
            bronze_document_path(self._org_id(), "credit", "")

    def test_traversal_doc_id_raises(self):
        from ai_engine.pipeline.storage_routing import bronze_document_path
        with pytest.raises(ValueError, match="Invalid doc_id"):
            bronze_document_path(self._org_id(), "credit", "../etc/passwd")

    def test_special_chars_doc_id_raises(self):
        from ai_engine.pipeline.storage_routing import silver_chunks_path
        with pytest.raises(ValueError, match="Invalid doc_id"):
            silver_chunks_path(self._org_id(), "credit", "doc id with spaces")

    def test_global_path_traversal_raises(self):
        from ai_engine.pipeline.storage_routing import global_reference_path
        with pytest.raises(ValueError, match="Invalid dataset"):
            global_reference_path("../secret", "data.csv")


# ── build_search_document organization_id tests ───────────────────


class TestSearchDocumentOrgId:
    """Test that build_search_document includes organization_id (F4 fix)."""

    def test_organization_id_included(self):
        from ai_engine.extraction.search_upsert_service import build_search_document
        org_id = uuid.uuid4()
        doc = build_search_document(
            deal_id=uuid.uuid4(),
            fund_id=uuid.uuid4(),
            domain="credit",
            doc_type="legal_lpa",
            authority="test",
            title="test.pdf",
            chunk_index=0,
            content="test content",
            embedding=[0.1] * 10,
            page_start=1,
            page_end=1,
            organization_id=org_id,
        )
        assert doc["organization_id"] == str(org_id)

    def test_organization_id_omitted_when_none(self):
        from ai_engine.extraction.search_upsert_service import build_search_document
        doc = build_search_document(
            deal_id=uuid.uuid4(),
            fund_id=uuid.uuid4(),
            domain="credit",
            doc_type="legal_lpa",
            authority="test",
            title="test.pdf",
            chunk_index=0,
            content="test content",
            embedding=[0.1] * 10,
            page_start=1,
            page_end=1,
        )
        assert "organization_id" not in doc


# ── Parquet serialization tests ────────────────────────────────────


class TestChunksParquet:
    """Test _build_chunks_parquet from unified_pipeline.py."""

    def test_round_trip(self):
        import io

        import pyarrow.parquet as pq

        from ai_engine.pipeline.unified_pipeline import _build_chunks_parquet

        chunks = [
            {
                "chunk_index": 0,
                "content": "Section 1 content",
                "page_start": 1,
                "page_end": 2,
                "section_type": "body",
                "breadcrumb": "Part I > Section 1",
                "has_table": True,
                "has_numbers": False,
                "char_count": 17,
                "doc_type": "legal_lpa",
                "vehicle_type": "standalone_fund",
                "embedding": [0.1, 0.2, 0.3],
            },
            {
                "chunk_index": 1,
                "content": "Section 2 content",
                "page_start": 3,
                "page_end": 4,
                "section_type": "appendix",
                "breadcrumb": "Part II",
                "has_table": False,
                "has_numbers": True,
                "char_count": 17,
                "doc_type": "legal_lpa",
                "vehicle_type": "standalone_fund",
                "embedding": [0.4, 0.5, 0.6],
            },
        ]

        parquet_bytes = _build_chunks_parquet(chunks, "doc-test-123", "org-abc-123")
        assert isinstance(parquet_bytes, bytes)
        assert len(parquet_bytes) > 0

        # Read back and verify
        table = pq.read_table(io.BytesIO(parquet_bytes))
        assert len(table) == 2
        assert set(table.column_names) >= {
            "doc_id", "chunk_index", "content", "embedding",
            "embedding_model", "embedding_dim", "doc_type", "vehicle_type",
            "organization_id",
        }

        # Verify data
        assert table.column("doc_id")[0].as_py() == "doc-test-123"
        assert table.column("chunk_index")[0].as_py() == 0
        assert table.column("content")[0].as_py() == "Section 1 content"
        assert table.column("has_table")[0].as_py() is True
        assert table.column("doc_type")[0].as_py() == "legal_lpa"
        assert table.column("vehicle_type")[0].as_py() == "standalone_fund"
        assert table.column("embedding")[0].as_py() == pytest.approx([0.1, 0.2, 0.3])
        assert table.column("embedding_model")[0].as_py() == "text-embedding-3-large"
        assert table.column("embedding_dim")[0].as_py() == 3072
        assert table.column("organization_id")[0].as_py() == "org-abc-123"

    def test_empty_chunks(self):
        from ai_engine.pipeline.unified_pipeline import _build_chunks_parquet
        parquet_bytes = _build_chunks_parquet([], "doc-empty", "org-abc-123")
        assert isinstance(parquet_bytes, bytes)


# ── write_to_lake tests ────────────────────────────────────────────


class TestWriteToLake:
    """Test _write_to_lake with LocalStorageClient."""

    @pytest.mark.asyncio
    async def test_write_and_read_back(self, tmp_path):
        from app.services.storage_client import LocalStorageClient

        client = LocalStorageClient(root=tmp_path)

        # Write directly via client
        path = "bronze/test-org/credit/documents/test-doc.json"
        payload = json.dumps({"test": True}).encode()
        await client.write(path, payload, content_type="application/json")

        # Read back
        data = await client.read(path)
        assert json.loads(data) == {"test": True}

    @pytest.mark.asyncio
    async def test_write_creates_directories(self, tmp_path):
        from app.services.storage_client import LocalStorageClient

        client = LocalStorageClient(root=tmp_path)
        path = "silver/org-1/wealth/chunks/doc-1/chunks.parquet"
        await client.write(path, b"fake-parquet-data")

        assert await client.exists(path)


# ── Search rebuild tests ───────────────────────────────────────────


class TestSearchRebuildValidation:
    """Test search rebuild embedding dimension validation."""

    def _make_parquet(self, embedding_dim: int, embedding_values: list[float] | None = None) -> bytes:
        """Helper to create a test parquet file."""
        import pyarrow as pa
        import pyarrow.parquet as pq

        emb = embedding_values if embedding_values is not None else [0.1] * 2
        table = pa.table({
            "doc_id": ["doc-1"],
            "chunk_index": [0],
            "content": ["test"],
            "page_start": [1],
            "page_end": [1],
            "section_type": ["body"],
            "breadcrumb": [""],
            "has_table": [False],
            "has_numbers": [False],
            "char_count": [4],
            "doc_type": ["legal_lpa"],
            "vehicle_type": ["standalone_fund"],
            "embedding": [emb],
            "embedding_model": ["text-embedding-3-large"],
            "embedding_dim": [embedding_dim],
        })
        buf = pa.BufferOutputStream()
        pq.write_table(table, buf)
        return buf.getvalue().to_pybytes()

    def test_rejects_mismatched_embedding_dim(self):
        from ai_engine.pipeline.search_rebuild import _rebuild_single_document

        parquet_bytes = self._make_parquet(embedding_dim=1536)

        with pytest.raises(ValueError, match="Embedding dimension mismatch"):
            _rebuild_single_document(
                parquet_bytes=parquet_bytes,
                doc_id_str="00000000-0000-0000-0000-000000000001",
                org_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                vertical="credit",
                deal_id=None,
                fund_id=None,
            )

    def test_accepts_correct_embedding_dim(self):
        """Verify files with correct dim pass validation, then upsert is called."""
        from unittest.mock import MagicMock, patch

        from ai_engine.pipeline.search_rebuild import _rebuild_single_document
        from ai_engine.validation.vector_integrity_guard import EMBEDDING_DIMENSIONS

        parquet_bytes = self._make_parquet(
            embedding_dim=EMBEDDING_DIMENSIONS,
            embedding_values=[0.1] * EMBEDDING_DIMENSIONS,
        )

        from ai_engine.extraction.pgvector_search_service import UpsertResult

        mock_result = UpsertResult(
            attempted_chunk_count=1,
            successful_chunk_count=1,
            failed_chunk_count=0,
            retryable=False,
        )
        mock_upsert = MagicMock(return_value=mock_result)

        with patch(
            "ai_engine.extraction.pgvector_search_service.upsert_chunks_sync",
            mock_upsert,
        ):
            count = _rebuild_single_document(
                parquet_bytes=parquet_bytes,
                doc_id_str="00000000-0000-0000-0000-000000000001",
                org_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
                vertical="credit",
                deal_id=None,
                fund_id=None,
            )
            assert count == 1
            mock_upsert.assert_called_once()

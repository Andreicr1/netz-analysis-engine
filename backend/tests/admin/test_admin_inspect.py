"""Tests for admin data lake inspection endpoints."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.duckdb_client import (
    ChunkStatsResult,
    DimensionMismatchResult,
    DocumentCoverageResult,
    DuckDBClient,
    ExtractionQualityResult,
    StaleEmbeddingResult,
)

ORG_ID = "00000000-0000-0000-0000-000000000001"
ORG_UUID = uuid.UUID(ORG_ID)

SUPER_ADMIN_HEADER = {
    "X-DEV-ACTOR": json.dumps(
        {
            "actor_id": "super-admin-user",
            "roles": ["SUPER_ADMIN"],
            "fund_ids": [],
            "org_id": ORG_ID,
        },
    ),
}

REGULAR_ADMIN_HEADER = {
    "X-DEV-ACTOR": json.dumps(
        {
            "actor_id": "regular-user",
            "roles": ["ADMIN"],
            "fund_ids": [],
            "org_id": ORG_ID,
        },
    ),
}

BASE = f"/api/v1/admin/inspect/{ORG_ID}/credit"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _mock_client() -> DuckDBClient:
    """Build a mock DuckDBClient with async methods returning sample data."""
    mock = AsyncMock(spec=DuckDBClient)

    mock.async_stale_embeddings.return_value = [
        StaleEmbeddingResult(doc_id="doc-1", chunk_count=5, embedding_model="old-model"),
    ]
    mock.async_document_coverage.return_value = [
        DocumentCoverageResult(doc_id="doc-1", doc_type="cim", chunk_count=10, total_chars=5000, has_embeddings=True),
    ]
    mock.async_extraction_quality.return_value = [
        ExtractionQualityResult(doc_id="doc-1", doc_type="cim", total_chunks=10, empty_chunks=1, governance_flagged=0, avg_char_count=500.0),
    ]
    mock.async_chunk_stats.return_value = ChunkStatsResult(
        total_chunks=100,
        total_documents=10,
        total_chars=50000,
        avg_chunk_chars=500.0,
        median_chunk_chars=480.0,
        p95_chunk_chars=950.0,
        doc_type_distribution={"cim": 60, "financial_statement": 40},
    )
    mock.async_embedding_dimension_audit.return_value = [
        DimensionMismatchResult(doc_id="doc-2", chunk_count=3, embedding_dim=1536),
    ]
    return mock


@pytest.mark.asyncio
class TestStaleEmbeddings:
    async def test_returns_results(self, client: AsyncClient):
        mock = _mock_client()
        with patch("app.domains.admin.routes.inspect.get_duckdb_client", return_value=mock):
            resp = await client.get(f"{BASE}/stale-embeddings", headers=SUPER_ADMIN_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["doc_id"] == "doc-1"
        assert data["org_id"] == ORG_ID
        assert data["vertical"] == "credit"

    async def test_custom_query_params(self, client: AsyncClient):
        mock = _mock_client()
        with patch("app.domains.admin.routes.inspect.get_duckdb_client", return_value=mock):
            resp = await client.get(
                f"{BASE}/stale-embeddings?current_model=custom&expected_dim=1536",
                headers=SUPER_ADMIN_HEADER,
            )
        assert resp.status_code == 200
        mock.async_stale_embeddings.assert_called_once_with(ORG_UUID, "credit", "custom", 1536)


@pytest.mark.asyncio
class TestDocumentCoverage:
    async def test_returns_results(self, client: AsyncClient):
        mock = _mock_client()
        with patch("app.domains.admin.routes.inspect.get_duckdb_client", return_value=mock):
            resp = await client.get(f"{BASE}/coverage", headers=SUPER_ADMIN_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["has_embeddings"] is True


@pytest.mark.asyncio
class TestExtractionQuality:
    async def test_returns_results(self, client: AsyncClient):
        mock = _mock_client()
        with patch("app.domains.admin.routes.inspect.get_duckdb_client", return_value=mock):
            resp = await client.get(f"{BASE}/extraction-quality?min_chars=100", headers=SUPER_ADMIN_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        mock.async_extraction_quality.assert_called_once_with(ORG_UUID, "credit", 100)


@pytest.mark.asyncio
class TestChunkStats:
    async def test_returns_single_result(self, client: AsyncClient):
        mock = _mock_client()
        with patch("app.domains.admin.routes.inspect.get_duckdb_client", return_value=mock):
            resp = await client.get(f"{BASE}/chunk-stats", headers=SUPER_ADMIN_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_chunks"] == 100
        assert data["doc_type_distribution"]["cim"] == 60
        assert data["org_id"] == ORG_ID


@pytest.mark.asyncio
class TestEmbeddingAudit:
    async def test_returns_results(self, client: AsyncClient):
        mock = _mock_client()
        with patch("app.domains.admin.routes.inspect.get_duckdb_client", return_value=mock):
            resp = await client.get(f"{BASE}/embedding-audit?expected_dim=3072", headers=SUPER_ADMIN_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["embedding_dim"] == 1536


@pytest.mark.asyncio
class TestAuthAndValidation:
    async def test_403_for_non_admin(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/coverage", headers=REGULAR_ADMIN_HEADER)
        assert resp.status_code == 403

    async def test_400_for_invalid_vertical(self, client: AsyncClient):
        mock = _mock_client()
        with patch("app.domains.admin.routes.inspect.get_duckdb_client", return_value=mock):
            resp = await client.get(
                f"/api/v1/admin/inspect/{ORG_ID}/invalid_vertical/coverage",
                headers=SUPER_ADMIN_HEADER,
            )
        assert resp.status_code == 400
        assert "invalid_vertical" in resp.json()["detail"].lower()

    async def test_504_on_timeout(self, client: AsyncClient):
        mock = _mock_client()
        mock.async_document_coverage.side_effect = TimeoutError()
        with patch("app.domains.admin.routes.inspect.get_duckdb_client", return_value=mock):
            # Patch wait_for to raise TimeoutError immediately
            resp = await client.get(f"{BASE}/coverage", headers=SUPER_ADMIN_HEADER)
        assert resp.status_code == 504

    async def test_422_for_invalid_uuid(self, client: AsyncClient):
        resp = await client.get(
            "/api/v1/admin/inspect/not-a-uuid/credit/coverage",
            headers=SUPER_ADMIN_HEADER,
        )
        assert resp.status_code == 422

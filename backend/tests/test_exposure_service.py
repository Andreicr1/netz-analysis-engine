"""Tests for the Exposure Monitor service and endpoints.

Tests exercise both the service layer (via ASGI client) and verify
empty-state behavior, never-raises guarantees, and response shape.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import DEV_ACTOR_HEADER


class TestExposureMatrixEndpoint:
    """GET /wealth/exposure/matrix — real DB queries."""

    @pytest.mark.asyncio
    async def test_matrix_returns_200_with_shape(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/wealth/exposure/matrix?dimension=geographic&aggregation=portfolio",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "rows" in data
        assert "columns" in data
        assert "data" in data
        assert "is_empty" in data
        assert "as_of" in data
        assert isinstance(data["rows"], list)
        assert isinstance(data["columns"], list)
        assert isinstance(data["data"], list)
        assert isinstance(data["is_empty"], bool)

    @pytest.mark.asyncio
    async def test_matrix_sector_dimension(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/wealth/exposure/matrix?dimension=sector&aggregation=portfolio",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["dimension"] == "sector"
        assert data["aggregation"] == "portfolio"

    @pytest.mark.asyncio
    async def test_matrix_manager_aggregation(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/wealth/exposure/matrix?dimension=geographic&aggregation=manager",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["aggregation"] == "manager"

    @pytest.mark.asyncio
    async def test_matrix_empty_has_consistent_shape(self, client: AsyncClient) -> None:
        """Even when empty, rows/columns/data must be present and consistent."""
        resp = await client.get(
            "/api/v1/wealth/exposure/matrix?dimension=geographic&aggregation=portfolio",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        if data["is_empty"]:
            assert data["rows"] == []
            assert data["columns"] == []
            assert data["data"] == []
            assert data["as_of"] is None

    @pytest.mark.asyncio
    async def test_matrix_data_rows_match_row_labels(self, client: AsyncClient) -> None:
        """When data exists, len(data) == len(rows) and each row len == len(columns)."""
        resp = await client.get(
            "/api/v1/wealth/exposure/matrix?dimension=geographic&aggregation=portfolio",
            headers=DEV_ACTOR_HEADER,
        )
        data = resp.json()
        if not data["is_empty"]:
            assert len(data["data"]) == len(data["rows"])
            for row in data["data"]:
                assert len(row) == len(data["columns"])

    @pytest.mark.asyncio
    async def test_matrix_rejects_invalid_dimension(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/wealth/exposure/matrix?dimension=invalid&aggregation=portfolio",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_matrix_rejects_invalid_aggregation(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/wealth/exposure/matrix?dimension=geographic&aggregation=invalid",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 422


class TestExposureMetadataEndpoint:
    """GET /wealth/exposure/metadata — snapshot freshness."""

    @pytest.mark.asyncio
    async def test_metadata_returns_200(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/wealth/exposure/metadata",
            headers=DEV_ACTOR_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "as_of" in data
        assert "snapshot_count" in data
        assert "profile_count" in data
        assert isinstance(data["snapshot_count"], int)
        assert isinstance(data["profile_count"], int)

    @pytest.mark.asyncio
    async def test_metadata_counts_non_negative(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/wealth/exposure/metadata",
            headers=DEV_ACTOR_HEADER,
        )
        data = resp.json()
        assert data["snapshot_count"] >= 0
        assert data["profile_count"] >= 0

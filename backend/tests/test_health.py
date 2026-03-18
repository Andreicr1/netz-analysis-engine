"""Tests for health and core endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import DEV_ACTOR_HEADER


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["service"] == "netz-analysis-engine"
    assert data["ai_router_status"] == "degraded"
    assert data["ai_router_degraded_modules"] == ["extraction", "portfolio"]


@pytest.mark.asyncio
async def test_health_api_prefix(client: AsyncClient):
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["ai_router_status"] == "degraded"


@pytest.mark.asyncio
async def test_api_root(client: AsyncClient):
    response = await client.get("/api/v1/", headers=DEV_ACTOR_HEADER)
    assert response.status_code == 200
    data = response.json()
    assert "credit" in data["verticals"]
    assert "wealth" in data["verticals"]


@pytest.mark.asyncio
async def test_unauthenticated_returns_401(client: AsyncClient):
    # SSE endpoint requires auth
    response = await client.get("/api/v1/jobs/test-123/stream")
    assert response.status_code == 401

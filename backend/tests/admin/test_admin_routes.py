"""Tests for admin API routes — auth, config, tenant, prompt, health endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import DEV_ACTOR_HEADER

# Non-admin actor header for permission testing
NON_ADMIN_HEADER = {
    "X-DEV-ACTOR": '{"actor_id": "investor-user", "roles": ["INVESTOR"], "fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}'
}


# ── Config routes ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_list_requires_admin(client: AsyncClient):
    """GET /admin/configs without admin role returns 403."""
    response = await client.get(
        "/api/v1/admin/configs",
        params={"vertical": "liquid_funds"},
        headers=NON_ADMIN_HEADER,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_config_list_as_admin(client: AsyncClient):
    """GET /admin/configs as admin returns config entries."""
    response = await client.get(
        "/api/v1/admin/configs",
        params={"vertical": "liquid_funds"},
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_config_diff_requires_admin(client: AsyncClient):
    """GET /admin/configs/{vertical}/{type}/diff without admin returns 403."""
    response = await client.get(
        "/api/v1/admin/configs/liquid_funds/calibration/diff",
        headers=NON_ADMIN_HEADER,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_config_diff_as_admin(client: AsyncClient):
    """GET /admin/configs/{vertical}/{type}/diff returns diff response."""
    response = await client.get(
        "/api/v1/admin/configs/liquid_funds/calibration/diff",
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert "default" in data
    assert "override" in data
    assert "merged" in data


# ── Tenant routes ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_list_requires_admin(client: AsyncClient):
    """GET /admin/tenants without admin role returns 403."""
    response = await client.get("/api/v1/admin/tenants", headers=NON_ADMIN_HEADER)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_tenant_list_as_admin(client: AsyncClient):
    """GET /admin/tenants as admin returns list."""
    response = await client.get("/api/v1/admin/tenants", headers=DEV_ACTOR_HEADER)
    assert response.status_code == 200
    assert isinstance(response.json(), list)


# ── Prompt routes ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_list_requires_admin(client: AsyncClient):
    """GET /admin/prompts/{vertical} without admin role returns 403."""
    response = await client.get(
        "/api/v1/admin/prompts/private_credit",
        headers=NON_ADMIN_HEADER,
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_prompt_list_as_admin(client: AsyncClient):
    """GET /admin/prompts/{vertical} as admin returns template list."""
    response = await client.get(
        "/api/v1/admin/prompts/private_credit",
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_prompt_validate_valid_template(client: AsyncClient):
    """POST /admin/prompts/{vertical}/{name}/validate returns valid for good template."""
    response = await client.post(
        "/api/v1/admin/prompts/private_credit/test_template/validate",
        json={"content": "Hello {{ name }}"},
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is True
    assert data["errors"] == []


@pytest.mark.asyncio
async def test_prompt_validate_invalid_template(client: AsyncClient):
    """POST /admin/prompts/{vertical}/{name}/validate returns errors for bad template."""
    response = await client.post(
        "/api/v1/admin/prompts/private_credit/test_template/validate",
        json={"content": "Hello {{ name }"},
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False
    assert len(data["errors"]) > 0


@pytest.mark.asyncio
async def test_prompt_validate_blocks_ssti(client: AsyncClient):
    """POST /admin/prompts/.../validate blocks SSTI patterns."""
    response = await client.post(
        "/api/v1/admin/prompts/private_credit/test_template/validate",
        json={"content": "{{ config.__class__.__mro__ }}"},
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["valid"] is False


@pytest.mark.asyncio
async def test_prompt_preview(client: AsyncClient):
    """POST /admin/prompts/{vertical}/{name}/preview renders with sample data."""
    response = await client.post(
        "/api/v1/admin/prompts/private_credit/test_template/preview",
        json={
            "content": "Hello {{ name }}, your deal {{ deal }} is ready.",
            "sample_data": {"name": "Alice", "deal": "ABC Corp"},
        },
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert "Alice" in data["rendered"]
    assert "ABC Corp" in data["rendered"]


# ── Health routes ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_health_workers_requires_admin(client: AsyncClient):
    """GET /admin/health/workers without admin role returns 403."""
    response = await client.get("/api/v1/admin/health/workers", headers=NON_ADMIN_HEADER)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_health_workers_as_admin(client: AsyncClient):
    """GET /admin/health/workers returns worker status list."""
    response = await client.get("/api/v1/admin/health/workers", headers=DEV_ACTOR_HEADER)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    if len(data) > 0:
        assert "name" in data[0]
        assert "status" in data[0]


@pytest.mark.asyncio
async def test_health_pipelines_as_admin(client: AsyncClient):
    """GET /admin/health/pipelines returns pipeline stats."""
    response = await client.get("/api/v1/admin/health/pipelines", headers=DEV_ACTOR_HEADER)
    assert response.status_code == 200
    data = response.json()
    assert "documents_processed" in data
    assert "queue_depth" in data


@pytest.mark.asyncio
async def test_health_usage_as_admin(client: AsyncClient):
    """GET /admin/health/usage returns usage list."""
    response = await client.get("/api/v1/admin/health/usage", headers=DEV_ACTOR_HEADER)
    assert response.status_code == 200
    assert isinstance(response.json(), list)

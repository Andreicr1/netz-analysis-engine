"""Tests for admin branding and asset endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import DEV_ACTOR_HEADER


@pytest.mark.asyncio
async def test_get_branding_returns_default(client: AsyncClient):
    """GET /api/v1/branding returns default Netz branding when no override."""
    response = await client.get("/api/v1/branding", headers=DEV_ACTOR_HEADER)
    assert response.status_code == 200
    data = response.json()
    assert data["company_name"] == "Netz Capital"
    assert data["primary_color"] == "#1a1a2e"
    assert "logo_light" in data["logo_light_url"]
    assert "logo_dark" in data["logo_dark_url"]
    assert "favicon" in data["favicon_url"]


@pytest.mark.asyncio
async def test_get_branding_requires_auth(client: AsyncClient):
    """GET /api/v1/branding without auth returns 401."""
    response = await client.get("/api/v1/branding")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_tenant_asset_default_for_unknown_slug(client: AsyncClient):
    """GET /api/v1/assets/tenant/unknown/logo_light returns default asset (not 404)."""
    response = await client.get("/api/v1/assets/tenant/unknown-org/logo_light")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert "nosniff" in response.headers["x-content-type-options"]
    assert "public" in response.headers["cache-control"]
    assert "etag" in response.headers


@pytest.mark.asyncio
async def test_get_tenant_asset_invalid_type_returns_404(client: AsyncClient):
    """GET /api/v1/assets/tenant/{slug}/invalid returns 404."""
    response = await client.get("/api/v1/assets/tenant/some-org/invalid_type")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_tenant_asset_valid_types(client: AsyncClient):
    """All valid asset types return 200 (default fallback)."""
    for asset_type in ("logo_light", "logo_dark", "favicon"):
        response = await client.get(f"/api/v1/assets/tenant/test-org/{asset_type}")
        assert response.status_code == 200, f"Failed for {asset_type}"

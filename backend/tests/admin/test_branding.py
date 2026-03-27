"""Tests for admin branding and asset endpoints."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from httpx import AsyncClient

from app.core.config.dependencies import get_config_service
from app.core.config.schemas import ConfigResult, ConfigResultState
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.admin.routes import assets as assets_routes
from app.main import app
from tests.conftest import DEV_ACTOR_HEADER

SUPER_ADMIN_DEV_ACTOR_HEADER = {
    "X-DEV-ACTOR": json.dumps(
        {
            "actor_id": "super-admin-user",
            "roles": ["SUPER_ADMIN"],
            "fund_ids": [],
            "org_id": "00000000-0000-0000-0000-000000000001",
        },
    ),
}


class _FakeExecuteResult:
    def all(self):
        return []

    def first(self):
        return None


class _FakeSession:
    async def execute(self, *_args, **_kwargs):
        return _FakeExecuteResult()


class _FakeConfigService:
    async def get(self, **_kwargs):
        return ConfigResult(
            value={
                "company_name": "Netz Capital",
                "primary_color": "#1a1a2e",
            },
            state=ConfigResultState.FOUND,
            source="mock",
        )


class _FakeSessionFactory:
    async def __aenter__(self):
        return _FakeSession()

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def _override_admin_branding_dependencies(monkeypatch) -> AsyncIterator[None]:
    async def _fake_db_with_rls():
        yield _FakeSession()

    async def _fake_config_service():
        return _FakeConfigService()

    app.dependency_overrides[get_db_with_rls] = _fake_db_with_rls
    app.dependency_overrides[get_config_service] = _fake_config_service
    monkeypatch.setattr(assets_routes, "async_session_factory", _FakeSessionFactory)
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_branding_returns_default(client: AsyncClient):
    """GET /api/v1/branding returns default Netz branding when no override."""
    response = await client.get("/api/v1/branding", headers=SUPER_ADMIN_DEV_ACTOR_HEADER)
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
async def test_get_branding_rejects_non_super_admin(client: AsyncClient):
    """GET /api/v1/branding with org admin auth returns 403."""
    response = await client.get("/api/v1/branding", headers=DEV_ACTOR_HEADER)
    assert response.status_code == 403
    assert response.json()["detail"] == "Platform admin access required"


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

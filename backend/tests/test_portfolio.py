"""Tests for credit portfolio asset endpoints — auth layer (no DB required)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

FUND_ID = "00000000-0000-0000-0000-000000000099"
BASE = f"/api/v1/funds/{FUND_ID}/assets"


@pytest.mark.asyncio
async def test_create_asset_requires_auth(client: AsyncClient):
    """Unauthenticated POST should return 401."""
    response = await client.post(BASE, json={
        "asset_type": "DIRECT_LOAN",
        "strategy": "CORE_DIRECT_LENDING",
        "name": "Test Asset",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_assets_route_exists(client: AsyncClient):
    """Route exists — POST without auth gives 401 (not 404)."""
    response = await client.post(BASE, json={})
    assert response.status_code != 404

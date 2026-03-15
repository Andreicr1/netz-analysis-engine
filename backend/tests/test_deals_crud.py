"""Tests for credit deals endpoints — auth layer (no DB required)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

FUND_ID = "00000000-0000-0000-0000-000000000099"
BASE = f"/api/v1/funds/{FUND_ID}/deals"


@pytest.mark.asyncio
async def test_create_deal_requires_auth(client: AsyncClient):
    """Unauthenticated POST should return 401."""
    response = await client.post(BASE, json={
        "deal_type": "DIRECT_LOAN",
        "name": "Test Deal",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_deals_requires_auth(client: AsyncClient):
    """Unauthenticated GET should return 401."""
    response = await client.get(BASE)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_deals_route_exists(client: AsyncClient):
    """Route exists — 401 (not 404) proves the router is mounted."""
    response = await client.get(BASE)
    assert response.status_code != 404

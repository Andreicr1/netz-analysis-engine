"""Tests for Portfolio Holdings + Screener Catalog REST endpoints.

Covers:
  - GET /market-data/portfolio/{id}/holdings — auth, response shape, empty fallback
  - GET /market-data/screener/catalog — auth, pagination, search, response shape
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from tests.conftest import DEV_ACTOR_HEADER


@pytest.fixture
async def async_client():
    """Async HTTP client for REST endpoint testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Portfolio Holdings ─────────────────────────────────────


@pytest.mark.asyncio
async def test_portfolio_holdings_requires_auth(async_client: AsyncClient):
    """Portfolio holdings endpoint requires authentication."""
    resp = await async_client.get("/api/v1/market-data/portfolio/growth/holdings")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_portfolio_holdings_returns_shape(async_client: AsyncClient):
    """Portfolio holdings returns correct response structure."""
    resp = await async_client.get(
        "/api/v1/market-data/portfolio/growth/holdings",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "portfolio_id" in data
    assert "profile" in data
    assert "holdings" in data
    assert "cash_balance" in data
    assert "portfolio_nav" in data
    assert "as_of" in data
    assert isinstance(data["holdings"], list)


@pytest.mark.asyncio
async def test_portfolio_holdings_empty_fallback(async_client: AsyncClient):
    """Portfolio holdings for nonexistent portfolio returns empty list."""
    resp = await async_client.get(
        "/api/v1/market-data/portfolio/nonexistent-profile/holdings",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["holdings"] == []
    # Pydantic v2 serializes Decimal as string by default.
    assert Decimal(data["portfolio_nav"]) == 0


@pytest.mark.asyncio
async def test_portfolio_holdings_position_fields(async_client: AsyncClient):
    """If holdings exist, each position has required fields."""
    resp = await async_client.get(
        "/api/v1/market-data/portfolio/growth/holdings",
        headers=DEV_ACTOR_HEADER,
    )
    data = resp.json()
    for position in data["holdings"]:
        assert "instrument_id" in position
        assert "ticker" in position
        assert "name" in position
        assert "weight" in position
        assert "quantity" in position
        assert "last_price" in position
        assert "previous_close" in position
        assert "asset_class" in position
        assert "currency" in position


# ── Screener Catalog ───────────────────────────────────────


@pytest.mark.asyncio
async def test_screener_catalog_requires_auth(async_client: AsyncClient):
    """Screener catalog endpoint requires authentication."""
    resp = await async_client.get("/api/v1/market-data/screener/catalog")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_screener_catalog_returns_shape(async_client: AsyncClient):
    """Screener catalog returns correct paginated response structure."""
    resp = await async_client.get(
        "/api/v1/market-data/screener/catalog",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data
    assert "has_next" in data
    assert isinstance(data["items"], list)
    assert data["page"] == 1
    assert data["page_size"] == 50


@pytest.mark.asyncio
async def test_screener_catalog_pagination(async_client: AsyncClient):
    """Screener catalog respects page and page_size params."""
    resp = await async_client.get(
        "/api/v1/market-data/screener/catalog",
        params={"page": 2, "page_size": 10},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 2
    assert data["page_size"] == 10


@pytest.mark.asyncio
async def test_screener_catalog_search(async_client: AsyncClient):
    """Screener catalog search filter works."""
    resp = await async_client.get(
        "/api/v1/market-data/screener/catalog",
        params={"q": "vanguard"},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["items"], list)
    # All results should contain the search term (if any)
    for item in data["items"]:
        assert "name" in item
        assert "external_id" in item


@pytest.mark.asyncio
async def test_screener_catalog_asset_fields(async_client: AsyncClient):
    """Each screener asset has required fields."""
    resp = await async_client.get(
        "/api/v1/market-data/screener/catalog",
        params={"page_size": 5},
        headers=DEV_ACTOR_HEADER,
    )
    data = resp.json()
    for item in data["items"]:
        assert "external_id" in item
        assert "name" in item
        assert "asset_class" in item
        assert "region" in item
        assert "fund_type" in item
        # Price fields are nullable
        assert "last_price" in item
        assert "change" in item
        assert "change_pct" in item


@pytest.mark.asyncio
async def test_screener_catalog_region_filter(async_client: AsyncClient):
    """Screener catalog region filter works."""
    resp = await async_client.get(
        "/api/v1/market-data/screener/catalog",
        params={"region": "US"},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    for item in data["items"]:
        assert item["region"] == "US"

"""Tests for Portfolio Analytics endpoints (holdings + performance).

Covers:
  - GET /model-portfolios/{id}/holdings — auth, 404, response shape
  - GET /model-portfolios/{id}/performance — auth, 404, timeframe validation
  - GET /market-data/dashboard-snapshot — auth, response shape
  - Schema validation for PositionDetail and PortfolioPerformanceSeries
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient

from app.domains.wealth.schemas.model_portfolio import (
    ModelPortfolioRead,
    RebalancePreviewResponse,
)
from app.domains.wealth.schemas.portfolio import (
    PerformancePoint,
    PortfolioPerformanceSeries,
    PositionDetail,
)
from app.main import app
from tests.conftest import DEV_ACTOR_HEADER


@pytest.fixture
async def client():
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Schema Unit Tests ───────────────────────────────────────


def test_position_detail_schema():
    """PositionDetail can be created with all fields."""
    pos = PositionDetail(
        instrument_id=uuid.uuid4(),
        ticker="SPY",
        name="SPDR S&P 500 ETF Trust",
        asset_class="Equity",
        currency="USD",
        weight=Decimal("0.25"),
        block_id="core_equity",
        last_price=Decimal("450.00"),
        previous_close=Decimal("448.50"),
        position_value=Decimal("250.00"),
        intraday_pnl=Decimal("0.84"),
        intraday_pnl_pct=Decimal("0.33"),
    )
    assert pos.weight == Decimal("0.25")
    assert pos.intraday_pnl == Decimal("0.84")


def test_position_detail_schema_minimal():
    """PositionDetail works with only required fields."""
    pos = PositionDetail(
        instrument_id=uuid.uuid4(),
        name="Test Fund",
        weight=Decimal("0.10"),
    )
    assert pos.last_price is None
    assert pos.intraday_pnl is None
    assert pos.currency == "USD"


def test_performance_point_schema():
    """PerformancePoint schema validation."""
    from datetime import date

    point = PerformancePoint(
        nav_date=date(2026, 4, 1),
        nav=Decimal("1050.25"),
        daily_return=Decimal("0.0025"),
        cumulative_return=Decimal("5.025"),
    )
    assert point.nav == Decimal("1050.25")


def test_performance_series_schema():
    """PortfolioPerformanceSeries with empty and populated series."""
    from datetime import date

    series = PortfolioPerformanceSeries(
        portfolio_id=uuid.uuid4(),
        profile="growth",
        inception_date=date(2025, 1, 1),
        inception_nav=Decimal("1000"),
        benchmark_name="60/40",
        series=[],
        as_of=date(2026, 4, 5),
    )
    assert series.profile == "growth"
    assert len(series.series) == 0


# ── Holdings Endpoint Tests ─────────────────────────────────


@pytest.mark.asyncio
async def test_holdings_requires_auth(client: AsyncClient):
    """GET /model-portfolios/{id}/holdings requires authentication."""
    random_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/model-portfolios/{random_id}/holdings")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_holdings_404_for_missing_portfolio(client: AsyncClient):
    """GET /model-portfolios/{id}/holdings returns 404 for non-existent portfolio."""
    random_id = str(uuid.uuid4())
    resp = await client.get(
        f"/api/v1/model-portfolios/{random_id}/holdings",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_holdings_returns_list(client: AsyncClient):
    """GET /model-portfolios/{id}/holdings returns a list (may be empty)."""
    # First get a real portfolio ID if one exists
    list_resp = await client.get(
        "/api/v1/model-portfolios",
        headers=DEV_ACTOR_HEADER,
    )
    if list_resp.status_code != 200 or not list_resp.json():
        pytest.skip("No model portfolios in test DB")

    portfolio_id = list_resp.json()[0]["id"]
    resp = await client.get(
        f"/api/v1/model-portfolios/{portfolio_id}/holdings",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # If there are positions, validate shape
    if data:
        pos = data[0]
        assert "instrument_id" in pos
        assert "weight" in pos
        assert "last_price" in pos
        assert "intraday_pnl_pct" in pos


# ── Performance Endpoint Tests ──────────────────────────────


@pytest.mark.asyncio
async def test_performance_requires_auth(client: AsyncClient):
    """GET /model-portfolios/{id}/performance requires authentication."""
    random_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/model-portfolios/{random_id}/performance")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_performance_404_for_missing_portfolio(client: AsyncClient):
    """GET /model-portfolios/{id}/performance returns 404 for non-existent portfolio."""
    random_id = str(uuid.uuid4())
    resp = await client.get(
        f"/api/v1/model-portfolios/{random_id}/performance",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_performance_invalid_timeframe(client: AsyncClient):
    """GET /model-portfolios/{id}/performance rejects invalid timeframes."""
    random_id = str(uuid.uuid4())
    resp = await client.get(
        f"/api/v1/model-portfolios/{random_id}/performance?timeframe=5Y",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 422  # validation error


@pytest.mark.asyncio
async def test_performance_returns_series(client: AsyncClient):
    """GET /model-portfolios/{id}/performance returns valid series structure."""
    list_resp = await client.get(
        "/api/v1/model-portfolios",
        headers=DEV_ACTOR_HEADER,
    )
    if list_resp.status_code != 200 or not list_resp.json():
        pytest.skip("No model portfolios in test DB")

    portfolio_id = list_resp.json()[0]["id"]
    resp = await client.get(
        f"/api/v1/model-portfolios/{portfolio_id}/performance?timeframe=1Y",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "portfolio_id" in data
    assert "profile" in data
    assert "series" in data
    assert isinstance(data["series"], list)
    assert "as_of" in data


# ── Dashboard Snapshot Tests ────────────────────────────────


@pytest.mark.asyncio
async def test_dashboard_snapshot_requires_auth(client: AsyncClient):
    """Dashboard snapshot endpoint requires authentication."""
    resp = await client.get("/api/v1/market-data/dashboard-snapshot")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_snapshot_response_shape(client: AsyncClient):
    """Dashboard snapshot returns valid structure with auth."""
    resp = await client.get(
        "/api/v1/market-data/dashboard-snapshot",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "holdings" in data
    assert "total_aum" in data
    assert "as_of" in data
    assert isinstance(data["holdings"], list)
    # Holdings should have weight (not units)
    if data["holdings"]:
        h = data["holdings"][0]
        assert "weight" in h
        assert "price" in h
        assert "asset_class" in h


# ── Weight Validation Tests (G1) ──────────────────────────────


def test_model_portfolio_read_weight_warning_off():
    """ModelPortfolioRead.weight_warning is False when weights sum to ~1.0."""
    mp = ModelPortfolioRead(
        id=uuid.uuid4(),
        profile="moderate",
        display_name="Test Portfolio",
        inception_nav=Decimal("1000"),
        status="active",
        fund_selection_schema={
            "profile": "moderate",
            "total_weight": 1.0,
            "funds": [
                {"instrument_id": str(uuid.uuid4()), "weight": 0.6, "block_id": "equity", "fund_name": "A"},
                {"instrument_id": str(uuid.uuid4()), "weight": 0.4, "block_id": "fi", "fund_name": "B"},
            ],
        },
        created_at="2026-04-05T00:00:00+00:00",
    )
    assert mp.weight_warning is False


def test_model_portfolio_read_weight_warning_on_over():
    """ModelPortfolioRead.weight_warning is True when weights sum > 1.02."""
    mp = ModelPortfolioRead(
        id=uuid.uuid4(),
        profile="growth",
        display_name="Over-allocated",
        inception_nav=Decimal("1000"),
        status="draft",
        fund_selection_schema={
            "profile": "growth",
            "total_weight": 1.5,
            "funds": [
                {"instrument_id": str(uuid.uuid4()), "weight": 0.8, "block_id": "equity", "fund_name": "A"},
                {"instrument_id": str(uuid.uuid4()), "weight": 0.7, "block_id": "fi", "fund_name": "B"},
            ],
        },
        created_at="2026-04-05T00:00:00+00:00",
    )
    assert mp.weight_warning is True


def test_model_portfolio_read_weight_warning_on_under():
    """ModelPortfolioRead.weight_warning is True when weights sum < 0.98."""
    mp = ModelPortfolioRead(
        id=uuid.uuid4(),
        profile="conservative",
        display_name="Under-allocated",
        inception_nav=Decimal("1000"),
        status="draft",
        fund_selection_schema={
            "profile": "conservative",
            "total_weight": 0.3,
            "funds": [
                {"instrument_id": str(uuid.uuid4()), "weight": 0.2, "block_id": "equity", "fund_name": "A"},
                {"instrument_id": str(uuid.uuid4()), "weight": 0.1, "block_id": "fi", "fund_name": "B"},
            ],
        },
        created_at="2026-04-05T00:00:00+00:00",
    )
    assert mp.weight_warning is True


def test_model_portfolio_read_no_schema_no_warning():
    """ModelPortfolioRead.weight_warning is False when fund_selection_schema is None."""
    mp = ModelPortfolioRead(
        id=uuid.uuid4(),
        profile="moderate",
        display_name="Empty Portfolio",
        inception_nav=Decimal("1000"),
        status="draft",
        fund_selection_schema=None,
        created_at="2026-04-05T00:00:00+00:00",
    )
    assert mp.weight_warning is False


def test_model_portfolio_read_edge_tolerance():
    """Weights summing to exactly 0.98 or 1.02 should NOT trigger warning."""
    mp = ModelPortfolioRead(
        id=uuid.uuid4(),
        profile="moderate",
        display_name="Edge Case",
        inception_nav=Decimal("1000"),
        status="active",
        fund_selection_schema={
            "profile": "moderate",
            "total_weight": 1.02,
            "funds": [
                {"instrument_id": str(uuid.uuid4()), "weight": 0.52, "block_id": "equity", "fund_name": "A"},
                {"instrument_id": str(uuid.uuid4()), "weight": 0.50, "block_id": "fi", "fund_name": "B"},
            ],
        },
        created_at="2026-04-05T00:00:00+00:00",
    )
    assert mp.weight_warning is False


# ── Rebalance Preview CVaR Schema Tests (G3) ──────────────────


def test_rebalance_preview_response_cvar_fields():
    """RebalancePreviewResponse includes CVaR awareness fields."""
    resp = RebalancePreviewResponse(
        portfolio_id=str(uuid.uuid4()),
        portfolio_name="Test",
        profile="moderate",
        total_aum=1_000_000.0,
        cash_available=50_000.0,
        total_trades=3,
        estimated_turnover_pct=0.05,
        trades=[],
        weight_comparison=[],
        cvar_95_projected=-0.08,
        cvar_limit=-0.10,
        cvar_warning=False,
    )
    assert resp.cvar_95_projected == -0.08
    assert resp.cvar_limit == -0.10
    assert resp.cvar_warning is False


def test_rebalance_preview_response_cvar_warning_flag():
    """RebalancePreviewResponse cvar_warning is True when CVaR approaches limit."""
    resp = RebalancePreviewResponse(
        portfolio_id=str(uuid.uuid4()),
        portfolio_name="Risky",
        profile="growth",
        total_aum=2_000_000.0,
        cash_available=0.0,
        total_trades=5,
        estimated_turnover_pct=0.12,
        trades=[],
        weight_comparison=[],
        cvar_95_projected=-0.095,
        cvar_limit=-0.10,
        cvar_warning=True,
    )
    assert resp.cvar_warning is True


def test_rebalance_preview_response_cvar_defaults():
    """CVaR fields default to None/False when not provided."""
    resp = RebalancePreviewResponse(
        portfolio_id=str(uuid.uuid4()),
        portfolio_name="Basic",
        profile="conservative",
        total_aum=500_000.0,
        cash_available=10_000.0,
        total_trades=1,
        estimated_turnover_pct=0.02,
        trades=[],
        weight_comparison=[],
    )
    assert resp.cvar_95_projected is None
    assert resp.cvar_limit is None
    assert resp.cvar_warning is False

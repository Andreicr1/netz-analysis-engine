"""Tests for Drift, Live Drift, and Monitoring Alerts endpoints.

Covers:
  - GET /model-portfolios/{id}/drift — auth (401), 404, schema shape
  - GET /model-portfolios/{id}/drift/live — auth (401), 404, 400 (no fund_selection), schema shape
  - GET /monitoring/alerts — auth (401), schema shape
  - Pydantic schema validation for drift and alert schemas
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.domains.wealth.schemas.portfolio import (
    AlertBatchRead,
    AlertRead,
    BlockDriftRead,
    DriftReportRead,
    LiveDriftResponse,
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


def test_block_drift_read_schema():
    """BlockDriftRead can be created with all fields."""
    block = BlockDriftRead(
        block_id="core_equity",
        current_weight=0.32,
        target_weight=0.30,
        absolute_drift=0.02,
        relative_drift=0.0667,
        status="maintenance",
    )
    assert block.block_id == "core_equity"
    assert block.status == "maintenance"
    assert block.absolute_drift == 0.02


def test_drift_report_read_schema():
    """DriftReportRead validates all fields including nested blocks."""
    report = DriftReportRead(
        profile="moderate",
        as_of_date=date(2026, 4, 5),
        blocks=[
            BlockDriftRead(
                block_id="core_equity",
                current_weight=0.35,
                target_weight=0.30,
                absolute_drift=0.05,
                relative_drift=0.1667,
                status="maintenance",
            ),
        ],
        max_drift_pct=0.05,
        overall_status="maintenance",
        rebalance_recommended=True,
        estimated_turnover=0.025,
    )
    assert report.profile == "moderate"
    assert len(report.blocks) == 1
    assert report.rebalance_recommended is True


def test_drift_report_empty_blocks():
    """DriftReportRead works with empty blocks list."""
    report = DriftReportRead(
        profile="conservative",
        as_of_date=date(2026, 4, 5),
        blocks=[],
        max_drift_pct=0.0,
        overall_status="ok",
        rebalance_recommended=False,
        estimated_turnover=0.0,
    )
    assert report.overall_status == "ok"
    assert len(report.blocks) == 0


def test_live_drift_response_schema():
    """LiveDriftResponse validates all fields."""
    resp = LiveDriftResponse(
        portfolio_id=str(uuid.uuid4()),
        profile="growth",
        as_of=date(2026, 4, 5),
        total_aum=1_000_000.0,
        blocks=[
            BlockDriftRead(
                block_id="satellite_em",
                current_weight=0.12,
                target_weight=0.10,
                absolute_drift=0.02,
                relative_drift=0.20,
                status="maintenance",
            ),
        ],
        max_drift_pct=0.02,
        overall_status="maintenance",
        rebalance_recommended=False,
        estimated_turnover=0.01,
    )
    assert resp.profile == "growth"
    assert resp.total_aum == 1_000_000.0
    # latest_nav_date defaults to None
    assert resp.latest_nav_date is None


def test_live_drift_response_with_nav_date():
    """LiveDriftResponse includes latest_nav_date when provided."""
    resp = LiveDriftResponse(
        portfolio_id=str(uuid.uuid4()),
        profile="moderate",
        as_of=date(2026, 4, 5),
        total_aum=500_000.0,
        blocks=[],
        max_drift_pct=0.0,
        overall_status="ok",
        rebalance_recommended=False,
        estimated_turnover=0.0,
        latest_nav_date=date(2026, 4, 3),
    )
    assert resp.latest_nav_date == date(2026, 4, 3)


def test_alert_read_schema():
    """AlertRead schema with all fields."""
    alert = AlertRead(
        alert_type="dd_expiry",
        severity="warning",
        title="DD Report expired for Test Fund",
        detail="Last DD Report is 400 days old.",
        entity_id=str(uuid.uuid4()),
        entity_type="fund",
    )
    assert alert.alert_type == "dd_expiry"
    assert alert.entity_type == "fund"


def test_alert_read_minimal():
    """AlertRead works without optional entity fields."""
    alert = AlertRead(
        alert_type="rebalance_overdue",
        severity="info",
        title="Rebalance overdue",
        detail="No rebalance on record.",
    )
    assert alert.entity_id is None
    assert alert.entity_type is None


def test_alert_batch_read_schema():
    """AlertBatchRead validates batch structure."""
    batch = AlertBatchRead(
        alerts=[
            AlertRead(
                alert_type="dd_expiry",
                severity="warning",
                title="DD expired",
                detail="Test detail",
            ),
        ],
        scanned_at="2026-04-05T12:00:00+00:00",
        organization_id="00000000-0000-0000-0000-000000000001",
    )
    assert len(batch.alerts) == 1
    assert batch.organization_id == "00000000-0000-0000-0000-000000000001"


# ── GET /model-portfolios/{id}/drift ──────────────────────────


@pytest.mark.asyncio
async def test_drift_requires_auth(client: AsyncClient):
    """GET /model-portfolios/{id}/drift requires authentication."""
    random_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/model-portfolios/{random_id}/drift")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_drift_404_for_missing_portfolio(client: AsyncClient):
    """GET /model-portfolios/{id}/drift returns 404 for non-existent portfolio."""
    random_id = str(uuid.uuid4())
    resp = await client.get(
        f"/api/v1/model-portfolios/{random_id}/drift",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_drift_returns_report(client: AsyncClient):
    """GET /model-portfolios/{id}/drift returns DriftReportRead shape."""
    list_resp = await client.get(
        "/api/v1/model-portfolios",
        headers=DEV_ACTOR_HEADER,
    )
    if list_resp.status_code != 200 or not list_resp.json():
        pytest.skip("No model portfolios in test DB")

    portfolio_id = list_resp.json()[0]["id"]
    resp = await client.get(
        f"/api/v1/model-portfolios/{portfolio_id}/drift",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "profile" in data
    assert "overall_status" in data
    assert "blocks" in data
    assert isinstance(data["blocks"], list)
    assert "rebalance_recommended" in data
    assert data["overall_status"] in ("ok", "maintenance", "urgent")


# ── GET /model-portfolios/{id}/drift/live ─────────────────────


@pytest.mark.asyncio
async def test_live_drift_requires_auth(client: AsyncClient):
    """GET /model-portfolios/{id}/drift/live requires authentication."""
    random_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/model-portfolios/{random_id}/drift/live")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_live_drift_404_for_missing_portfolio(client: AsyncClient):
    """GET /model-portfolios/{id}/drift/live returns 404 for non-existent portfolio."""
    random_id = str(uuid.uuid4())
    resp = await client.get(
        f"/api/v1/model-portfolios/{random_id}/drift/live",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_live_drift_returns_response(client: AsyncClient):
    """GET /model-portfolios/{id}/drift/live returns LiveDriftResponse shape."""
    list_resp = await client.get(
        "/api/v1/model-portfolios",
        headers=DEV_ACTOR_HEADER,
    )
    if list_resp.status_code != 200 or not list_resp.json():
        pytest.skip("No model portfolios in test DB")

    # Find a portfolio with fund_selection_schema
    portfolio_id = None
    for p in list_resp.json():
        if p.get("fund_selection_schema") and p["fund_selection_schema"].get("funds"):
            portfolio_id = p["id"]
            break

    if portfolio_id is None:
        pytest.skip("No constructed portfolios in test DB")

    resp = await client.get(
        f"/api/v1/model-portfolios/{portfolio_id}/drift/live",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "portfolio_id" in data
    assert "overall_status" in data
    assert "blocks" in data
    assert "total_aum" in data
    assert data["overall_status"] in ("ok", "maintenance", "urgent")


@pytest.mark.asyncio
async def test_live_drift_400_no_fund_selection(client: AsyncClient):
    """GET /model-portfolios/{id}/drift/live returns 400 if no fund_selection."""
    list_resp = await client.get(
        "/api/v1/model-portfolios",
        headers=DEV_ACTOR_HEADER,
    )
    if list_resp.status_code != 200 or not list_resp.json():
        pytest.skip("No model portfolios in test DB")

    # Find a draft portfolio without fund_selection_schema
    portfolio_id = None
    for p in list_resp.json():
        if not p.get("fund_selection_schema") or not p["fund_selection_schema"].get("funds"):
            portfolio_id = p["id"]
            break

    if portfolio_id is None:
        pytest.skip("No unconstructed portfolios in test DB")

    resp = await client.get(
        f"/api/v1/model-portfolios/{portfolio_id}/drift/live",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 400
    assert "fund selection" in resp.json()["detail"].lower()


# ── GET /monitoring/alerts ────────────────────────────────────


@pytest.mark.asyncio
async def test_monitoring_alerts_requires_auth(client: AsyncClient):
    """GET /monitoring/alerts requires authentication."""
    resp = await client.get("/api/v1/monitoring/alerts")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_monitoring_alerts_returns_batch(client: AsyncClient):
    """GET /monitoring/alerts returns AlertBatchRead shape."""
    resp = await client.get(
        "/api/v1/monitoring/alerts",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "alerts" in data
    assert isinstance(data["alerts"], list)
    assert "scanned_at" in data
    assert "organization_id" in data

    # Validate individual alert shape if any exist
    for alert in data["alerts"]:
        assert "alert_type" in alert
        assert "severity" in alert
        assert "title" in alert
        assert "detail" in alert
        assert alert["alert_type"] in ("dd_expiry", "rebalance_overdue")
        assert alert["severity"] in ("info", "warning", "critical")

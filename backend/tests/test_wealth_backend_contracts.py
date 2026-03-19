"""Tests for wealth backend contract gaps — computed_at + drift export."""

from __future__ import annotations

import csv
import io
import json
import uuid
from datetime import UTC, date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

DEV_ACTOR_HEADER = {
    "X-DEV-ACTOR": json.dumps(
        {
            "actor_id": "test-user",
            "roles": ["ADMIN"],
            "fund_ids": [],
            "org_id": "00000000-0000-0000-0000-000000000001",
        }
    )
}

ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Helpers ───────────────────────────────────────────────────────


def _fake_snapshot(profile: str = "conservative", snap_date: date | None = None):
    """Build a mock PortfolioSnapshot with the fields routes access."""
    snap = MagicMock()
    snap.snapshot_id = uuid.uuid4()
    snap.profile = profile
    snap.snapshot_date = snap_date or date(2026, 3, 15)
    snap.weights = {"core": 0.6, "satellite": 0.4}
    snap.fund_selection = None
    snap.cvar_current = Decimal("0.045")
    snap.cvar_limit = Decimal("0.10")
    snap.cvar_utilized_pct = Decimal("45.0")
    snap.trigger_status = "ok"
    snap.consecutive_breach_days = 0
    snap.regime = "normal"
    snap.core_weight = Decimal("0.6")
    snap.satellite_weight = Decimal("0.4")
    snap.regime_probs = None
    snap.cvar_lower_5 = None
    snap.cvar_upper_95 = None
    return snap


def _fake_drift_alert(
    instrument_id: uuid.UUID,
    severity: str = "moderate",
    detected_at: datetime | None = None,
):
    alert = MagicMock()
    alert.id = uuid.uuid4()
    alert.instrument_id = instrument_id
    alert.status = "drift_detected"
    alert.severity = severity
    alert.anomalous_count = 3
    alert.total_metrics = 7
    alert.metric_details = [
        {"metric_name": "volatility_1y", "z_score": 3.5, "is_anomalous": True}
    ]
    alert.is_current = True
    alert.detected_at = detected_at or datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    alert.created_at = datetime(2026, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
    return alert


# ── Gap 1: computed_at on Portfolio schemas ───────────────────────


@pytest.mark.asyncio
class TestPortfolioComputedAt:
    async def test_computed_at_in_summary(self, client: AsyncClient):
        snap = _fake_snapshot("conservative")

        async def _mock_get_latest(db, profile):
            return snap if profile == "conservative" else None

        with patch(
            "app.domains.wealth.routes.portfolios.get_latest_snapshot",
            side_effect=_mock_get_latest,
        ):
            resp = await client.get(
                "/api/v1/portfolios/conservative", headers=DEV_ACTOR_HEADER
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "computed_at" in data
        assert data["computed_at"] is not None
        # Should be derived from snapshot_date
        parsed = datetime.fromisoformat(data["computed_at"])
        assert parsed.date() == date(2026, 3, 15)

    async def test_computed_at_in_snapshot(self, client: AsyncClient):
        snap = _fake_snapshot("conservative")

        async def _mock_get_latest(db, profile):
            return snap

        with patch(
            "app.domains.wealth.routes.portfolios.get_latest_snapshot",
            side_effect=_mock_get_latest,
        ):
            resp = await client.get(
                "/api/v1/portfolios/conservative/snapshot",
                headers=DEV_ACTOR_HEADER,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "computed_at" in data
        assert data["computed_at"] is not None

    async def test_computed_at_none_when_no_snapshot(self, client: AsyncClient):
        async def _mock_get_latest(db, profile):
            return None

        with patch(
            "app.domains.wealth.routes.portfolios.get_latest_snapshot",
            side_effect=_mock_get_latest,
        ):
            resp = await client.get(
                "/api/v1/portfolios/conservative", headers=DEV_ACTOR_HEADER
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["computed_at"] is None


# ── Gap 2: Drift export ──────────────────────────────────────────


INST_ID = uuid.UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
EXPORT_BASE = f"/api/v1/analytics/strategy-drift/{INST_ID}/export"


def _mock_db_with_instrument_and_alerts(alerts: list):
    """Create a mock AsyncSession that returns instrument name + alerts."""
    mock_db = AsyncMock()

    # First execute call: instrument name lookup
    inst_result = MagicMock()
    inst_result.scalar.return_value = "Test Fund"

    # Second execute call: alerts query
    alerts_result = MagicMock()
    alerts_scalars = MagicMock()
    alerts_scalars.all.return_value = alerts
    alerts_result.scalars.return_value = alerts_scalars

    mock_db.execute = AsyncMock(side_effect=[inst_result, alerts_result])
    return mock_db


@pytest.mark.asyncio
class TestDriftExportCSV:
    async def test_csv_returns_valid_headers(self, client: AsyncClient):
        alert = _fake_drift_alert(INST_ID)
        mock_db = _mock_db_with_instrument_and_alerts([alert])

        with patch("app.domains.wealth.routes.strategy_drift.get_db_with_rls") as mock_dep:
            app.dependency_overrides[
                __import__(
                    "app.core.tenancy.middleware", fromlist=["get_db_with_rls"]
                ).get_db_with_rls
            ] = lambda: mock_db
            try:
                resp = await client.get(
                    f"{EXPORT_BASE}?format=csv", headers=DEV_ACTOR_HEADER
                )
            finally:
                app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert "text/csv" in resp.headers["content-type"]
        assert "attachment" in resp.headers["content-disposition"]

        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 1
        assert set(reader.fieldnames or []) == {
            "detected_at",
            "status",
            "severity",
            "anomalous_count",
            "metric_details",
        }

    async def test_json_returns_valid_array(self, client: AsyncClient):
        alert = _fake_drift_alert(INST_ID)
        mock_db = _mock_db_with_instrument_and_alerts([alert])

        from app.core.tenancy.middleware import get_db_with_rls

        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{EXPORT_BASE}?format=json", headers=DEV_ACTOR_HEADER
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert "application/json" in resp.headers["content-type"]
        data = json.loads(resp.text)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["severity"] == "moderate"


@pytest.mark.asyncio
class TestDriftExportFilters:
    async def test_date_filter_passed_to_query(self, client: AsyncClient):
        """Verify from_date/to_date are passed through to the query."""
        mock_db = _mock_db_with_instrument_and_alerts([])

        from app.core.tenancy.middleware import get_db_with_rls

        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{EXPORT_BASE}?format=csv&from_date=2026-01-01T00:00:00Z&to_date=2026-03-01T00:00:00Z",
                headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        # Empty CSV (header only)
        lines = resp.text.strip().split("\n")
        assert len(lines) == 1  # header only

    async def test_404_for_missing_instrument(self, client: AsyncClient):
        """RLS: instrument not found returns 404."""
        mock_db = AsyncMock()
        inst_result = MagicMock()
        inst_result.scalar.return_value = None  # instrument not found
        mock_db.execute = AsyncMock(return_value=inst_result)

        from app.core.tenancy.middleware import get_db_with_rls

        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(EXPORT_BASE, headers=DEV_ACTOR_HEADER)
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 404

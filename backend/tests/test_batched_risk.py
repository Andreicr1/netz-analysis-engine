"""Tests for batched risk summary endpoint."""

from __future__ import annotations

import json
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

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

SUMMARY_URL = "/api/v1/risk/summary"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _fake_snapshot(profile: str, snap_date: date | None = None):
    snap = MagicMock()
    snap.profile = profile
    snap.snapshot_date = snap_date or date(2026, 3, 15)
    snap.cvar_current = Decimal("0.045")
    snap.cvar_limit = Decimal("0.10")
    snap.cvar_utilized_pct = Decimal("45.0")
    snap.trigger_status = "ok"
    snap.consecutive_breach_days = 0
    snap.regime = "normal"
    snap.cvar_lower_5 = Decimal("0.035")
    snap.cvar_upper_95 = Decimal("0.055")
    return snap


def _mock_db_with_snapshots(snapshots: list):
    """Mock db that returns snapshots from the batch query."""
    mock_db = AsyncMock()
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = snapshots
    result.scalars.return_value = scalars
    mock_db.execute = AsyncMock(return_value=result)
    return mock_db


@pytest.mark.asyncio
class TestBatchRiskSummary:
    async def test_single_profile(self, client: AsyncClient):
        snap = _fake_snapshot("conservative")
        mock_db = _mock_db_with_snapshots([snap])

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{SUMMARY_URL}?profiles=conservative", headers=DEV_ACTOR_HEADER
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_count"] == 1
        assert "conservative" in data["profiles"]
        cvar = data["profiles"]["conservative"]
        assert cvar["profile"] == "conservative"
        assert float(cvar["cvar_current"]) == pytest.approx(0.045)
        assert data["computed_at"] is not None

    async def test_multiple_profiles(self, client: AsyncClient):
        snaps = [
            _fake_snapshot("conservative"),
            _fake_snapshot("moderate"),
            _fake_snapshot("growth"),
        ]
        mock_db = _mock_db_with_snapshots(snaps)

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{SUMMARY_URL}?profiles=conservative,moderate,growth",
                headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_count"] == 3
        for name in ("conservative", "moderate", "growth"):
            assert name in data["profiles"]
            assert data["profiles"][name] is not None

    async def test_unknown_profile_returns_none(self, client: AsyncClient):
        snap = _fake_snapshot("conservative")
        mock_db = _mock_db_with_snapshots([snap])

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{SUMMARY_URL}?profiles=conservative,nonexistent",
                headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["profiles"]["nonexistent"] is None
        assert data["profiles"]["conservative"] is not None

    async def test_empty_profiles_returns_422(self, client: AsyncClient):
        resp = await client.get(
            f"{SUMMARY_URL}?profiles=", headers=DEV_ACTOR_HEADER
        )
        assert resp.status_code == 422

    async def test_too_many_profiles_returns_422(self, client: AsyncClient):
        many = ",".join(f"profile{i}" for i in range(21))
        resp = await client.get(
            f"{SUMMARY_URL}?profiles={many}", headers=DEV_ACTOR_HEADER
        )
        assert resp.status_code == 422
        assert "Too many profiles" in resp.json()["detail"]

    async def test_requires_auth(self, client: AsyncClient):
        resp = await client.get(f"{SUMMARY_URL}?profiles=conservative")
        assert resp.status_code == 401

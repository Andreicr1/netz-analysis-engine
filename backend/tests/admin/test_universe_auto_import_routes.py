"""Tests for admin universe auto-import routes.

Scope:

* RBAC — non ``SUPER_ADMIN`` callers hit 403.
* Happy path — ``POST /admin/universe/auto-import/run`` returns the
  service metrics as-is, aum/coverage constants from the service are
  echoed back.
* Status — ``GET /admin/universe/auto-import/status`` returns the
  aggregated shape (list of per-org rows).

The service call itself is patched so we don't need a live catalog or
populated ``nav_timeseries``; the classifier and SQL are covered by
``test_universe_auto_import_classifier.py`` (already green) and the
worker smoke test on a dev DB.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.tenancy.admin_middleware import get_db_admin
from app.domains.wealth.services.universe_auto_import_service import (
    AUM_FLOOR_USD,
    NAV_COVERAGE_MIN,
)
from app.main import app

ORG_ID = "00000000-0000-0000-0000-000000000010"

SUPER_ADMIN_HEADER = {
    "X-DEV-ACTOR": json.dumps({
        "actor_id": "super-admin",
        "roles": ["SUPER_ADMIN"],
        "fund_ids": [],
        "org_id": ORG_ID,
    }),
}

INVESTMENT_TEAM_HEADER = {
    "X-DEV-ACTOR": json.dumps({
        "actor_id": "ic-analyst",
        "roles": ["INVESTMENT_TEAM"],
        "fund_ids": [],
        "org_id": ORG_ID,
    }),
}

BASE = "/api/v1/admin/universe/auto-import"


class _FakeResult:
    """Mimics SQLAlchemy Result.all() returning zero rows — enough for
    the /status endpoint's shape tests.
    """

    def all(self) -> list:
        return []


class _FakeDb:
    async def execute(self, *args, **kwargs) -> _FakeResult:  # noqa: ANN002, ANN003
        return _FakeResult()

    async def commit(self) -> None:
        return None


async def _fake_db_admin():
    yield _FakeDb()


async def _fake_db_for_tenant(org_id):  # noqa: ANN001
    yield _FakeDb()


@pytest.fixture
async def client():
    # /status uses Depends(get_db_admin) — dependency_overrides works.
    # /run calls get_db_for_tenant(body.org_id) directly (async generator
    # iteration), so that one is patched per-test via
    # ``patch("app.domains.admin.routes.universe_auto_import.get_db_for_tenant")``.
    app.dependency_overrides[get_db_admin] = _fake_db_admin
    transport = ASGITransport(app=app)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.pop(get_db_admin, None)


def _fake_metrics(org_id: str) -> dict:
    return {
        "org_id": org_id,
        "evaluated": 42,
        "added": 30,
        "updated": 5,
        "skipped": 7,
        "skipped_by_reason": {"unclassified": 5, "hybrid_unsupported": 2},
        "duration_ms": 123,
    }


@pytest.mark.asyncio
class TestRunEndpoint:
    async def test_403_for_investment_team(self, client: AsyncClient):
        resp = await client.post(
            f"{BASE}/run",
            json={"org_id": ORG_ID, "reason": "org_provisioning"},
            headers=INVESTMENT_TEAM_HEADER,
        )
        assert resp.status_code == 403

    async def test_422_for_missing_reason(self, client: AsyncClient):
        resp = await client.post(
            f"{BASE}/run",
            json={"org_id": ORG_ID},
            headers=SUPER_ADMIN_HEADER,
        )
        assert resp.status_code == 422

    async def test_422_for_short_reason(self, client: AsyncClient):
        resp = await client.post(
            f"{BASE}/run",
            json={"org_id": ORG_ID, "reason": "xx"},
            headers=SUPER_ADMIN_HEADER,
        )
        assert resp.status_code == 422

    async def test_422_for_bad_uuid(self, client: AsyncClient):
        resp = await client.post(
            f"{BASE}/run",
            json={"org_id": "not-a-uuid", "reason": "org_provisioning"},
            headers=SUPER_ADMIN_HEADER,
        )
        assert resp.status_code == 422

    async def test_happy_path_returns_metrics(self, client: AsyncClient):
        mock_service = AsyncMock(return_value=_fake_metrics(ORG_ID))
        with patch(
            "app.domains.admin.routes.universe_auto_import.auto_import_for_org",
            mock_service,
        ), patch(
            "app.domains.admin.routes.universe_auto_import.get_db_for_tenant",
            _fake_db_for_tenant,
        ):
            resp = await client.post(
                f"{BASE}/run",
                json={"org_id": ORG_ID, "reason": "org_provisioning"},
                headers=SUPER_ADMIN_HEADER,
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["org_id"] == ORG_ID
        assert body["evaluated"] == 42
        assert body["added"] == 30
        assert body["updated"] == 5
        assert body["skipped"] == 7
        assert body["skipped_by_reason"]["unclassified"] == 5
        assert body["aum_floor_usd"] == AUM_FLOOR_USD
        assert body["nav_coverage_min"] == NAV_COVERAGE_MIN
        assert mock_service.await_count == 1
        # reason propagated to service
        call_kwargs = mock_service.await_args.kwargs
        assert call_kwargs["reason"] == "org_provisioning"
        assert call_kwargs["actor_id"] == "super-admin"
        assert "SUPER_ADMIN" in call_kwargs["actor_roles"]


@pytest.mark.asyncio
class TestStatusEndpoint:
    async def test_403_for_investment_team(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/status", headers=INVESTMENT_TEAM_HEADER)
        assert resp.status_code == 403

    async def test_super_admin_returns_shape(self, client: AsyncClient):
        resp = await client.get(f"{BASE}/status", headers=SUPER_ADMIN_HEADER)
        assert resp.status_code == 200
        body = resp.json()
        assert body["aum_floor_usd"] == AUM_FLOOR_USD
        assert body["nav_coverage_min"] == NAV_COVERAGE_MIN
        assert isinstance(body["per_org"], list)
        # Rows may or may not exist depending on DB state; shape must
        # still be valid for the UI regardless of cardinality.
        for row in body["per_org"]:
            uuid.UUID(row["org_id"])
            assert "last_added" in row
            assert "last_updated" in row
            assert "last_skipped" in row
            assert "total_rows" in row

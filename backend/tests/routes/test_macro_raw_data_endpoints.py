"""Tests for Phase 3A macro raw data endpoints.

Covers:
  - Route mounting (401/404 distinction)
  - Auth (INVESTMENT_TEAM gets 200, INVESTOR gets 403)
  - Query parameter validation
  - Empty result handling
  - Schema validation
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

# ── Auth headers ────────────────────────────────────────────────

_TEAM_HEADER = {
    "X-DEV-ACTOR": (
        '{"actor_id": "team-user", "roles": ["INVESTMENT_TEAM"], '
        '"fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}'
    )
}

_ADMIN_HEADER = {
    "X-DEV-ACTOR": (
        '{"actor_id": "admin-user", "roles": ["ADMIN"], '
        '"fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}'
    )
}

_INVESTOR_HEADER = {
    "X-DEV-ACTOR": (
        '{"actor_id": "investor-user", "roles": ["INVESTOR"], '
        '"fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}'
    )
}


# ═══════════════════════════════════════════════════════════════════
#  Route mounting — routes exist (401 not 404)
# ═══════════════════════════════════════════════════════════════════


class TestMacroRawRouteMounting:
    """Verify routes exist (401 not 404)."""

    @pytest.mark.asyncio
    async def test_bis_route_exists(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/macro/bis?country=US&indicator=CREDIT_GAP")
        assert resp.status_code != 404, "BIS route not mounted"

    @pytest.mark.asyncio
    async def test_imf_route_exists(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/macro/imf?country=US&indicator=NGDP_RPCH")
        assert resp.status_code != 404, "IMF route not mounted"

    @pytest.mark.asyncio
    async def test_treasury_route_exists(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/macro/treasury?series=10Y_RATE")
        assert resp.status_code != 404, "Treasury route not mounted"

    @pytest.mark.asyncio
    async def test_ofr_route_exists(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/macro/ofr?metric=HF_LEVERAGE")
        assert resp.status_code != 404, "OFR route not mounted"


# ═══════════════════════════════════════════════════════════════════
#  Auth — INVESTOR role should get 403
# ═══════════════════════════════════════════════════════════════════


class TestMacroRawAuth:
    """Auth: non-team roles should get 403."""

    @pytest.mark.asyncio
    async def test_investor_gets_403_on_bis(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/bis?country=US&indicator=CREDIT_GAP",
            headers=_INVESTOR_HEADER,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_investor_gets_403_on_imf(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/imf?country=US&indicator=NGDP_RPCH",
            headers=_INVESTOR_HEADER,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_investor_gets_403_on_treasury(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/treasury?series=10Y_RATE",
            headers=_INVESTOR_HEADER,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_investor_gets_403_on_ofr(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/ofr?metric=HF_LEVERAGE",
            headers=_INVESTOR_HEADER,
        )
        assert resp.status_code == 403


# ═══════════════════════════════════════════════════════════════════
#  Query parameter validation — missing required params = 422
# ═══════════════════════════════════════════════════════════════════


class TestMacroRawQueryValidation:
    """Missing required query params should yield 422."""

    @pytest.mark.asyncio
    async def test_bis_missing_country(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/bis?indicator=CREDIT_GAP",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_bis_missing_indicator(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/bis?country=US",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_imf_missing_country(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/imf?indicator=NGDP_RPCH",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_imf_missing_indicator(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/imf?country=US",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_treasury_missing_series(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/treasury",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_ofr_missing_metric(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/ofr",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════
#  Empty results — valid request to empty global table = 200 + empty data
# ═══════════════════════════════════════════════════════════════════


class TestMacroRawEmptyResults:
    """Querying non-existent series should return 200 with empty data array."""

    @pytest.mark.asyncio
    async def test_bis_empty_result(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/bis?country=ZZ&indicator=NONEXISTENT",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["country"] == "ZZ"
        assert body["indicator"] == "NONEXISTENT"
        assert body["data"] == []

    @pytest.mark.asyncio
    async def test_imf_empty_result(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/imf?country=ZZ&indicator=NONEXISTENT",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["country"] == "ZZ"
        assert body["indicator"] == "NONEXISTENT"
        assert body["data"] == []

    @pytest.mark.asyncio
    async def test_treasury_empty_result(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/treasury?series=NONEXISTENT_SERIES",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["series"] == "NONEXISTENT_SERIES"
        assert body["data"] == []

    @pytest.mark.asyncio
    async def test_ofr_empty_result(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/ofr?metric=NONEXISTENT_METRIC",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["metric"] == "NONEXISTENT_METRIC"
        assert body["data"] == []


# ═══════════════════════════════════════════════════════════════════
#  Schema validation — response shape matches Pydantic models
# ═══════════════════════════════════════════════════════════════════


class TestMacroRawSchemaShape:
    """Verify response schema shape is correct."""

    @pytest.mark.asyncio
    async def test_bis_response_shape(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/bis?country=US&indicator=CREDIT_GAP",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "country" in body
        assert "indicator" in body
        assert "data" in body
        assert isinstance(body["data"], list)

    @pytest.mark.asyncio
    async def test_imf_response_shape(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/imf?country=US&indicator=NGDP_RPCH",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "country" in body
        assert "indicator" in body
        assert "data" in body
        assert isinstance(body["data"], list)

    @pytest.mark.asyncio
    async def test_treasury_response_shape(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/treasury?series=10Y_RATE",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "series" in body
        assert "data" in body
        assert isinstance(body["data"], list)

    @pytest.mark.asyncio
    async def test_ofr_response_shape(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/ofr?metric=HF_LEVERAGE",
            headers=_TEAM_HEADER,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "metric" in body
        assert "data" in body
        assert isinstance(body["data"], list)


# ═══════════════════════════════════════════════════════════════════
#  Global table access — no organization_id, no RLS
# ═══════════════════════════════════════════════════════════════════


class TestMacroRawGlobalAccess:
    """Endpoints use global tables — any org should get same data."""

    @pytest.mark.asyncio
    async def test_admin_can_access_bis(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/bis?country=US&indicator=CREDIT_GAP",
            headers=_ADMIN_HEADER,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_can_access_imf(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/imf?country=US&indicator=NGDP_RPCH",
            headers=_ADMIN_HEADER,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_can_access_treasury(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/treasury?series=10Y_RATE",
            headers=_ADMIN_HEADER,
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_admin_can_access_ofr(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/macro/ofr?metric=HF_LEVERAGE",
            headers=_ADMIN_HEADER,
        )
        assert resp.status_code == 200

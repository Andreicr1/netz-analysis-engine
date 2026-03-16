"""Tests for investor portal endpoints (Phase B+)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import DEV_ACTOR_HEADER

FUND_ID = str(uuid.uuid4())


def _investor_header() -> dict[str, str]:
    """Dev actor header with INVESTOR role."""
    return {
        "X-DEV-ACTOR": f'{{"actor_id": "investor-user", "roles": ["INVESTOR"], "fund_ids": ["{FUND_ID}"], "org_id": "00000000-0000-0000-0000-000000000001"}}',
    }


def _team_header() -> dict[str, str]:
    """Dev actor header with INVESTMENT_TEAM role (should be rejected by investor portal)."""
    return {
        "X-DEV-ACTOR": f'{{"actor_id": "team-user", "roles": ["INVESTMENT_TEAM"], "fund_ids": ["{FUND_ID}"], "org_id": "00000000-0000-0000-0000-000000000001"}}',
    }


# --- Report Packs ---


@pytest.mark.asyncio
async def test_investor_report_packs_admin(client: AsyncClient):
    """ADMIN can access investor report packs (empty list — no data seeded)."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/report-packs",
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_investor_report_packs_investor_role(client: AsyncClient):
    """INVESTOR role can access investor report packs."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/report-packs",
        headers=_investor_header(),
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


@pytest.mark.asyncio
async def test_investor_report_packs_team_rejected(client: AsyncClient):
    """INVESTMENT_TEAM role is rejected from investor report packs."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/report-packs",
        headers=_team_header(),
    )
    assert response.status_code == 403


# --- Statements ---


@pytest.mark.asyncio
async def test_investor_statements_admin(client: AsyncClient):
    """ADMIN can access investor statements."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/statements",
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_investor_statements_investor_role(client: AsyncClient):
    """INVESTOR role can access investor statements."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/statements",
        headers=_investor_header(),
    )
    assert response.status_code == 200
    assert "items" in response.json()


@pytest.mark.asyncio
async def test_investor_statements_team_rejected(client: AsyncClient):
    """INVESTMENT_TEAM role is rejected from investor statements."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/statements",
        headers=_team_header(),
    )
    assert response.status_code == 403


# --- Documents ---


@pytest.mark.asyncio
async def test_investor_documents_admin(client: AsyncClient):
    """ADMIN can access investor documents."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/documents",
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_investor_documents_investor_role(client: AsyncClient):
    """INVESTOR role can access investor documents."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/documents",
        headers=_investor_header(),
    )
    assert response.status_code == 200
    assert "items" in response.json()


@pytest.mark.asyncio
async def test_investor_documents_team_rejected(client: AsyncClient):
    """INVESTMENT_TEAM role is rejected from investor documents."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/documents",
        headers=_team_header(),
    )
    assert response.status_code == 403


# --- Pagination ---


@pytest.mark.asyncio
async def test_investor_report_packs_pagination(client: AsyncClient):
    """Pagination params are accepted."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/report-packs?limit=10&offset=5",
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_investor_statements_pagination(client: AsyncClient):
    """Pagination params are accepted."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/statements?limit=10&offset=5",
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_investor_documents_pagination(client: AsyncClient):
    """Pagination params are accepted."""
    response = await client.get(
        f"/api/v1/funds/{FUND_ID}/investor/documents?limit=10&offset=5",
        headers=DEV_ACTOR_HEADER,
    )
    assert response.status_code == 200

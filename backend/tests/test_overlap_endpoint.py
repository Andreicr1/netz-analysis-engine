"""Tests for GET /api/v1/model-portfolios/{portfolio_id}/overlap.

Covers:
- 200 with has_sufficient_data=False when no N-PORT data
- 404 when portfolio belongs to another org (RLS)
- limit_pct query param propagation
- 404 for non-existent portfolio
- 422 for limit_pct out of range
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient


def _headers(org_id: str, actor_id: str = "user-1") -> dict[str, str]:
    return {
        "X-DEV-ACTOR": json.dumps({
            "actor_id": actor_id,
            "roles": ["INVESTMENT_TEAM"],
            "fund_ids": [],
            "org_id": org_id,
        }),
    }


@pytest.mark.asyncio
async def test_overlap_404_for_nonexistent_portfolio(client: AsyncClient) -> None:
    """Non-existent portfolio returns 404."""
    org = str(uuid.uuid4())
    resp = await client.get(
        f"/api/v1/model-portfolios/{uuid.uuid4()}/overlap",
        headers=_headers(org),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_overlap_empty_when_no_nport(client: AsyncClient) -> None:
    """Portfolio with no fund_selection_schema returns 200 with empty overlap."""
    org = str(uuid.uuid4())
    h = _headers(org)

    create_resp = await client.post(
        "/api/v1/model-portfolios",
        headers=h,
        json={"profile": "moderate", "display_name": "Test Overlap Portfolio"},
    )
    assert create_resp.status_code == 201
    portfolio_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/model-portfolios/{portfolio_id}/overlap",
        headers=h,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_sufficient_data"] is False
    assert data["total_holdings"] == 0
    assert data["funds_analyzed"] == 0
    assert isinstance(data["top_cusip_exposures"], list)
    assert isinstance(data["sector_exposures"], list)
    assert isinstance(data["breaches"], list)


@pytest.mark.asyncio
async def test_overlap_rls_cross_org(client: AsyncClient) -> None:
    """Portfolio created by one org is not accessible by another org."""
    org_a = str(uuid.uuid4())
    org_b = str(uuid.uuid4())

    create_resp = await client.post(
        "/api/v1/model-portfolios",
        headers=_headers(org_a),
        json={"profile": "conservative", "display_name": "RLS Test Portfolio"},
    )
    assert create_resp.status_code == 201
    portfolio_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/model-portfolios/{portfolio_id}/overlap",
        headers=_headers(org_b, actor_id="user-2"),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_overlap_limit_pct_param(client: AsyncClient) -> None:
    """limit_pct query param is reflected in response."""
    org = str(uuid.uuid4())
    h = _headers(org)

    create_resp = await client.post(
        "/api/v1/model-portfolios",
        headers=h,
        json={"profile": "growth", "display_name": "Limit PCT Test Portfolio"},
    )
    assert create_resp.status_code == 201
    portfolio_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/model-portfolios/{portfolio_id}/overlap?limit_pct=0.10",
        headers=h,
    )
    assert resp.status_code == 200
    assert resp.json()["limit_pct"] == 0.10


@pytest.mark.asyncio
async def test_overlap_limit_pct_validation(client: AsyncClient) -> None:
    """limit_pct out of range returns 422 (validated before DB access)."""
    org = str(uuid.uuid4())
    resp = await client.get(
        f"/api/v1/model-portfolios/{uuid.uuid4()}/overlap?limit_pct=0.99",
        headers=_headers(org),
    )
    assert resp.status_code == 422

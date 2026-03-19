"""Tests for credit deal cashflow endpoints — route wiring + auth (no DB required).

Validates that the 6 cashflow endpoints are mounted, accept correct params,
and enforce authentication. Route-exists tests verify 401 (not 404), proving
the route is mounted without requiring a live database.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

FUND_ID = "00000000-0000-0000-0000-000000000099"
DEAL_ID = "00000000-0000-0000-0000-000000000088"
CASHFLOW_ID = "00000000-0000-0000-0000-000000000077"
BASE = "/api/v1/pipeline/deals"

_CASHFLOW_BODY = {
    "flow_type": "disbursement",
    "amount": 100000,
    "currency": "USD",
    "flow_date": "2026-01-15",
}


# ── List cashflows ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_cashflows_requires_auth(client: AsyncClient):
    resp = await client.get(f"{BASE}/{DEAL_ID}/cashflows", params={"fund_id": FUND_ID})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_cashflows_route_exists(client: AsyncClient):
    """Route exists — 401 (not 404) proves the router is mounted."""
    resp = await client.get(f"{BASE}/{DEAL_ID}/cashflows", params={"fund_id": FUND_ID})
    assert resp.status_code != 404


# ── Create cashflow ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_cashflow_requires_auth(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/{DEAL_ID}/cashflows",
        params={"fund_id": FUND_ID},
        json=_CASHFLOW_BODY,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_cashflow_route_exists(client: AsyncClient):
    resp = await client.post(
        f"{BASE}/{DEAL_ID}/cashflows",
        params={"fund_id": FUND_ID},
        json=_CASHFLOW_BODY,
    )
    assert resp.status_code != 404


# ── Update cashflow ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_cashflow_requires_auth(client: AsyncClient):
    resp = await client.patch(
        f"{BASE}/{DEAL_ID}/cashflows/{CASHFLOW_ID}",
        params={"fund_id": FUND_ID},
        json=_CASHFLOW_BODY,
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_update_cashflow_route_exists(client: AsyncClient):
    resp = await client.patch(
        f"{BASE}/{DEAL_ID}/cashflows/{CASHFLOW_ID}",
        params={"fund_id": FUND_ID},
        json=_CASHFLOW_BODY,
    )
    assert resp.status_code != 404


# ── Delete cashflow ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_cashflow_requires_auth(client: AsyncClient):
    resp = await client.delete(
        f"{BASE}/{DEAL_ID}/cashflows/{CASHFLOW_ID}",
        params={"fund_id": FUND_ID},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_delete_cashflow_route_exists(client: AsyncClient):
    resp = await client.delete(
        f"{BASE}/{DEAL_ID}/cashflows/{CASHFLOW_ID}",
        params={"fund_id": FUND_ID},
    )
    assert resp.status_code != 404


# ── Performance metrics ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_performance_requires_auth(client: AsyncClient):
    resp = await client.get(
        f"{BASE}/{DEAL_ID}/performance",
        params={"fund_id": FUND_ID},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_performance_route_exists(client: AsyncClient):
    resp = await client.get(f"{BASE}/{DEAL_ID}/performance", params={"fund_id": FUND_ID})
    assert resp.status_code != 404


# ── Monitoring metrics ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_monitoring_requires_auth(client: AsyncClient):
    resp = await client.get(
        f"{BASE}/{DEAL_ID}/monitoring",
        params={"fund_id": FUND_ID},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_monitoring_route_exists(client: AsyncClient):
    resp = await client.get(f"{BASE}/{DEAL_ID}/monitoring", params={"fund_id": FUND_ID})
    assert resp.status_code != 404

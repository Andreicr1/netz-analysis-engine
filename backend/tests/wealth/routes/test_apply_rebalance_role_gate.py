"""Role gate tests for POST /rebalancing/proposals/{id}/apply.

PR-Q98: Verify that investor-role users are rejected (403) and
IC-role users pass the role gate (not 403).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

_PROPOSAL_ID = str(uuid.uuid4())


def _investor_header() -> dict[str, str]:
    """Dev actor header with INVESTOR role (read-only)."""
    return {
        "X-DEV-ACTOR": (
            '{"actor_id": "investor-user", "roles": ["INVESTOR"],'
            ' "fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}'
        ),
    }


def _ic_header() -> dict[str, str]:
    """Dev actor header with INVESTMENT_TEAM role."""
    return {
        "X-DEV-ACTOR": (
            '{"actor_id": "ic-user", "roles": ["INVESTMENT_TEAM"],'
            ' "fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}'
        ),
    }


@pytest.mark.asyncio
async def test_apply_rebalance_rejects_investor_role(client: AsyncClient):
    """INVESTOR role must be rejected with 403 — privilege escalation guard."""
    resp = await client.post(
        f"/api/v1/rebalancing/proposals/{_PROPOSAL_ID}/apply",
        headers=_investor_header(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_apply_rebalance_accepts_ic_role(client: AsyncClient):
    """INVESTMENT_TEAM role passes role gate — 404 expected (no seeded proposal)."""
    resp = await client.post(
        f"/api/v1/rebalancing/proposals/{_PROPOSAL_ID}/apply",
        headers=_ic_header(),
    )
    # Role gate passed; handler returns 404 because proposal doesn't exist
    assert resp.status_code != 403
    assert resp.status_code in (200, 202, 404)

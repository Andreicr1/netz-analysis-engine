"""Role gate tests for DD trigger and regenerate endpoints.

PR-Q101: Verify that investor-role users are rejected (403) on
trigger_dd_report and regenerate_dd_report, while IC-role users
pass the role gate.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

_FUND_ID = str(uuid.uuid4())
_REPORT_ID = str(uuid.uuid4())


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


# ---- trigger_dd_report ----


@pytest.mark.asyncio
async def test_trigger_dd_report_rejects_investor_role(client: AsyncClient):
    """INVESTOR role must be rejected with 403 on DD trigger."""
    resp = await client.post(
        f"/api/v1/dd-reports/funds/{_FUND_ID}",
        headers=_investor_header(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_trigger_dd_report_accepts_investment_team(client: AsyncClient):
    """INVESTMENT_TEAM role passes role gate -- 404 expected (no seeded fund)."""
    resp = await client.post(
        f"/api/v1/dd-reports/funds/{_FUND_ID}",
        headers=_ic_header(),
    )
    # Role gate passed; handler returns 404 because fund doesn't exist
    assert resp.status_code != 403
    assert resp.status_code in (200, 202, 404)


# ---- regenerate_dd_report ----


@pytest.mark.asyncio
async def test_regenerate_dd_report_rejects_investor_role(client: AsyncClient):
    """INVESTOR role must be rejected with 403 on DD regenerate."""
    resp = await client.post(
        f"/api/v1/dd-reports/{_REPORT_ID}/regenerate",
        headers=_investor_header(),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_regenerate_dd_report_accepts_investment_team(client: AsyncClient):
    """INVESTMENT_TEAM role passes role gate -- 404 expected (no seeded report)."""
    resp = await client.post(
        f"/api/v1/dd-reports/{_REPORT_ID}/regenerate",
        headers=_ic_header(),
    )
    # Role gate passed; handler returns 404 because report doesn't exist
    assert resp.status_code != 403
    assert resp.status_code in (200, 202, 404)

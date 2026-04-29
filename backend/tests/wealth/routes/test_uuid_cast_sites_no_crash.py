"""Smoke tests for the 5 UUID cast crash sites fixed by PR-Q96.

Each test sends a minimal valid request to the affected route handler
and asserts that the response is NOT a 500 Internal Server Error.
Some routes may legitimately return 4xx (missing entities, feature
disabled, etc.), but the bug was a 500 with ``AttributeError:
'UUID' object has no attribute 'replace'`` caused by
``uuid.UUID(org_id)`` when ``org_id`` was already a ``uuid.UUID``
from ``get_org_id``.

Wave 6 Session 09 — C-03 (Crit).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from tests.conftest import DEV_ACTOR_HEADER

_FAKE_UUID = str(uuid.uuid4())


# ── Site 1: instruments.py:229 ────────────────────────────────────


@pytest.mark.asyncio
async def test_update_instrument_org_does_not_crash_on_uuid_org(client: AsyncClient):
    """PATCH /instruments/{id}/org must not crash with UUID org_id."""
    resp = await client.patch(
        f"/api/v1/instruments/{_FAKE_UUID}/org",
        json={"block_id": "test-block"},
        headers=DEV_ACTOR_HEADER,
    )
    # 404 (instrument not found) is expected; 500 is the bug.
    assert resp.status_code != 500, f"UUID cast crash: {resp.text}"


# ── Site 2 & 3: content.py:403,443 ───────────────────────────────


@pytest.mark.asyncio
async def test_trigger_outlook_does_not_crash_on_uuid_org(client: AsyncClient):
    """POST /content/outlooks must not crash with UUID org_id."""
    resp = await client.post(
        "/api/v1/content/outlooks",
        headers=DEV_ACTOR_HEADER,
    )
    # 501 (feature disabled) is expected in test env; 500 is the bug.
    assert resp.status_code != 500, f"UUID cast crash: {resp.text}"


@pytest.mark.asyncio
async def test_trigger_flash_report_does_not_crash_on_uuid_org(client: AsyncClient):
    """POST /content/flash-reports must not crash with UUID org_id."""
    resp = await client.post(
        "/api/v1/content/flash-reports",
        headers=DEV_ACTOR_HEADER,
    )
    # 501 (feature disabled) is expected in test env; 500 is the bug.
    assert resp.status_code != 500, f"UUID cast crash: {resp.text}"


# ── Site 4: builder.py:121 (_set_rls_org) ─────────────────────────


@pytest.mark.asyncio
async def test_build_portfolio_does_not_crash_on_uuid_org(client: AsyncClient):
    """POST /portfolios/{id}/build must not crash with UUID org_id."""
    resp = await client.post(
        f"/api/v1/portfolios/{_FAKE_UUID}/build",
        headers=DEV_ACTOR_HEADER,
    )
    # 202 (accepted) or 4xx (not found, etc.) are fine; 500 is the bug.
    assert resp.status_code != 500, f"UUID cast crash: {resp.text}"


# ── Site 5: builder.py:220 (execute_construction_run) ─────────────


@pytest.mark.asyncio
async def test_preview_cvar_does_not_crash_on_uuid_org(client: AsyncClient):
    """POST /portfolios/{id}/preview-cvar must not crash with UUID org_id."""
    resp = await client.post(
        f"/api/v1/portfolios/{_FAKE_UUID}/preview-cvar",
        json={"cvar_limit": 0.05},
        headers=DEV_ACTOR_HEADER,
    )
    # 404 (portfolio not found) or 4xx are fine; 500 is the bug.
    assert resp.status_code != 500, f"UUID cast crash: {resp.text}"

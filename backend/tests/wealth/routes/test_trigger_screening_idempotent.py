"""Idempotency tests for POST /screener/run (PR-Q95).

Verifies that re-running trigger_screening for the same instrument does
not raise IntegrityError on the partial unique index
uq_screening_results_current.  The route must set is_current=False on
prior rows before inserting new is_current=True rows.

Runs against real Docker-compose PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db.engine import async_session_factory

# Deterministic test UUIDs (q95 prefix — never conflicts with real tenants)
_ORG_ID = uuid.UUID("09500000-0000-0000-0000-000000000001")
_INSTRUMENT_ID = uuid.UUID("09500000-0000-0000-0000-000000000010")
_INSTRUMENT_ORG_ID = uuid.UUID("09500000-0000-0000-0000-000000000011")

_DEV_HEADER = {
    "X-DEV-ACTOR": json.dumps({
        "actor_id": "q95-test",
        "roles": ["ADMIN"],
        "fund_ids": [],
        "org_id": str(_ORG_ID),
    }),
}

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture(scope="module")
async def _seed_q95():
    """Seed a minimal instrument + instruments_org for trigger_screening."""
    async with async_session_factory() as db:
        await db.execute(
            text("SELECT set_config('app.current_organization_id', :oid, true)"),
            {"oid": str(_ORG_ID)},
        )

        # instruments_universe (global, no RLS)
        await db.execute(
            text("""
                INSERT INTO instruments_universe
                    (instrument_id, instrument_type, name, ticker, asset_class,
                     geography, currency, is_active, attributes)
                VALUES
                    (:iid, 'fund', 'Q95 Idempotency Test Fund', 'Q95TST', 'equity',
                     'US', 'USD', true,
                     CAST(:attrs AS jsonb))
                ON CONFLICT (instrument_id) DO NOTHING
            """),
            {
                "iid": _INSTRUMENT_ID,
                "attrs": json.dumps({
                    "aum_usd": 500_000_000,
                    "manager_name": "Q95 Test",
                    "inception_date": "2020-01-01",
                }),
            },
        )

        # instruments_org (org-scoped)
        await db.execute(
            text("""
                INSERT INTO instruments_org
                    (id, instrument_id, organization_id, block_id, approval_status)
                VALUES
                    (:ioid, :iid, :oid, NULL, 'watchlist')
                ON CONFLICT (id) DO NOTHING
            """),
            {"ioid": _INSTRUMENT_ORG_ID, "iid": _INSTRUMENT_ID, "oid": _ORG_ID},
        )

        await db.commit()

    yield

    # Teardown (FK-safe order)
    async with async_session_factory() as db:
        await db.execute(
            text("""
                DELETE FROM screening_results
                WHERE run_id IN (
                    SELECT run_id FROM screening_runs WHERE organization_id = :oid
                )
            """),
            {"oid": _ORG_ID},
        )
        await db.execute(
            text("DELETE FROM screening_runs WHERE organization_id = :oid"),
            {"oid": _ORG_ID},
        )
        await db.execute(
            text("DELETE FROM instruments_org WHERE organization_id = :oid"),
            {"oid": _ORG_ID},
        )
        await db.execute(
            text("DELETE FROM instruments_universe WHERE instrument_id = :iid"),
            {"iid": _INSTRUMENT_ID},
        )
        await db.commit()


@pytest.fixture(scope="module")
async def q95_client():
    """Async HTTP client for screener route testing."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Tests ────────────────────────────────────────────────────────


async def test_screening_rerun_no_integrity_error(
    _seed_q95,
    q95_client: AsyncClient,
):
    """Two consecutive trigger_screening calls for the same instrument
    must both succeed (no IntegrityError on uq_screening_results_current).

    After re-run: exactly 1 is_current=True row, at least 1 is_current=False row.
    """
    payload = {"instrument_ids": [str(_INSTRUMENT_ID)]}

    # First run
    resp1 = await q95_client.post(
        "/api/v1/screener/run",
        json=payload,
        headers=_DEV_HEADER,
    )
    assert resp1.status_code == 202, f"First run failed: {resp1.text}"

    # Second run (would crash pre-fix with IntegrityError)
    resp2 = await q95_client.post(
        "/api/v1/screener/run",
        json=payload,
        headers=_DEV_HEADER,
    )
    assert resp2.status_code == 202, f"Second run failed: {resp2.text}"

    # Verify DB state
    async with async_session_factory() as db:
        await db.execute(
            text("SELECT set_config('app.current_organization_id', :oid, true)"),
            {"oid": str(_ORG_ID)},
        )

        current = await db.execute(
            text("""
                SELECT count(*) FROM screening_results
                WHERE instrument_id = :iid
                  AND organization_id = :oid
                  AND is_current = true
            """),
            {"iid": _INSTRUMENT_ID, "oid": _ORG_ID},
        )
        current_count = current.scalar_one()

        historical = await db.execute(
            text("""
                SELECT count(*) FROM screening_results
                WHERE instrument_id = :iid
                  AND organization_id = :oid
                  AND is_current = false
            """),
            {"iid": _INSTRUMENT_ID, "oid": _ORG_ID},
        )
        historical_count = historical.scalar_one()

    assert current_count == 1, (
        f"Expected exactly 1 is_current=True row, got {current_count}"
    )
    assert historical_count >= 1, (
        f"Expected at least 1 is_current=False row (the prior run), got {historical_count}"
    )


async def test_screening_concurrent_runs_serialized(
    _seed_q95,
    q95_client: AsyncClient,
):
    """Two concurrent trigger_screening calls for the same instrument
    both succeed — transaction serialization prevents duplicates.

    Final state: exactly 1 is_current=True row.
    """
    payload = {"instrument_ids": [str(_INSTRUMENT_ID)]}

    async def _fire():
        return await q95_client.post(
            "/api/v1/screener/run",
            json=payload,
            headers=_DEV_HEADER,
        )

    r1, r2 = await asyncio.gather(_fire(), _fire())

    # Both must succeed (202) — no IntegrityError
    assert r1.status_code == 202, f"Concurrent run 1 failed: {r1.text}"
    assert r2.status_code == 202, f"Concurrent run 2 failed: {r2.text}"

    # Final state: exactly 1 current row
    async with async_session_factory() as db:
        await db.execute(
            text("SELECT set_config('app.current_organization_id', :oid, true)"),
            {"oid": str(_ORG_ID)},
        )

        current = await db.execute(
            text("""
                SELECT count(*) FROM screening_results
                WHERE instrument_id = :iid
                  AND organization_id = :oid
                  AND is_current = true
            """),
            {"iid": _INSTRUMENT_ID, "oid": _ORG_ID},
        )
        current_count = current.scalar_one()

    assert current_count == 1, (
        f"Expected exactly 1 is_current=True row after concurrent runs, got {current_count}"
    )

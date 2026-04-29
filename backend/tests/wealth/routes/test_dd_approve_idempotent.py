"""Idempotency tests for POST /dd-reports/{id}/approve (PR-Q100).

Verifies that approve_dd_report clears prior is_current=True rows in
universe_approvals before inserting the new approval.  Without this fix,
re-approval after reject->regenerate would violate the partial unique
index on (organization_id, instrument_id) WHERE is_current=true.

Runs against real Docker-compose PostgreSQL.
"""

from __future__ import annotations

import json
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db.engine import async_session_factory

# Deterministic test UUIDs (q100 prefix -- never conflicts with real tenants)
_ORG_ID = uuid.UUID("01000000-0000-0000-0000-000000000001")
_INSTRUMENT_ID = uuid.UUID("01000000-0000-0000-0000-000000000010")
_INSTRUMENT_ORG_ID = uuid.UUID("01000000-0000-0000-0000-000000000011")
_DD_REPORT_ID = uuid.UUID("01000000-0000-0000-0000-000000000020")
_DD_CHAPTER_ID = uuid.UUID("01000000-0000-0000-0000-000000000030")
_PRIOR_APPROVAL_ID = uuid.UUID("01000000-0000-0000-0000-000000000040")

_CREATOR = "q100-creator"
_APPROVER = "q100-approver"

_DEV_HEADER = {
    "X-DEV-ACTOR": json.dumps({
        "actor_id": _APPROVER,
        "roles": ["INVESTMENT_TEAM"],
        "fund_ids": [],
        "org_id": str(_ORG_ID),
    }),
}

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


# -- Fixtures ---------------------------------------------------------------


@pytest.fixture(scope="module")
async def _seed_q100():
    """Seed instrument, instruments_org, dd_report, dd_chapter, prior approval."""
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
                    (:iid, 'fund', 'Q100 Idempotency Test Fund', 'Q100T', 'equity',
                     'US', 'USD', true,
                     CAST(:attrs AS jsonb))
                ON CONFLICT (instrument_id) DO NOTHING
            """),
            {
                "iid": _INSTRUMENT_ID,
                "attrs": json.dumps({
                    "aum_usd": 500_000_000,
                    "manager_name": "Q100 Test Manager",
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
                    (:ioid, :iid, :oid, NULL, 'pending')
                ON CONFLICT (id) DO NOTHING
            """),
            {"ioid": _INSTRUMENT_ORG_ID, "iid": _INSTRUMENT_ID, "oid": _ORG_ID},
        )

        # dd_reports -- status=pending_approval, created_by != approver
        await db.execute(
            text("""
                INSERT INTO dd_reports
                    (id, instrument_id, organization_id, report_type, version,
                     status, is_current, schema_version, created_by)
                VALUES
                    (:rid, :iid, :oid, 'dd_report', 1,
                     'pending_approval', true, 1, :creator)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "rid": _DD_REPORT_ID,
                "iid": _INSTRUMENT_ID,
                "oid": _ORG_ID,
                "creator": _CREATOR,
            },
        )

        # dd_chapters (at least one, composite FK requires matching org_id)
        await db.execute(
            text("""
                INSERT INTO dd_chapters
                    (id, dd_report_id, organization_id, chapter_tag,
                     chapter_order, content_md)
                VALUES
                    (:cid, :rid, :oid, 'summary', 1, '## Summary\nTest content.')
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "cid": _DD_CHAPTER_ID,
                "rid": _DD_REPORT_ID,
                "oid": _ORG_ID,
            },
        )

        # Pre-existing universe_approval with is_current=True (simulates
        # prior approval that should be superseded on re-approval)
        await db.execute(
            text("""
                INSERT INTO universe_approvals
                    (id, instrument_id, organization_id, decision,
                     is_current, created_by, decided_by)
                VALUES
                    (:aid, :iid, :oid, 'approved',
                     true, :creator, :creator)
                ON CONFLICT (id) DO NOTHING
            """),
            {
                "aid": _PRIOR_APPROVAL_ID,
                "iid": _INSTRUMENT_ID,
                "oid": _ORG_ID,
                "creator": _CREATOR,
            },
        )

        await db.commit()

    yield

    # Teardown (FK-safe order)
    async with async_session_factory() as db:
        await db.execute(
            text("DELETE FROM universe_approvals WHERE organization_id = :oid"),
            {"oid": _ORG_ID},
        )
        await db.execute(
            text("DELETE FROM dd_chapters WHERE organization_id = :oid"),
            {"oid": _ORG_ID},
        )
        await db.execute(
            text("DELETE FROM dd_reports WHERE organization_id = :oid"),
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
async def q100_client():
    """Async HTTP client for DD report route testing."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# -- Tests -------------------------------------------------------------------


async def test_dd_approve_clears_prior_current_approval(
    _seed_q100,
    q100_client: AsyncClient,
):
    """Approving a DD report when a prior is_current=True approval exists
    must clear the prior row and insert a new is_current=True row.

    After approval: exactly 1 is_current=True, at least 1 is_current=False.
    No IntegrityError on the partial unique index.
    """
    resp = await q100_client.post(
        f"/api/v1/dd-reports/{_DD_REPORT_ID}/approve",
        json={"rationale": "Approved after full committee review — idempotency test"},
        headers=_DEV_HEADER,
    )
    assert resp.status_code == 200, f"Approval failed: {resp.text}"

    # Verify DB state
    async with async_session_factory() as db:
        await db.execute(
            text("SELECT set_config('app.current_organization_id', :oid, true)"),
            {"oid": str(_ORG_ID)},
        )

        current = await db.execute(
            text("""
                SELECT count(*) FROM universe_approvals
                WHERE instrument_id = :iid
                  AND organization_id = :oid
                  AND is_current = true
            """),
            {"iid": _INSTRUMENT_ID, "oid": _ORG_ID},
        )
        current_count = current.scalar_one()

        historical = await db.execute(
            text("""
                SELECT count(*) FROM universe_approvals
                WHERE instrument_id = :iid
                  AND organization_id = :oid
                  AND is_current = false
            """),
            {"iid": _INSTRUMENT_ID, "oid": _ORG_ID},
        )
        historical_count = historical.scalar_one()

    assert current_count == 1, (
        f"Expected exactly 1 is_current=True approval, got {current_count}"
    )
    assert historical_count >= 1, (
        f"Expected at least 1 is_current=False (the prior approval), got {historical_count}"
    )


async def test_dd_approve_after_reject_regenerate_cycle(
    _seed_q100,
    q100_client: AsyncClient,
):
    """Simulates reject -> regenerate -> re-approve cycle.

    After the first test already approved, we reset the report to
    pending_approval and approve again.  Must still yield exactly 1
    is_current=True row (the latest approval).
    """
    # Reset report to pending_approval for re-approval
    async with async_session_factory() as db:
        await db.execute(
            text("SELECT set_config('app.current_organization_id', :oid, true)"),
            {"oid": str(_ORG_ID)},
        )
        await db.execute(
            text("""
                UPDATE dd_reports
                SET status = 'pending_approval',
                    approved_by = NULL,
                    approved_at = NULL,
                    rejection_reason = NULL
                WHERE id = :rid
            """),
            {"rid": _DD_REPORT_ID},
        )
        await db.commit()

    # Second approval
    resp = await q100_client.post(
        f"/api/v1/dd-reports/{_DD_REPORT_ID}/approve",
        json={"rationale": "Re-approved after reject-regenerate cycle — idempotency test"},
        headers=_DEV_HEADER,
    )
    assert resp.status_code == 200, f"Re-approval failed: {resp.text}"

    # Verify DB state: exactly 1 is_current=True
    async with async_session_factory() as db:
        await db.execute(
            text("SELECT set_config('app.current_organization_id', :oid, true)"),
            {"oid": str(_ORG_ID)},
        )

        current = await db.execute(
            text("""
                SELECT count(*) FROM universe_approvals
                WHERE instrument_id = :iid
                  AND organization_id = :oid
                  AND is_current = true
            """),
            {"iid": _INSTRUMENT_ID, "oid": _ORG_ID},
        )
        current_count = current.scalar_one()

        total = await db.execute(
            text("""
                SELECT count(*) FROM universe_approvals
                WHERE instrument_id = :iid
                  AND organization_id = :oid
            """),
            {"iid": _INSTRUMENT_ID, "oid": _ORG_ID},
        )
        total_count = total.scalar_one()

    assert current_count == 1, (
        f"Expected exactly 1 is_current=True after re-approval, got {current_count}"
    )
    # Should have at least 3 rows total: seed + first approval + second approval
    assert total_count >= 3, (
        f"Expected at least 3 total approval rows, got {total_count}"
    )

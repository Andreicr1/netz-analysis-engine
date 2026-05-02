"""PR-BE-3 — audit_events Option A cross-tenant leak regression.

The ``audit_events`` table is a TimescaleDB hypertable with columnstore
enabled (migration 0030). Postgres rejects ``ENABLE/FORCE ROW LEVEL
SECURITY`` while columnstore is on (PR-Q11 Phase 5 incompatibility), so
the table runs with ``rowsecurity = false`` even though migration
0195_q92 carries an org-isolation policy. The institutional pattern
(Option A) is therefore:

    - WRITE side: ``write_audit_event()`` injects ``organization_id``
      from the active ``SET LOCAL`` RLS context — every writer is
      forced through the helper.
    - READ side: every callsite must explicitly include
      ``WHERE organization_id = :org`` (the policy is **not** what
      keeps tenants apart at runtime).

This test materialises the contract end-to-end so a future regression
that drops the WHERE clause cannot ship silently:

    1. Insert one audit row with ``write_audit_event()`` while RLS
       context is set to ORG_A.
    2. Re-open a session with RLS context set to ORG_B. The same
       SELECT *with* ``WHERE organization_id = :org`` returns 0 rows —
       the institutional pattern works.
    3. Re-open another session with RLS context set to ORG_B. The same
       SELECT *without* the WHERE clause returns >= 1 row — proving
       the table itself does NOT enforce isolation, which is the
       reason every reader callsite must filter explicitly.
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db.audit import write_audit_event
from app.core.db.engine import async_session_factory as async_session


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


_ORG_A = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
_ORG_B = uuid.UUID("00000000-0000-0000-0000-0000000000b1")


@pytest.mark.asyncio
async def test_audit_events_cross_tenant_isolation_via_where_clause():
    """Helper-write + WHERE-filter-read keeps tenants isolated."""
    sentinel = f"pr_be_3_xtenant_{uuid.uuid4().hex[:8]}"

    # --- 1. Write one row in ORG_A's context. ---
    async with async_session() as db:
        # SET LOCAL is transaction-scoped; the helper resolves
        # organization_id from this exact session.
        await db.execute(
            text(f"SET LOCAL app.current_organization_id = '{_ORG_A}'"),
        )
        await write_audit_event(
            db,
            action="test_be3_xtenant",
            entity_type="ModelPortfolio",
            entity_id=sentinel,
            actor_id="tester-a",
            after={"sentinel": sentinel, "org": "A"},
        )
        await db.commit()

    try:
        # --- 2. ORG_B reader WITH explicit organization_id filter. ---
        async with async_session() as db:
            await db.execute(
                text(f"SET LOCAL app.current_organization_id = '{_ORG_B}'"),
            )
            result = await db.execute(
                text(
                    """
                    SELECT count(*) FROM audit_events
                     WHERE entity_id = :sentinel
                       AND organization_id = :org_b
                    """,
                ),
                {"sentinel": sentinel, "org_b": _ORG_B},
            )
            count_filtered = result.scalar()
        assert count_filtered == 0, (
            "audit_events MUST be invisible to other tenants when the "
            "reader applies the WHERE organization_id filter"
        )

        # --- 3. ORG_B reader WITHOUT the filter sees the row. ---
        # We use a raw asyncpg connection so SQLAlchemy session caches
        # cannot mask the leak: this is the worst-case "code skipped
        # the WHERE clause" scenario, and we want to *see* the row to
        # justify the institutional Option-A pattern.
        conn = await asyncpg.connect(_asyncpg_dsn())
        try:
            await conn.execute(
                f"SET app.current_organization_id = '{_ORG_B}'",
            )
            count_unfiltered = await conn.fetchval(
                "SELECT count(*) FROM audit_events WHERE entity_id = $1",
                sentinel,
            )
        finally:
            await conn.close()
        assert count_unfiltered >= 1, (
            "WITHOUT a WHERE organization_id filter, audit_events does "
            "leak across tenants — this is precisely why CLAUDE.md "
            "mandates Option A (helper-write + explicit reader filter)"
        )
    finally:
        # Cleanup — keep the table clean for repeat runs.
        conn = await asyncpg.connect(_asyncpg_dsn())
        try:
            await conn.execute(
                "DELETE FROM audit_events WHERE entity_id = $1",
                sentinel,
            )
        finally:
            await conn.close()

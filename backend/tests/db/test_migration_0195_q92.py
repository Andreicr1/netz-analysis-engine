"""PR-Q92 — audit_events.organization_id nullable + allow_global gate.

Validates the global-audit contract:
- audit_events.organization_id can hold NULL for global pipeline events.
- write_audit_event(allow_global=True) writes NULL successfully.
- write_audit_event(allow_global=False, RLS empty) raises ValueError —
  prevents tenant code from silently producing orphan audit rows.
"""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings
from app.core.db.audit import write_audit_event
from app.core.db.engine import async_session_factory as async_session


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.mark.asyncio
async def test_audit_events_organization_id_is_nullable():
    """organization_id must be NULLABLE post-migration 0195."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        is_nullable = await conn.fetchval(
            """
            SELECT is_nullable
            FROM information_schema.columns
            WHERE table_name = 'audit_events'
              AND column_name = 'organization_id'
            """
        )
    finally:
        await conn.close()
    assert is_nullable == "YES", (
        "audit_events.organization_id must be nullable to support global "
        "pipeline events (factor model, macro ingestion, benchmark_ingest)"
    )


@pytest.mark.asyncio
async def test_write_audit_event_allow_global_writes_null_org():
    """allow_global=True writes a row with organization_id=NULL."""
    async with async_session() as db:
        await write_audit_event(
            db,
            action="test_q92_global",
            entity_type="factor_model",
            entity_id="test_global_event",
            after={"smoke": "test"},
            allow_global=True,
        )
        await db.commit()

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            """
            SELECT organization_id, action, entity_id
            FROM audit_events
            WHERE action = 'test_q92_global'
              AND entity_id = 'test_global_event'
            ORDER BY created_at DESC LIMIT 1
            """
        )
        # Cleanup
        await conn.execute(
            "DELETE FROM audit_events WHERE action = 'test_q92_global'",
        )
    finally:
        await conn.close()
    assert row is not None, "global audit row was not persisted"
    assert row["organization_id"] is None, (
        "expected organization_id=NULL for global event"
    )


@pytest.mark.asyncio
async def test_write_audit_event_without_global_flag_raises_when_no_org():
    """allow_global=False (default) must raise when RLS context is empty —
    prevents tenant code from silently producing orphan audit rows."""
    async with async_session() as db:
        with pytest.raises(ValueError, match="organization_id"):
            await write_audit_event(
                db,
                action="test_q92_orphan_check",
                entity_type="factor_model",
                entity_id="should_never_persist",
                after={"smoke": "negative"},
                # allow_global omitted -> defaults to False
            )


@pytest.mark.asyncio
async def test_factor_model_writes_global_audit_on_data_gap():
    """End-to-end: factor model run produces at least one factor_data_gap
    audit row with organization_id=NULL (no audit_failed warnings)."""
    import datetime as dt

    from quant_engine.factor_model_service import build_fundamental_factor_returns

    end = dt.date(2026, 4, 28)
    start = end - dt.timedelta(days=365)
    async with async_session() as db:
        await build_fundamental_factor_returns(db, start, end)
        await db.commit()

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM audit_events
            WHERE entity_type = 'factor_model'
              AND organization_id IS NULL
              AND created_at >= NOW() - INTERVAL '5 minutes'
            """
        )
    finally:
        await conn.close()
    assert count >= 1, (
        f"expected at least one factor_model audit row with org=NULL, got {count}"
    )

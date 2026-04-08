"""Assert migration 0098 created the model_portfolio lifecycle state machine.

Verifies (per Phase 1 Task 1.1 of the portfolio enterprise plan):

- The 4 new state machine columns exist on ``model_portfolios``
- The CHECK constraint on ``state`` enumerates exactly the 8 canonical values
- The ``portfolio_state_transitions`` audit table exists with the expected
  shape (PK, FK with CASCADE, columns, indexes)
- RLS is enabled with the subselect-wrapped policy
- The two indexes (``ix_pst_portfolio_created``, ``ix_pst_org_created``) exist
- Backfill populated ``state`` for any pre-existing portfolio rows
"""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


_EXPECTED_STATES = {
    "draft",
    "constructed",
    "validated",
    "approved",
    "live",
    "paused",
    "archived",
    "rejected",
}


@pytest.mark.asyncio
async def test_model_portfolios_state_columns_exist():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_name = 'model_portfolios'
              AND column_name IN ('state', 'state_metadata', 'state_changed_at', 'state_changed_by')
            ORDER BY column_name
            """,
        )
    finally:
        await conn.close()

    by_name = {r["column_name"]: r for r in rows}
    assert set(by_name.keys()) == {
        "state",
        "state_metadata",
        "state_changed_at",
        "state_changed_by",
    }, f"missing state columns: {set(by_name.keys())}"

    # state — text NOT NULL DEFAULT 'draft'
    assert by_name["state"]["data_type"] == "text"
    assert by_name["state"]["is_nullable"] == "NO"
    assert by_name["state"]["column_default"] is not None
    assert "draft" in by_name["state"]["column_default"]

    # state_metadata — jsonb NOT NULL DEFAULT '{}'
    assert by_name["state_metadata"]["data_type"] == "jsonb"
    assert by_name["state_metadata"]["is_nullable"] == "NO"

    # state_changed_at — timestamp with tz NOT NULL
    assert "timestamp" in by_name["state_changed_at"]["data_type"]
    assert by_name["state_changed_at"]["is_nullable"] == "NO"

    # state_changed_by — text NULL
    assert by_name["state_changed_by"]["data_type"] == "text"
    assert by_name["state_changed_by"]["is_nullable"] == "YES"


@pytest.mark.asyncio
async def test_model_portfolios_state_check_constraint_enumerates_8_values():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        check_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'model_portfolios'
              AND c.conname = 'model_portfolios_state_check'
            """,
        )
    finally:
        await conn.close()

    assert check_def is not None, "model_portfolios_state_check constraint not found"
    for value in _EXPECTED_STATES:
        assert f"'{value}'" in check_def, f"state '{value}' missing from CHECK"


@pytest.mark.asyncio
async def test_portfolio_state_transitions_table_exists():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'portfolio_state_transitions'
            ORDER BY ordinal_position
            """,
        )
    finally:
        await conn.close()

    by_name = {r["column_name"]: r for r in rows}
    expected = {
        "id",
        "organization_id",
        "portfolio_id",
        "from_state",
        "to_state",
        "actor_id",
        "reason",
        "metadata",
        "created_at",
    }
    assert expected.issubset(by_name.keys()), (
        f"missing columns: {expected - set(by_name.keys())}"
    )

    # to_state, actor_id, organization_id, portfolio_id are NOT NULL
    assert by_name["to_state"]["is_nullable"] == "NO"
    assert by_name["actor_id"]["is_nullable"] == "NO"
    assert by_name["organization_id"]["is_nullable"] == "NO"
    assert by_name["portfolio_id"]["is_nullable"] == "NO"

    # from_state is nullable (initial transition has no source)
    assert by_name["from_state"]["is_nullable"] == "YES"


@pytest.mark.asyncio
async def test_portfolio_state_transitions_fk_cascades():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        fk_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_state_transitions'
              AND c.contype = 'f'
              AND c.conname LIKE '%portfolio_id%'
            """,
        )
    finally:
        await conn.close()

    assert fk_def is not None, "FK on portfolio_id not found"
    assert "model_portfolios" in fk_def
    assert "ON DELETE CASCADE" in fk_def


@pytest.mark.asyncio
async def test_portfolio_state_transitions_indexes_exist():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        indexes = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'portfolio_state_transitions'
            """,
        )
    finally:
        await conn.close()

    names = {r["indexname"] for r in indexes}
    assert "ix_pst_portfolio_created" in names
    assert "ix_pst_org_created" in names


@pytest.mark.asyncio
async def test_portfolio_state_transitions_rls_subselect():
    """RLS policy MUST use the subselect pattern (CLAUDE.md rule).

    Without the subselect wrapper, ``current_setting()`` re-evaluates per
    row and the index plan loses ~1000x in latency.
    """
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rls_enabled = await conn.fetchval(
            """
            SELECT relrowsecurity FROM pg_class
            WHERE relname = 'portfolio_state_transitions'
            """,
        )
        policy_def = await conn.fetchval(
            """
            SELECT qual FROM pg_policies
            WHERE policyname = 'portfolio_state_transitions_rls'
              AND tablename = 'portfolio_state_transitions'
            """,
        )
    finally:
        await conn.close()

    assert rls_enabled is True, "RLS not enabled on portfolio_state_transitions"
    assert policy_def is not None, "portfolio_state_transitions_rls policy missing"
    # The subselect form: (SELECT current_setting(...))
    assert "SELECT current_setting" in policy_def, (
        f"RLS policy must use subselect form, got: {policy_def}"
    )
    assert "app.current_organization_id" in policy_def


@pytest.mark.asyncio
async def test_model_portfolios_backfill_populated_state():
    """All existing rows should have a non-null state after the backfill.

    Even if the table is empty in this test environment, the assertion
    must hold (no rows → no violations).
    """
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        null_count = await conn.fetchval(
            "SELECT COUNT(*) FROM model_portfolios WHERE state IS NULL",
        )
    finally:
        await conn.close()

    assert null_count == 0, f"{null_count} model_portfolios rows have NULL state"

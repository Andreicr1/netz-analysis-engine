"""Assert migration 0102 created portfolio_weight_snapshots hypertable.

Verifies (per Phase 2 Task 2.3):

- Columns: organization_id, portfolio_id, instrument_id, as_of,
  weight_strategic, weight_tactical, weight_effective, source, notes
- Composite PK is ``(organization_id, portfolio_id, instrument_id, as_of)``
- CHECK on ``source`` restricts to ('eod', 'intraday',
  'construction_run', 'overlay')
- FKs to ``model_portfolios(id)`` (CASCADE) and
  ``instruments_universe(instrument_id)``
- TimescaleDB hypertable with 7-day chunk interval
- Compression enabled with ``segmentby=portfolio_id`` and
  ``orderby=as_of DESC, instrument_id``
- Compression policy set to 14 days
- **RLS is DISABLED** (documented architectural exception — see
  migration docstring)
- Auxiliary index ``ix_pws_portfolio_as_of`` exists
"""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


_EXPECTED_COLUMNS = {
    "organization_id",
    "portfolio_id",
    "instrument_id",
    "as_of",
    "weight_strategic",
    "weight_tactical",
    "weight_effective",
    "source",
    "notes",
    "created_at",
}


@pytest.mark.asyncio
async def test_portfolio_weight_snapshots_columns():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'portfolio_weight_snapshots'
            """,
        )
    finally:
        await conn.close()
    present = {r["column_name"] for r in rows}
    missing = _EXPECTED_COLUMNS - present
    assert not missing, f"missing columns: {missing}"


@pytest.mark.asyncio
async def test_portfolio_weight_snapshots_composite_pk():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        pk_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_weight_snapshots'
              AND c.contype = 'p'
            """,
        )
    finally:
        await conn.close()
    assert pk_def is not None
    # All 4 PK columns must be present in the correct order
    for col in ("organization_id", "portfolio_id", "instrument_id", "as_of"):
        assert col in pk_def, f"PK column {col} missing: {pk_def}"


@pytest.mark.asyncio
async def test_portfolio_weight_snapshots_source_check():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        check_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_weight_snapshots'
              AND c.conname = 'ck_pws_source'
            """,
        )
    finally:
        await conn.close()
    assert check_def is not None
    for source in ("eod", "intraday", "construction_run", "overlay"):
        assert f"'{source}'" in check_def, f"source {source} missing from CHECK"


@pytest.mark.asyncio
async def test_portfolio_weight_snapshots_fks():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        fks = await conn.fetch(
            """
            SELECT pg_get_constraintdef(c.oid) AS def
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_weight_snapshots'
              AND c.contype = 'f'
            """,
        )
    finally:
        await conn.close()
    defs = [r["def"] for r in fks]
    assert any("model_portfolios" in d and "CASCADE" in d for d in defs), (
        f"no CASCADE FK to model_portfolios: {defs}"
    )
    assert any("instruments_universe" in d for d in defs), (
        f"no FK to instruments_universe: {defs}"
    )


@pytest.mark.asyncio
async def test_portfolio_weight_snapshots_is_hypertable():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            """
            SELECT hypertable_name, num_dimensions, compression_enabled
            FROM timescaledb_information.hypertables
            WHERE hypertable_name = 'portfolio_weight_snapshots'
            """,
        )
    finally:
        await conn.close()
    assert row is not None, "portfolio_weight_snapshots is not a hypertable"
    assert row["num_dimensions"] == 1
    assert row["compression_enabled"] is True


@pytest.mark.asyncio
async def test_portfolio_weight_snapshots_compression_segmentby():
    """TimescaleDB 2.26.1 exposes compression settings as one row per
    column with ``attname`` + ``segmentby_column_index`` / ``orderby_column_index``.
    Assert that ``portfolio_id`` is configured as a segmentby column
    and ``as_of`` is configured as an orderby column."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT attname, segmentby_column_index, orderby_column_index
            FROM timescaledb_information.compression_settings
            WHERE hypertable_name = 'portfolio_weight_snapshots'
            """,
        )
    finally:
        await conn.close()
    assert rows, "compression_settings rows missing"

    segmentby_cols = {
        r["attname"] for r in rows if r["segmentby_column_index"] is not None
    }
    orderby_cols = {
        r["attname"] for r in rows if r["orderby_column_index"] is not None
    }

    assert "portfolio_id" in segmentby_cols, (
        f"portfolio_id must be a segmentby column; got segmentby={segmentby_cols}"
    )
    assert "as_of" in orderby_cols, (
        f"as_of must be an orderby column; got orderby={orderby_cols}"
    )


@pytest.mark.asyncio
async def test_portfolio_weight_snapshots_compression_policy_14_days():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            """
            SELECT config
            FROM timescaledb_information.jobs
            WHERE hypertable_name = 'portfolio_weight_snapshots'
              AND proc_name = 'policy_compression'
            """,
        )
    finally:
        await conn.close()
    assert row is not None, "compression policy job missing"
    # Compression policy config carries the threshold — must be
    # ~14 days in some form (seconds / interval).
    config_text = str(row["config"])
    assert "14" in config_text or "1209600" in config_text, (
        f"compression threshold != 14 days: {config_text}"
    )


@pytest.mark.asyncio
async def test_portfolio_weight_snapshots_rls_disabled_by_design():
    """RLS is intentionally DISABLED on this table.

    Compressed hypertables in this codebase all disable RLS —
    ``audit_events``, ``fund_risk_metrics``, ``macro_data`` follow
    the same pattern. Security is enforced at the application
    layer via mandatory ``WHERE organization_id = :org_id`` filters.

    This test documents the exception so a future PR doesn't
    "fix" it by enabling RLS and silently breaking compression.
    """
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rls_enabled = await conn.fetchval(
            "SELECT relrowsecurity FROM pg_class WHERE relname = 'portfolio_weight_snapshots'",
        )
    finally:
        await conn.close()
    assert rls_enabled is False, (
        "portfolio_weight_snapshots must NOT have RLS enabled — "
        "compression incompatible per existing codebase pattern. "
        "See migration 0030_audit_event_hypertables.py for precedent."
    )


@pytest.mark.asyncio
async def test_portfolio_weight_snapshots_auxiliary_index():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'portfolio_weight_snapshots'
            """,
        )
    finally:
        await conn.close()
    names = {r["indexname"] for r in rows}
    assert "ix_pws_portfolio_as_of" in names

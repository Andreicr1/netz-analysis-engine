"""Assert migration 0103 created portfolio_alerts.

Verifies (per Phase 2 Task 2.4):

- Expected columns present (id, portfolio_id, alert_type, severity,
  title, payload, source_worker, source_lock_id, dedupe_key,
  created_at, acknowledged_at/by, dismissed_at/by, auto_dismiss_at)
- ``dedupe_key`` is a NOT NULL materialized column (OD-23)
- CHECK on ``alert_type`` enumerates the 8 canonical values
- CHECK on ``severity`` enumerates (info, warning, critical)
- FK to ``model_portfolios(id)`` with CASCADE
- ``ix_portfolio_alerts_open`` partial index on
  ``(portfolio_id, created_at DESC) WHERE dismissed_at IS NULL``
- ``ix_portfolio_alerts_dedupe`` UNIQUE partial index on
  ``(portfolio_id, alert_type, dedupe_key) WHERE dismissed_at IS NULL``
- Subselect-wrapped RLS policy
"""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


_EXPECTED_COLUMNS = {
    "id",
    "organization_id",
    "portfolio_id",
    "alert_type",
    "severity",
    "title",
    "payload",
    "source_worker",
    "source_lock_id",
    "dedupe_key",
    "created_at",
    "acknowledged_at",
    "acknowledged_by",
    "dismissed_at",
    "dismissed_by",
    "auto_dismiss_at",
}

_EXPECTED_ALERT_TYPES = {
    "cvar_breach",
    "drift",
    "regime_change",
    "price_staleness",
    "weight_drift",
    "rebalance_suggested",
    "validation_block",
    "custom",
}


@pytest.mark.asyncio
async def test_portfolio_alerts_columns():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT column_name, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'portfolio_alerts'
            """,
        )
    finally:
        await conn.close()
    by_name = {r["column_name"]: r for r in rows}
    missing = _EXPECTED_COLUMNS - set(by_name.keys())
    assert not missing, f"missing columns: {missing}"
    # OD-23: dedupe_key is materialized and NOT NULL
    assert by_name["dedupe_key"]["is_nullable"] == "NO"
    # Source attribution NOT NULL
    assert by_name["source_worker"]["is_nullable"] == "NO"


@pytest.mark.asyncio
async def test_portfolio_alerts_alert_type_check():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        check_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_alerts'
              AND c.conname = 'ck_alert_type'
            """,
        )
    finally:
        await conn.close()
    assert check_def is not None
    for alert_type in _EXPECTED_ALERT_TYPES:
        assert f"'{alert_type}'" in check_def, (
            f"alert_type {alert_type} missing from CHECK"
        )


@pytest.mark.asyncio
async def test_portfolio_alerts_severity_check():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        check_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_alerts'
              AND c.conname = 'ck_alert_severity'
            """,
        )
    finally:
        await conn.close()
    assert check_def is not None
    for severity in ("info", "warning", "critical"):
        assert f"'{severity}'" in check_def


@pytest.mark.asyncio
async def test_portfolio_alerts_fk_cascade():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        fk_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_alerts'
              AND c.contype = 'f'
            """,
        )
    finally:
        await conn.close()
    assert fk_def is not None
    assert "model_portfolios" in fk_def
    assert "ON DELETE CASCADE" in fk_def


@pytest.mark.asyncio
async def test_portfolio_alerts_open_partial_index():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        idx_def = await conn.fetchval(
            """
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'portfolio_alerts'
              AND indexname = 'ix_portfolio_alerts_open'
            """,
        )
    finally:
        await conn.close()
    assert idx_def is not None, "ix_portfolio_alerts_open missing"
    assert "dismissed_at IS NULL" in idx_def, (
        f"hot-path index must be partial on dismissed_at: {idx_def}"
    )
    assert "created_at" in idx_def


@pytest.mark.asyncio
async def test_portfolio_alerts_dedupe_unique_partial_index():
    """OD-23: partial UNIQUE index on (portfolio_id, alert_type, dedupe_key)."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        idx_def = await conn.fetchval(
            """
            SELECT indexdef FROM pg_indexes
            WHERE tablename = 'portfolio_alerts'
              AND indexname = 'ix_portfolio_alerts_dedupe'
            """,
        )
    finally:
        await conn.close()
    assert idx_def is not None, "ix_portfolio_alerts_dedupe missing"
    assert "UNIQUE" in idx_def
    assert "dismissed_at IS NULL" in idx_def
    for col in ("portfolio_id", "alert_type", "dedupe_key"):
        assert col in idx_def, f"dedupe index missing column {col}: {idx_def}"


@pytest.mark.asyncio
async def test_portfolio_alerts_auto_dismiss_index():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'portfolio_alerts'
            """,
        )
    finally:
        await conn.close()
    names = {r["indexname"] for r in rows}
    assert "ix_portfolio_alerts_auto_dismiss" in names
    assert "ix_portfolio_alerts_portfolio_created" in names


@pytest.mark.asyncio
async def test_portfolio_alerts_rls_subselect():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rls_enabled = await conn.fetchval(
            "SELECT relrowsecurity FROM pg_class WHERE relname = 'portfolio_alerts'",
        )
        policy_def = await conn.fetchval(
            """
            SELECT qual FROM pg_policies
            WHERE policyname = 'portfolio_alerts_rls'
              AND tablename = 'portfolio_alerts'
            """,
        )
    finally:
        await conn.close()
    assert rls_enabled is True
    assert policy_def is not None
    assert "SELECT current_setting" in policy_def
    assert "app.current_organization_id" in policy_def

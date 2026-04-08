"""Assert migration 0105 added the calibration FK.

Verifies (per Phase 2 Task 2.6):

- ``fk_pcr_calibration_id`` exists on ``portfolio_construction_runs``
- References ``portfolio_calibration(id)``
- Uses ON DELETE SET NULL (preserves historical runs on preset
  deletion per DL4)
- 0099's "no FK yet" guard test must now show the FK present
"""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.mark.asyncio
async def test_calibration_fk_exists():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        fk_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_construction_runs'
              AND c.conname = 'fk_pcr_calibration_id'
            """,
        )
    finally:
        await conn.close()
    assert fk_def is not None, "fk_pcr_calibration_id constraint missing"
    assert "portfolio_calibration" in fk_def
    assert "calibration_id" in fk_def
    assert "ON DELETE SET NULL" in fk_def


@pytest.mark.asyncio
async def test_calibration_fk_references_correct_column():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT
                a.attname AS local_column,
                rt.relname AS foreign_table,
                af.attname AS foreign_column
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
            JOIN pg_class rt ON rt.oid = c.confrelid
            JOIN pg_attribute af ON af.attrelid = c.confrelid AND af.attnum = ANY(c.confkey)
            WHERE t.relname = 'portfolio_construction_runs'
              AND c.conname = 'fk_pcr_calibration_id'
            """,
        )
    finally:
        await conn.close()
    assert len(rows) == 1, f"expected 1 FK column, got {len(rows)}"
    row = rows[0]
    assert row["local_column"] == "calibration_id"
    assert row["foreign_table"] == "portfolio_calibration"
    assert row["foreign_column"] == "id"

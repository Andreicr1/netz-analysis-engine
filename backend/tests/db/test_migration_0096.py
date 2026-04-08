"""Assert migration 0096 created Discovery FCL keyset indexes."""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.mark.asyncio
async def test_sec_managers_aum_crd_index_exists():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchval(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'sec_managers'
              AND indexname = 'idx_sec_managers_aum_crd'
            """
        )
    finally:
        await conn.close()
    assert row == "idx_sec_managers_aum_crd"


@pytest.mark.asyncio
async def test_mv_unified_funds_mgr_aum_index_exists():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchval(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'mv_unified_funds'
              AND indexname = 'idx_mv_unified_funds_mgr_aum'
            """
        )
    finally:
        await conn.close()
    assert row == "idx_mv_unified_funds_mgr_aum"

"""Conftest for wealth route integration tests."""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config.settings import settings


def _asyncpg_dsn() -> str:
    """Convert SQLAlchemy async DSN to plain asyncpg DSN."""
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture(scope="module", autouse=True)
async def _refresh_screener_matviews():
    """Ensure mv_fund_risk_latest is populated before screener tests.

    Migration 0116 creates the matview and refreshes it once, but on a
    fresh DB fund_risk_metrics is empty so the view stays 'unpopulated'.
    Selecting from an unpopulated matview raises
    ObjectNotInPrerequisiteStateError.  A single REFRESH (even to an
    empty result set) puts the view into a valid state.

    Uses a raw asyncpg connection (not the SQLAlchemy engine) to avoid
    event-loop conflicts with the shared connection pool.
    """
    dsn = _asyncpg_dsn()
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("REFRESH MATERIALIZED VIEW mv_fund_risk_latest")
    finally:
        await conn.close()

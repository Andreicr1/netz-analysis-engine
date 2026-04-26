"""PR-Q11 Phase 1 — integration tests for instrument_identity schema + resolver.

Tests run against local docker-compose PostgreSQL (``make up``) with
``instruments_universe`` populated. Marked as integration: CI's default
``-m "not integration"`` filter skips them. Run locally with::

    pytest backend/tests/data_providers/identity/ -m integration
"""
from __future__ import annotations

import uuid

import asyncpg
import pytest

from app.core.config import settings

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_PREFIX = "q11-p1"


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def _db_reachable() -> bool:
    try:
        conn = await asyncpg.connect(_asyncpg_dsn(), timeout=2.0)
    except Exception:
        return False
    await conn.close()
    return True


@pytest.fixture
async def conn():
    """Provide a raw asyncpg connection with automatic cleanup."""
    if not await _db_reachable():
        pytest.skip("DATABASE_URL not reachable")
    c = await asyncpg.connect(_asyncpg_dsn(), timeout=5.0)
    yield c
    # Cleanup any test rows
    await c.execute(
        "DELETE FROM instrument_identity_history "
        "WHERE instrument_id IN ("
        "  SELECT instrument_id FROM instrument_identity "
        "  WHERE identity_sources->>'_test_prefix' = $1"
        ")",
        TEST_PREFIX,
    )
    await c.execute(
        "DELETE FROM instrument_identity "
        "WHERE identity_sources->>'_test_prefix' = $1",
        TEST_PREFIX,
    )
    await c.close()


async def _get_test_instrument_id(conn) -> uuid.UUID:
    """Return first instrument_id from instruments_universe."""
    row = await conn.fetchrow(
        "SELECT instrument_id FROM instruments_universe LIMIT 1"
    )
    assert row is not None, "instruments_universe is empty"
    return row["instrument_id"]


async def _get_test_instrument_ids(conn, n: int = 3) -> list[uuid.UUID]:
    """Return N instrument_ids from instruments_universe."""
    rows = await conn.fetch(
        "SELECT instrument_id FROM instruments_universe LIMIT $1", n
    )
    return [r["instrument_id"] for r in rows]


async def _insert_identity(conn, instrument_id, **kwargs):
    """Insert an identity row with test prefix."""
    kwargs.setdefault("identity_sources", f'{{"_test_prefix": "{TEST_PREFIX}"}}')
    cols = ["instrument_id"] + list(kwargs.keys())
    vals = [instrument_id] + list(kwargs.values())
    placeholders = ", ".join(f"${i+1}" for i in range(len(cols)))
    col_str = ", ".join(cols)
    await conn.execute(
        f"INSERT INTO instrument_identity ({col_str}) VALUES ({placeholders})",
        *vals,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_db_returns_empty_or_none(conn):
    """Resolver returns empty/None when identity table has no matching row."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from data_providers.identity.resolver import by_cik, resolve_full

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    fake_id = uuid.uuid4()
    async with async_session() as session:
        result = await resolve_full(session, fake_id)
        assert result is None

        result_list = await by_cik(session, "9999999999")
        assert result_list == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_cik_padded_unpadded_normalization(conn):
    """by_cik finds the row whether input is padded or unpadded."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from data_providers.identity.resolver import by_cik

    iid = await _get_test_instrument_id(conn)
    await _insert_identity(
        conn, iid,
        cik_padded="0000884394",
        cik_unpadded="884394",
        ticker="TEST1",
        resolution_status="canonical",
    )

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        # Padded input
        r1 = await by_cik(session, "0000884394")
        assert iid in r1

        # Unpadded input
        r2 = await by_cik(session, "884394")
        assert iid in r2

    await engine.dispose()


@pytest.mark.asyncio
async def test_by_cik_returns_list_not_single(conn):
    """by_cik always returns a list."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from data_providers.identity.resolver import by_cik

    iid = await _get_test_instrument_id(conn)
    await _insert_identity(
        conn, iid,
        cik_padded="0000000001",
        cik_unpadded="1",
        ticker="TRET",
        resolution_status="canonical",
    )

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await by_cik(session, "1")
        assert isinstance(result, list)
        assert len(result) >= 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_by_cik_multiple_share_classes_returns_all(conn):
    """Multiple instruments with same CIK all returned."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    from data_providers.identity.resolver import by_cik

    ids = await _get_test_instrument_ids(conn, 2)
    for iid in ids:
        await _insert_identity(
            conn, iid,
            cik_padded="0000999888",
            cik_unpadded="999888",
            ticker=f"MC{ids.index(iid)}",
            resolution_status="canonical",
        )

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await by_cik(session, "999888")
        assert len(result) >= 2
        for iid in ids:
            assert iid in result

    await engine.dispose()


@pytest.mark.asyncio
async def test_isin_check_constraint_rejects_series_id_format(conn):
    """ISIN CHECK rejects SEC series_id format (S000012345)."""
    iid = await _get_test_instrument_id(conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_identity(conn, iid, isin="S000012345")


@pytest.mark.asyncio
async def test_isin_check_constraint_rejects_lei_format(conn):
    """ISIN CHECK rejects LEI format (20 alphanumeric chars)."""
    iid = await _get_test_instrument_id(conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_identity(conn, iid, isin="549300GKFG0E")  # too long or wrong format


@pytest.mark.asyncio
async def test_chk_cik_consistency_rejects_mismatched_pair(conn):
    """CIK consistency CHECK rejects padded/unpadded that don't match."""
    iid = await _get_test_instrument_id(conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_identity(
            conn, iid,
            cik_padded="0000001234",
            cik_unpadded="9999",
        )


@pytest.mark.asyncio
async def test_resolution_status_canonical_requires_canonical_identifier(conn):
    """canonical status needs at least one canonical identifier."""
    iid = await _get_test_instrument_id(conn)
    with pytest.raises(asyncpg.CheckViolationError):
        await _insert_identity(
            conn, iid,
            resolution_status="canonical",
            # No canonical identifiers provided
        )


@pytest.mark.asyncio
async def test_resolution_status_candidate_accepts_crd_only_seed(conn):
    """candidate status should accept sec_crd only."""
    iid = await _get_test_instrument_id(conn)
    await _insert_identity(
        conn, iid,
        resolution_status="candidate",
        sec_crd="1234567",
    )
    row = await conn.fetchrow(
        "SELECT resolution_status FROM instrument_identity "
        "WHERE instrument_id = $1",
        iid,
    )
    assert row["resolution_status"] == "candidate"


@pytest.mark.asyncio
async def test_history_trigger_fires_on_update(conn):
    """AFTER UPDATE trigger creates history rows."""
    iid = await _get_test_instrument_id(conn)
    await _insert_identity(
        conn, iid,
        cik_padded="0000000042",
        cik_unpadded="42",
        ticker="HIST",
        resolution_status="canonical",
    )

    # Update ticker
    await conn.execute(
        "UPDATE instrument_identity SET ticker = 'HIST2' "
        "WHERE instrument_id = $1",
        iid,
    )

    rows = await conn.fetch(
        "SELECT field_name, old_value, new_value FROM instrument_identity_history "
        "WHERE instrument_id = $1 AND field_name = 'ticker' "
        "ORDER BY history_id",
        iid,
    )
    # Should have initial insert row + update row
    assert len(rows) >= 2
    # Last row should be the update
    assert rows[-1]["old_value"] == "HIST"
    assert rows[-1]["new_value"] == "HIST2"


@pytest.mark.asyncio
async def test_history_records_old_and_new_values(conn):
    """History correctly records old_value=NULL on initial insert."""
    iid = await _get_test_instrument_id(conn)
    await _insert_identity(
        conn, iid,
        cik_padded="0000000077",
        cik_unpadded="77",
        ticker="NEWV",
        resolution_status="canonical",
    )

    rows = await conn.fetch(
        "SELECT field_name, old_value, new_value FROM instrument_identity_history "
        "WHERE instrument_id = $1 AND field_name = 'cik_padded'",
        iid,
    )
    assert len(rows) >= 1
    # Initial insert should have old_value=NULL
    assert rows[0]["old_value"] is None
    assert rows[0]["new_value"] == "0000000077"

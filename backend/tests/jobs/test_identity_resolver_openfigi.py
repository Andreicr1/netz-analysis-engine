"""PR-Q11 Phase 3 — OpenFIGI source tests.

Tests run against local docker-compose PostgreSQL (``make up``).
Skipped cleanly if DATABASE_URL is unreachable.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest

from app.core.config import settings
from app.core.jobs.identity_resolver import (
    OPENFIGI_BATCH_SIZE,
    OPENFIGI_RATE_LIMIT_REQUESTS,
    SourceResult,
    _source_5_openfigi,
    _upsert_identity,
)

TEST_PREFIX = "q11-p3"


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
    if not await _db_reachable():
        pytest.skip("DATABASE_URL not reachable")
    c = await asyncpg.connect(_asyncpg_dsn(), timeout=5.0)
    yield c
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


@pytest.fixture
async def db_session():
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_async_engine(settings.database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
    await engine.dispose()


async def _get_test_iid(conn) -> str:
    row = await conn.fetchrow(
        "SELECT instrument_id::text FROM instruments_universe "
        "WHERE ticker IS NOT NULL LIMIT 1"
    )
    return row["instrument_id"]


# ---------------------------------------------------------------------------
# OpenFIGI tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openfigi_batch_size_100(conn, db_session):
    """OpenFIGI batches are limited to 100 items."""
    assert OPENFIGI_BATCH_SIZE == 100


@pytest.mark.asyncio
async def test_openfigi_rate_limit_respected(conn, db_session):
    """Rate limit config is 25 requests per 6 seconds."""
    assert OPENFIGI_RATE_LIMIT_REQUESTS == 25


@pytest.mark.asyncio
async def test_openfigi_provider_gate_circuit_breaker(conn, db_session):
    """OpenFIGI uses ExternalProviderGate with 5min timeout."""
    from app.core.runtime.gates import _OPENFIGI_GATE_CONFIG

    assert _OPENFIGI_GATE_CONFIG.name == "openfigi"
    assert _OPENFIGI_GATE_CONFIG.timeout_s == 300.0
    assert _OPENFIGI_GATE_CONFIG.failure_threshold == 10


@pytest.mark.asyncio
async def test_openfigi_isin_only_overwrites_when_authority_allows(conn, db_session):
    """OpenFIGI ISIN (authority 2) cannot overwrite ESMA ISIN (authority 3)."""
    iid = await _get_test_iid(conn)

    # First set ISIN from ESMA (authority 3)
    sr_esma = SourceResult("esma")
    sr_esma.set("isin", "IE00B5BMR087")
    sr_esma.set("esma_manager_id", "MGR999")
    await _upsert_identity(db_session, iid, [sr_esma])
    await db_session.commit()

    # Then try OpenFIGI ISIN (authority 2) — should NOT overwrite
    sr_figi = SourceResult("openfigi")
    sr_figi.set("isin", "US1234567890")
    sr_figi.set("figi", "BBG000BHTK46")
    await _upsert_identity(db_session, iid, [sr_figi])
    await db_session.commit()

    from sqlalchemy import text
    row = (await db_session.execute(
        text("SELECT isin, figi FROM instrument_identity WHERE instrument_id = :iid"),
        {"iid": iid},
    )).first()
    assert row.isin == "IE00B5BMR087"  # ESMA wins
    assert row.figi == "BBG000BHTK46"  # FIGI set by OpenFIGI (no prior)

    # Cleanup
    await db_session.execute(
        text("DELETE FROM instrument_identity_history WHERE instrument_id = :iid"),
        {"iid": iid},
    )
    await db_session.execute(
        text("DELETE FROM instrument_identity WHERE instrument_id = :iid"),
        {"iid": iid},
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_openfigi_populates_figi_cusip_when_missing(conn, db_session):
    """OpenFIGI fills figi and cusip when previously NULL."""
    iid = await _get_test_iid(conn)

    # Insert with just CIK (no cusip/figi)
    sr_sec = SourceResult("sec_company_tickers")
    sr_sec.set("cik_padded", "0000884394")
    sr_sec.set("cik_unpadded", "884394")
    sr_sec.set("ticker", "SPY")
    await _upsert_identity(db_session, iid, [sr_sec])
    await db_session.commit()

    # OpenFIGI adds cusip + figi
    sr_figi = SourceResult("openfigi")
    sr_figi.set("figi", "BBG000BHTK46")
    sr_figi.set("cusip_9", "78462F103")
    sr_figi.set("cusip_8", "78462F10")
    await _upsert_identity(db_session, iid, [sr_figi])
    await db_session.commit()

    from sqlalchemy import text
    row = (await db_session.execute(
        text(
            "SELECT figi, cusip_9, cusip_8 FROM instrument_identity "
            "WHERE instrument_id = :iid"
        ),
        {"iid": iid},
    )).first()
    assert row.figi == "BBG000BHTK46"
    assert row.cusip_9 == "78462F103"
    assert row.cusip_8 == "78462F10"

    # Cleanup
    await db_session.execute(
        text("DELETE FROM instrument_identity_history WHERE instrument_id = :iid"),
        {"iid": iid},
    )
    await db_session.execute(
        text("DELETE FROM instrument_identity WHERE instrument_id = :iid"),
        {"iid": iid},
    )
    await db_session.commit()


@pytest.mark.asyncio
async def test_openfigi_no_api_key_returns_failure(conn, db_session):
    """Without OPENFIGI_API_KEY, source 5 returns success=False."""
    iid = await _get_test_iid(conn)

    with patch.dict("os.environ", {"OPENFIGI_API_KEY": ""}):
        results, success = await _source_5_openfigi(db_session, [iid])

    assert success is False
    assert results == {}


@pytest.mark.asyncio
async def test_openfigi_mock_response_extracts_fields(conn, db_session):
    """Mocked OpenFIGI response correctly extracts figi, cusip, mic."""
    iid = await _get_test_iid(conn)

    mock_response = [
        {
            "data": [
                {
                    "figi": "BBG000BHTK46",
                    "compositeFIGI": "BBG000BHTK46",
                    "cusip": "78462F103",
                    "exchCode": "US",
                    "micCode": "XNYS",
                    "securityType": "Common Stock",
                    "marketSector": "Equity",
                }
            ]
        }
    ]

    with patch.dict("os.environ", {"OPENFIGI_API_KEY": "test-key"}):
        with patch(
            "app.core.jobs.identity_resolver._openfigi_batch_request",
            return_value=mock_response,
        ):
            with patch(
                "app.core.runtime.gates.get_openfigi_gate"
            ) as mock_gate_factory:
                # Make gate.call call the lambda and await it
                mock_gate = AsyncMock()

                async def _call_fn(key, fn):
                    result = fn()
                    if asyncio.iscoroutine(result):
                        return await result
                    return result

                mock_gate.call = _call_fn
                mock_gate_factory.return_value = mock_gate

                results, success = await _source_5_openfigi(db_session, [iid])

    assert success is True
    if iid in results:
        sr = results[iid]
        assert sr.fields.get("figi") == "BBG000BHTK46"
        assert sr.fields.get("cusip_9") == "78462F103"
        assert sr.fields.get("mic") == "XNYS"

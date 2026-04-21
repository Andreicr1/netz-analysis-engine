"""Integration tests for equity_characteristics_compute worker.

Requires running PostgreSQL with TimescaleDB + Tiingo fundamentals tables.
"""

from __future__ import annotations

import asyncpg
import pytest
from sqlalchemy import text

from app.core.config.settings import settings
from app.core.db.engine import async_session_factory as async_session
from app.core.jobs.equity_characteristics_compute import LOCK_ID, run_equity_characteristics_compute


def _direct_url() -> str:
    url = settings.database_url
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url


@pytest.fixture
async def seed_tiingo_data():
    """Seed 5 tickers x 12 months of Tiingo fundamentals + NAV data."""
    tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
    async with async_session() as db:
        await db.execute(text("DELETE FROM equity_characteristics_monthly"))

        for tk in tickers:
            for m in range(1, 13):
                month_end = f"2025-{m:02d}-28"
                await db.execute(
                    text("""
                        INSERT INTO tiingo_fundamentals_daily (ticker, as_of, market_cap)
                        VALUES (:tk, :dt, :mc)
                        ON CONFLICT (ticker, as_of) DO NOTHING
                    """),
                    {"tk": tk, "dt": month_end, "mc": 1_000_000_000 + m * 100_000_000},
                )

                for item, val in [
                    ("totalEquity", 500_000_000),
                    ("netIncome", 50_000_000),
                    ("totalAssets", 2_000_000_000),
                    ("grossProfit", 300_000_000),
                    ("revenue", 1_000_000_000),
                ]:
                    await db.execute(
                        text("""
                            INSERT INTO tiingo_fundamentals_statements
                                (ticker, period_end, statement_type, line_item, value, filing_date)
                            VALUES (:tk, :pe, 'balance', :li, :val, :fd)
                            ON CONFLICT (ticker, period_end, statement_type, line_item, filing_date) DO NOTHING
                        """),
                        {"tk": tk, "pe": month_end, "li": item, "val": val, "fd": month_end},
                    )

        for tk in tickers:
            iid = await db.scalar(
                text("SELECT id FROM instruments_universe WHERE ticker = :tk LIMIT 1"),
                {"tk": tk},
            )
            if iid:
                for m in range(1, 14):
                    nav_date = f"2024-{m:02d}-15" if m <= 12 else "2025-01-15"
                    await db.execute(
                        text("""
                            INSERT INTO nav_timeseries (instrument_id, ts, nav)
                            VALUES (:iid, :ts, :nav)
                            ON CONFLICT DO NOTHING
                        """),
                        {"iid": str(iid), "ts": nav_date, "nav": 100 + m * 2},
                    )

        await db.commit()
    yield
    async with async_session() as db:
        await db.execute(text("DELETE FROM equity_characteristics_monthly"))
        await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_inserts_rows(seed_tiingo_data):
    """1. Worker on seeded tickers produces rows with non-NULL characteristics."""
    result = await run_equity_characteristics_compute(limit=5)
    assert result["status"] == "ok"
    assert result["computed"] > 0

    async with async_session() as db:
        count = await db.scalar(text("SELECT COUNT(*) FROM equity_characteristics_monthly"))
        assert count > 0
        non_null = await db.scalar(text(
            "SELECT COUNT(*) FROM equity_characteristics_monthly WHERE size_log_mkt_cap IS NOT NULL"
        ))
        assert non_null > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_restatement_propagates(seed_tiingo_data):
    """2. Updated filing_date propagates via upsert — restatement overwrites."""
    await run_equity_characteristics_compute(limit=1)

    async with async_session() as db:
        old_val = await db.scalar(text(
            "SELECT quality_roa FROM equity_characteristics_monthly ORDER BY as_of DESC LIMIT 1"
        ))

    async with async_session() as db:
        await db.execute(text("""
            UPDATE tiingo_fundamentals_statements
            SET value = 999999999, filing_date = '2025-12-31'
            WHERE ticker = 'AAPL' AND line_item = 'netIncome'
            AND period_end = '2025-12-28'
        """))
        await db.commit()

    await run_equity_characteristics_compute(limit=1)

    async with async_session() as db:
        new_val = await db.scalar(text(
            "SELECT quality_roa FROM equity_characteristics_monthly "
            "WHERE ticker = 'AAPL' ORDER BY as_of DESC LIMIT 1"
        ))
    assert new_val != old_val


@pytest.mark.integration
@pytest.mark.asyncio
async def test_missing_data_null_tolerance():
    """3. Ticker with market_cap but no statements produces row with NULL characteristics."""
    async with async_session() as db:
        await db.execute(text("DELETE FROM equity_characteristics_monthly"))

        iid = await db.scalar(
            text("SELECT id FROM instruments_universe LIMIT 1"),
        )
        if not iid:
            pytest.skip("No instruments_universe rows")

        tk = await db.scalar(
            text("SELECT ticker FROM instruments_universe WHERE id = :iid"),
            {"iid": iid},
        )

        await db.execute(text("DELETE FROM tiingo_fundamentals_statements WHERE ticker = :tk"), {"tk": tk})
        await db.execute(text("""
            INSERT INTO tiingo_fundamentals_daily (ticker, as_of, market_cap)
            VALUES (:tk, '2025-06-28', 5000000000)
            ON CONFLICT (ticker, as_of) DO NOTHING
        """), {"tk": tk})
        await db.commit()

    result = await run_equity_characteristics_compute(limit=1)
    assert result["status"] == "ok"

    async with async_session() as db:
        row = (await db.execute(text(
            "SELECT size_log_mkt_cap, book_to_market, quality_roa "
            "FROM equity_characteristics_monthly WHERE ticker = :tk LIMIT 1"
        ), {"tk": tk})).first()
    assert row is not None
    assert row[0] is not None  # size computed from market_cap
    assert row[1] is None  # book_to_market NULL (no totalEquity)

    async with async_session() as db:
        await db.execute(text("DELETE FROM equity_characteristics_monthly WHERE ticker = :tk"), {"tk": tk})
        await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_idempotent(seed_tiingo_data):
    """4. Re-run produces no duplicates — upsert semantics."""
    await run_equity_characteristics_compute(limit=5)
    async with async_session() as db:
        count_1 = await db.scalar(text("SELECT COUNT(*) FROM equity_characteristics_monthly"))

    await run_equity_characteristics_compute(limit=5)
    async with async_session() as db:
        count_2 = await db.scalar(text("SELECT COUNT(*) FROM equity_characteristics_monthly"))

    assert count_1 == count_2


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_lock_held():
    """5. Second concurrent invocation exits cleanly when lock is held."""
    conn = await asyncpg.connect(_direct_url())
    await conn.execute(f"SELECT pg_advisory_lock({LOCK_ID})")

    try:
        result = await run_equity_characteristics_compute(limit=1)
        assert result["status"] == "skipped"
        assert result["reason"] == "lock_held"
    finally:
        await conn.execute(f"SELECT pg_advisory_unlock({LOCK_ID})")
        await conn.close()

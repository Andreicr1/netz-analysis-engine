"""Integration test for equity_characteristics_compute worker.

Seeds instruments_universe, sec_xbrl_facts, nav_timeseries with synthetic
data, runs the worker, and verifies equity_characteristics_monthly is
populated with correct values.

Skips if Postgres is unreachable (run ``make up`` first).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import asyncpg
import numpy as np
import pytest

from app.core.config import settings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TEST_PREFIX = "ecm-int"
CIK_A = 12345
CIK_B = 67890


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def _db_reachable() -> bool:
    try:
        conn = await asyncpg.connect(_asyncpg_dsn(), timeout=2.0)
    except Exception:
        return False
    await conn.close()
    return True


def _month_end(year: int, month: int) -> date:
    """Return last day of the given month."""
    import calendar

    return date(year, month, calendar.monthrange(year, month)[1])


@pytest.fixture
async def seeded_ecm():
    """Seed 2 instruments with XBRL + NAV data. Teardown cleans up."""
    if not await _db_reachable():
        pytest.skip("Postgres not reachable — run `make up`")

    rng = np.random.default_rng(20260425)
    inst_a = uuid.uuid4()
    inst_b = uuid.uuid4()
    instrument_ids = [inst_a, inst_b]

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        # 1. instruments_universe
        for iid, ticker, cik in [
            (inst_a, f"{TEST_PREFIX}-AAPL", CIK_A),
            (inst_b, f"{TEST_PREFIX}-MSFT", CIK_B),
        ]:
            await conn.execute(
                """
                INSERT INTO instruments_universe (
                    instrument_id, instrument_type, name, asset_class,
                    geography, ticker, attributes, slug
                ) VALUES (
                    $1::uuid, 'equity', $2, 'Equity', 'us', $3,
                    jsonb_build_object(
                        'sec_cik', $4::text,
                        'market_cap_usd', '1000000000',
                        'sector', 'Technology',
                        'exchange', 'NASDAQ'
                    ),
                    $5
                ) ON CONFLICT (instrument_id) DO NOTHING
                """,
                iid, f"Test {ticker}", ticker, str(cik),
                f"{TEST_PREFIX}-{iid}",
            )

        # 2. sec_xbrl_facts — 18 months of quarterly fundamentals
        xbrl_rows = []
        concepts_usd = {
            "StockholdersEquity": 50_000_000_000.0,
            "Assets": 300_000_000_000.0,
            "NetIncomeLoss": 20_000_000_000.0,
            "Revenues": 80_000_000_000.0,
            "CostOfRevenue": 50_000_000_000.0,
            "GrossProfit": 30_000_000_000.0,
            "PaymentsToAcquirePropertyPlantAndEquipment": 10_000_000_000.0,
            "PropertyPlantAndEquipmentNet": 40_000_000_000.0,
        }
        # Quarterly period ends: 2024-Q1 through 2025-Q2 (6 quarters)
        quarter_ends = [
            _month_end(2024, 3), _month_end(2024, 6),
            _month_end(2024, 9), _month_end(2024, 12),
            _month_end(2025, 3), _month_end(2025, 6),
        ]
        for cik in [CIK_A, CIK_B]:
            for i, pe in enumerate(quarter_ends):
                scale = 1.0 + i * 0.02  # slight growth each quarter
                for concept, base_val in concepts_usd.items():
                    val = base_val * scale
                    accn = f"0001234567-{pe.year}-{pe.month:02d}{cik}"
                    xbrl_rows.append((
                        cik, "us-gaap", concept, "USD", pe, None,
                        val, None, accn, pe.year, f"Q{(pe.month - 1) // 3 + 1}",
                        "10-Q", pe + timedelta(days=30),
                    ))
                # shares outstanding (dei taxonomy)
                shares_val = 15_000_000_000.0
                accn_shares = f"0001234567-{pe.year}-sh{pe.month:02d}{cik}"
                xbrl_rows.append((
                    cik, "dei", "EntityCommonStockSharesOutstanding",
                    "shares", pe, None, shares_val, None,
                    accn_shares, pe.year, f"Q{(pe.month - 1) // 3 + 1}",
                    "10-Q", pe + timedelta(days=30),
                ))

        await conn.executemany(
            """
            INSERT INTO sec_xbrl_facts (
                cik, taxonomy, concept, unit, period_end, period_start,
                val, val_text, accn, fy, fp, form, filed
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (cik, taxonomy, concept, unit, period_end, accn) DO NOTHING
            """,
            xbrl_rows,
        )

        # 3. Restatement test: insert a LATER filing for Assets in 2024-Q4
        # with a different value — the later one should win.
        restatement_pe = _month_end(2024, 12)
        restatement_val = 350_000_000_000.0  # different from the original
        restatement_accn = f"0001234567-2025-restate{CIK_A}"
        restatement_filed = restatement_pe + timedelta(days=90)  # filed later
        await conn.execute(
            """
            INSERT INTO sec_xbrl_facts (
                cik, taxonomy, concept, unit, period_end, period_start,
                val, val_text, accn, fy, fp, form, filed
            ) VALUES ($1, 'us-gaap', 'Assets', 'USD', $2, NULL,
                      $3, NULL, $4, 2024, 'Q4', '10-K/A', $5)
            ON CONFLICT (cik, taxonomy, concept, unit, period_end, accn) DO NOTHING
            """,
            CIK_A, restatement_pe, restatement_val,
            restatement_accn, restatement_filed,
        )

        # 4. nav_timeseries — daily NAV for 18 months (enough for momentum_12_1)
        nav_start = date(2024, 1, 1)
        nav_end = date(2025, 7, 31)
        nav_rows = []
        for iid in instrument_ids:
            d = nav_start
            nav_val = 150.0
            while d <= nav_end:
                ret = float(rng.standard_normal() * 0.01)
                nav_val *= 1 + ret
                nav_rows.append((iid, d, nav_val, ret))
                d += timedelta(days=1)
        await conn.executemany(
            """
            INSERT INTO nav_timeseries (instrument_id, nav_date, nav, return_1d)
            VALUES ($1::uuid, $2, $3, $4)
            ON CONFLICT (instrument_id, nav_date) DO NOTHING
            """,
            nav_rows,
        )

        yield {
            "instrument_ids": instrument_ids,
            "inst_a": inst_a,
            "inst_b": inst_b,
            "cik_a": CIK_A,
            "cik_b": CIK_B,
            "concepts_usd": concepts_usd,
            "quarter_ends": quarter_ends,
            "restatement_pe": restatement_pe,
            "restatement_val": restatement_val,
        }
    finally:
        # Teardown
        try:
            await conn.execute(
                "DELETE FROM equity_characteristics_monthly "
                "WHERE instrument_id = ANY($1::uuid[])",
                instrument_ids,
            )
            await conn.execute(
                "DELETE FROM nav_timeseries WHERE instrument_id = ANY($1::uuid[])",
                instrument_ids,
            )
            for cik in [CIK_A, CIK_B]:
                await conn.execute(
                    "DELETE FROM sec_xbrl_facts WHERE cik = $1", cik,
                )
            await conn.execute(
                "DELETE FROM instruments_universe WHERE instrument_id = ANY($1::uuid[])",
                instrument_ids,
            )
        finally:
            await conn.close()


async def test_worker_populates_characteristics(seeded_ecm):
    """Worker produces rows with correct values for seeded instruments."""
    from app.core.jobs.equity_characteristics_compute import (
        run_equity_characteristics_compute,
    )

    result = await run_equity_characteristics_compute()
    assert result["status"] == "succeeded"
    assert result["instruments_processed"] >= 2
    assert result["rows_written"] > 0

    # Verify rows exist
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT instrument_id, as_of,
                   size_log_mkt_cap, book_to_market, mom_12_1,
                   quality_roa, investment_growth, profitability_gross,
                   source_filing_date
            FROM equity_characteristics_monthly
            WHERE instrument_id = ANY($1::uuid[])
            ORDER BY instrument_id, as_of
            """,
            seeded_ecm["instrument_ids"],
        )
        assert len(rows) > 0, "No rows written for test instruments"

        # Each instrument should have multiple months
        inst_a_rows = [r for r in rows if r["instrument_id"] == seeded_ecm["inst_a"]]
        assert len(inst_a_rows) >= 3, f"Expected ≥3 rows for inst_a, got {len(inst_a_rows)}"

        # Check that at least some rows have non-null characteristics
        has_size = any(r["size_log_mkt_cap"] is not None for r in inst_a_rows)
        has_btm = any(r["book_to_market"] is not None for r in inst_a_rows)
        has_roa = any(r["quality_roa"] is not None for r in inst_a_rows)
        assert has_size, "No size_log_mkt_cap computed"
        assert has_btm, "No book_to_market computed"
        assert has_roa, "No quality_roa computed"

        # Verify source_filing_date is populated
        has_filed = any(r["source_filing_date"] is not None for r in inst_a_rows)
        assert has_filed, "source_filing_date not populated"

    finally:
        await conn.close()


async def test_restatement_later_filing_wins(seeded_ecm):
    """Two XBRL obs for same (cik, concept, period_end) — later filed wins."""
    from app.core.db.engine import async_session_factory
    from app.core.jobs.equity_characteristics_compute import _fetch_fundamentals

    async with async_session_factory() as db:
        fundamentals = await _fetch_fundamentals(db, seeded_ecm["cik_a"])

    pe = seeded_ecm["restatement_pe"]
    assert pe in fundamentals, f"Missing period {pe} in fundamentals"
    # The restated (later-filed) Assets value should win
    actual_assets = fundamentals[pe].get("Assets")
    assert actual_assets is not None
    assert abs(actual_assets - seeded_ecm["restatement_val"]) < 1.0, (
        f"Expected restated Assets={seeded_ecm['restatement_val']}, got {actual_assets}"
    )


async def test_idempotent_rerun(seeded_ecm):
    """Running the worker twice doesn't duplicate rows (ON CONFLICT DO UPDATE)."""
    from app.core.jobs.equity_characteristics_compute import (
        run_equity_characteristics_compute,
    )

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        # First run
        r1 = await run_equity_characteristics_compute()
        assert r1["status"] == "succeeded"

        count_after_first = await conn.fetchval(
            "SELECT COUNT(*) FROM equity_characteristics_monthly "
            "WHERE instrument_id = ANY($1::uuid[])",
            seeded_ecm["instrument_ids"],
        )
        assert count_after_first > 0, "No rows written on first run"

        # Second run
        r2 = await run_equity_characteristics_compute()
        assert r2["status"] == "succeeded"

        count_after_second = await conn.fetchval(
            "SELECT COUNT(*) FROM equity_characteristics_monthly "
            "WHERE instrument_id = ANY($1::uuid[])",
            seeded_ecm["instrument_ids"],
        )
        # Upsert: count should be identical (no duplicates)
        assert count_after_second == count_after_first, (
            f"Row count changed: {count_after_first} → {count_after_second} (duplication)"
        )
    finally:
        await conn.close()

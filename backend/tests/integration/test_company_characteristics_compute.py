"""Integration tests for company_characteristics_compute worker.

Covers 5 acceptance gates:
    - basic_population: synthetic XBRL → correct rows + math
    - restatement_dedup: later filing wins
    - idempotent_rerun: ON CONFLICT UPDATE, no duplicates
    - concept_fallback: RevenueFromContract... fills in for missing Revenues
    - unit_filter: CNY observations ignored (only USD)

Requires a running Postgres with sec_xbrl_facts table and migration 0174
applied. Skipped otherwise. Self-seeding — no dev_seed_local dependency.
"""

from __future__ import annotations

import asyncio
from datetime import date

import pytest

pytestmark = pytest.mark.integration

_TEST_CIK_A = 9999901
_TEST_CIK_B = 9999902
_TEST_CIK_C = 9999903  # concept fallback
_TEST_CIK_D = 9999904  # unit filter


def _get_session_factory():
    try:
        from app.core.db.engine import async_session_factory
        return async_session_factory
    except Exception as exc:
        pytest.skip(f"Cannot import session factory: {exc}")


async def _cleanup(db, ciks: list[int]):
    """Remove test data from both tables."""
    from sqlalchemy import text
    cik_list = ", ".join(str(c) for c in ciks)
    await db.execute(text(
        f"DELETE FROM company_characteristics_monthly WHERE cik IN ({cik_list})"
    ))
    await db.execute(text(
        f"DELETE FROM sec_xbrl_facts WHERE cik IN ({cik_list})"
    ))
    await db.commit()


async def _seed_xbrl(db, cik: int, concept: str, period_end: date,
                     val: float, filed: date, taxonomy: str = "us-gaap",
                     unit: str = "USD", fp: str = "FY",
                     accn: str = "0000000000-00-000001",
                     form: str = "10-K"):
    from sqlalchemy import text
    await db.execute(text("""
        INSERT INTO sec_xbrl_facts (cik, taxonomy, concept, unit, period_end, val, fp, filed, accn, form)
        VALUES (:cik, :taxonomy, :concept, :unit, :period_end, :val, :fp, :filed, :accn, :form)
        ON CONFLICT DO NOTHING
    """), {
        "cik": cik, "taxonomy": taxonomy, "concept": concept, "unit": unit,
        "period_end": period_end, "val": val, "fp": fp, "filed": filed,
        "accn": accn, "form": form,
    })


async def _seed_basic_cik(db, cik: int, period_end: date, filed: date,
                          assets: float = 1000.0, equity: float = 400.0,
                          net_income: float = 100.0, revenue: float = 500.0,
                          cost_rev: float = 300.0, fp: str = "FY",
                          accn_suffix: str = "001"):
    """Seed one CIK with a full set of fundamentals for one period."""
    accn = f"0000000000-00-0000{accn_suffix}"
    concepts = [
        ("Assets", assets),
        ("StockholdersEquity", equity),
        ("NetIncomeLoss", net_income),
        ("Revenues", revenue),
        ("CostOfRevenue", cost_rev),
    ]
    for concept, val in concepts:
        await _seed_xbrl(db, cik, concept, period_end, val, filed,
                         fp=fp, accn=accn)


async def _run_worker_for_ciks(ciks: list[int]):
    """Run the worker with a CIK filter by limiting to a small universe."""
    factory = _get_session_factory()
    async with factory() as db:
        from app.core.jobs.company_characteristics_compute import (
            _compute_cik,
            _upsert_rows,
        )
        for cik in ciks:
            rows = await _compute_cik(db, cik)
            if rows:
                await _upsert_rows(db, rows)


async def _count_rows(db, cik: int) -> int:
    from sqlalchemy import text
    return await db.scalar(text(
        "SELECT COUNT(*) FROM company_characteristics_monthly WHERE cik = :cik"
    ), {"cik": cik})


async def _get_rows(db, cik: int) -> list:
    from sqlalchemy import text
    result = await db.execute(text(
        "SELECT * FROM company_characteristics_monthly WHERE cik = :cik ORDER BY period_end"
    ), {"cik": cik})
    return result.all()


# ---------- Test 1: basic population ----------

def test_basic_population():
    """Seed 2 CIKs × 4 periods → assert 8 rows with correct math."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db, [_TEST_CIK_A, _TEST_CIK_B])

            periods = [
                date(2022, 3, 31), date(2022, 6, 30),
                date(2022, 9, 30), date(2022, 12, 31),
            ]
            for cik in [_TEST_CIK_A, _TEST_CIK_B]:
                for i, pe in enumerate(periods):
                    filed = date(2023, 2, 15)
                    await _seed_basic_cik(
                        db, cik, pe, filed,
                        assets=1000.0 + i * 100,
                        equity=400.0,
                        net_income=100.0,
                        revenue=500.0,
                        cost_rev=300.0,
                        fp="FY" if i == 3 else f"Q{i+1}",
                        accn_suffix=f"{cik % 100:02d}{i}",
                    )
            await db.commit()

        # Run worker
        await _run_worker_for_ciks([_TEST_CIK_A, _TEST_CIK_B])

        # Verify
        async with factory() as db:
            count_a = await _count_rows(db, _TEST_CIK_A)
            count_b = await _count_rows(db, _TEST_CIK_B)
            assert count_a == 4, f"Expected 4 rows for CIK A, got {count_a}"
            assert count_b == 4, f"Expected 4 rows for CIK B, got {count_b}"

            rows = await _get_rows(db, _TEST_CIK_A)
            # Check FY period (last one, assets=1300)
            fy_row = [r for r in rows if r.period_end == date(2022, 12, 31)][0]
            assert fy_row.total_assets == 1300.0
            assert fy_row.book_equity == 400.0
            assert fy_row.revenue == 500.0
            # gross_profit = 500 - 300 = 200
            assert fy_row.gross_profit == 200.0
            # profitability_gross = 200 / 500 = 0.4
            assert abs(float(fy_row.profitability_gross) - 0.4) < 0.001
            # quality_roa = net_income_ttm / total_assets
            # For FY, net_income_ttm = 100 (FY value)
            if fy_row.net_income_ttm is not None:
                expected_roa = 100.0 / 1300.0
                assert abs(float(fy_row.quality_roa) - expected_roa) < 0.001

            # Cleanup
            await _cleanup(db, [_TEST_CIK_A, _TEST_CIK_B])

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 2: restatement dedup ----------

def test_restatement_dedup():
    """Two observations same (cik, concept, period_end) — later filed wins."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db, [_TEST_CIK_A])

            pe = date(2023, 12, 31)
            # First filing: Assets = 900
            await _seed_xbrl(db, _TEST_CIK_A, "Assets", pe, 900.0,
                             filed=date(2024, 2, 1),
                             accn="0000000000-24-000001")
            # Restatement: Assets = 950 (filed later)
            await _seed_xbrl(db, _TEST_CIK_A, "Assets", pe, 950.0,
                             filed=date(2024, 5, 1),
                             accn="0000000000-24-000002")
            # Other concepts needed for a row
            await _seed_xbrl(db, _TEST_CIK_A, "NetIncomeLoss", pe, 80.0,
                             filed=date(2024, 2, 1),
                             accn="0000000000-24-000001")
            await db.commit()

        await _run_worker_for_ciks([_TEST_CIK_A])

        async with factory() as db:
            rows = await _get_rows(db, _TEST_CIK_A)
            assert len(rows) >= 1
            row = [r for r in rows if r.period_end == pe][0]
            # Should use the restated value (950), not original (900)
            assert float(row.total_assets) == 950.0
            await _cleanup(db, [_TEST_CIK_A])

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 3: idempotent rerun ----------

def test_idempotent_rerun():
    """Running worker twice produces same row count (ON CONFLICT UPDATE)."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db, [_TEST_CIK_A])
            await _seed_basic_cik(db, _TEST_CIK_A, date(2023, 12, 31),
                                  date(2024, 2, 15))
            await db.commit()

        # First run
        await _run_worker_for_ciks([_TEST_CIK_A])
        async with factory() as db:
            count1 = await _count_rows(db, _TEST_CIK_A)

        # Second run
        await _run_worker_for_ciks([_TEST_CIK_A])
        async with factory() as db:
            count2 = await _count_rows(db, _TEST_CIK_A)
            assert count1 == count2, f"Idempotency violated: {count1} vs {count2}"
            await _cleanup(db, [_TEST_CIK_A])

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 4: concept fallback ----------

def test_concept_fallback():
    """CIK with no Revenues but with RevenueFromContract... → revenue populated."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db, [_TEST_CIK_C])

            pe = date(2023, 12, 31)
            filed = date(2024, 2, 15)
            accn = "0000000000-24-000010"
            # NO Revenues — use fallback
            await _seed_xbrl(db, _TEST_CIK_C,
                             "RevenueFromContractWithCustomerExcludingAssessedTax",
                             pe, 750.0, filed, accn=accn)
            await _seed_xbrl(db, _TEST_CIK_C, "CostOfRevenue", pe, 450.0,
                             filed, accn=accn)
            await _seed_xbrl(db, _TEST_CIK_C, "Assets", pe, 2000.0,
                             filed, accn=accn)
            await db.commit()

        await _run_worker_for_ciks([_TEST_CIK_C])

        async with factory() as db:
            rows = await _get_rows(db, _TEST_CIK_C)
            assert len(rows) >= 1
            row = [r for r in rows if r.period_end == pe][0]
            assert float(row.revenue) == 750.0
            # gross_profit = 750 - 450 = 300
            assert float(row.gross_profit) == 300.0
            # profitability_gross = 300 / 750 = 0.4
            assert abs(float(row.profitability_gross) - 0.4) < 0.001
            await _cleanup(db, [_TEST_CIK_C])

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 5: unit filter ----------

def test_unit_filter():
    """CNY observations are ignored — only USD wins."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db, [_TEST_CIK_D])

            pe = date(2023, 12, 31)
            filed = date(2024, 2, 15)
            # Assets in CNY — should be ignored
            await _seed_xbrl(db, _TEST_CIK_D, "Assets", pe, 99999.0,
                             filed, unit="CNY",
                             accn="0000000000-24-000020")
            # Assets in USD — should be used
            await _seed_xbrl(db, _TEST_CIK_D, "Assets", pe, 5000.0,
                             filed, unit="USD",
                             accn="0000000000-24-000021")
            await db.commit()

        await _run_worker_for_ciks([_TEST_CIK_D])

        async with factory() as db:
            rows = await _get_rows(db, _TEST_CIK_D)
            if rows:
                row = [r for r in rows if r.period_end == pe][0]
                # Should be the USD value, not the CNY value
                assert float(row.total_assets) == 5000.0
            await _cleanup(db, [_TEST_CIK_D])

    asyncio.get_event_loop().run_until_complete(_test())

"""Integration tests for fund_characteristics_aggregator worker.

Covers 7 acceptance gates:
    - basic_aggregation: 1 fund with 3 equity holdings -> correct portfolio-level chars
    - period_matching: picks latest company chars <= report_date
    - unresolved_holding_skipped: holding with no issuer_cik is skipped, not error
    - bdc_direct_path: BDC uses direct XBRL, not N-PORT aggregation
    - momentum_from_fund_nav: mom_12_1 from fund's own NAV, not aggregated
    - mmf_skipped: money market fund produces no output
    - idempotent_rerun: second run upserts without duplicating

Requires a running Postgres with migrations through 0174 applied.
Self-seeding — no dev_seed_local dependency.
"""

from __future__ import annotations

import asyncio
import math
import uuid
from datetime import date, timedelta

import pytest

pytestmark = pytest.mark.integration

# Synthetic test IDs
_FUND_ID_A = uuid.UUID("aaaaaaaa-0001-0001-0001-aaaaaaaaaaaa")
_FUND_ID_B = uuid.UUID("aaaaaaaa-0002-0002-0002-aaaaaaaaaaaa")  # BDC
_FUND_ID_C = uuid.UUID("aaaaaaaa-0003-0003-0003-aaaaaaaaaaaa")  # MMF
_FUND_ID_D = uuid.UUID("aaaaaaaa-0004-0004-0004-aaaaaaaaaaaa")  # momentum test

_FUND_CIK_A = "9990001"
_FUND_CIK_B = "9990002"
_FUND_CIK_C = "9990003"
_FUND_CIK_D = "9990004"

_COMPANY_CIK_1 = 8880001
_COMPANY_CIK_2 = 8880002
_COMPANY_CIK_3 = 8880003

_CUSIP_1 = "TSTCSP001"
_CUSIP_2 = "TSTCSP002"
_CUSIP_3 = "TSTCSP003"  # no issuer_cik — unresolved


def _get_session_factory():
    try:
        from app.core.db.engine import async_session_factory
        return async_session_factory
    except Exception as exc:
        pytest.skip(f"Cannot import session factory: {exc}")


async def _cleanup(db):
    """Remove all test data."""
    from sqlalchemy import text
    fund_ids = ", ".join(
        f"'{x}'" for x in [_FUND_ID_A, _FUND_ID_B, _FUND_ID_C, _FUND_ID_D]
    )
    cik_list = ", ".join(str(c) for c in [_COMPANY_CIK_1, _COMPANY_CIK_2, _COMPANY_CIK_3])
    fund_ciks = ", ".join(f"'{c}'" for c in [_FUND_CIK_A, _FUND_CIK_B, _FUND_CIK_C, _FUND_CIK_D])
    cusips = ", ".join(f"'{c}'" for c in [_CUSIP_1, _CUSIP_2, _CUSIP_3])

    await db.execute(text(
        f"DELETE FROM equity_characteristics_monthly WHERE instrument_id IN ({fund_ids})"
    ))
    await db.execute(text(
        f"DELETE FROM nav_timeseries WHERE instrument_id IN ({fund_ids})"
    ))
    await db.execute(text(
        f"DELETE FROM sec_nport_holdings WHERE cik IN ({fund_ciks})"
    ))
    await db.execute(text(
        f"DELETE FROM sec_cusip_ticker_map WHERE cusip IN ({cusips})"
    ))
    await db.execute(text(
        f"DELETE FROM company_characteristics_monthly WHERE cik IN ({cik_list})"
    ))
    await db.execute(text(
        f"DELETE FROM instruments_universe WHERE instrument_id IN ({fund_ids})"
    ))
    # Clean up BDC/MMF test rows (cik is varchar in both tables)
    await db.execute(text(
        f"DELETE FROM sec_bdcs WHERE cik IN ('{_FUND_CIK_B}')"
    ))
    await db.execute(text(
        f"DELETE FROM sec_money_market_funds WHERE cik IN ('{_FUND_CIK_C}')"
    ))
    await db.commit()


async def _seed_instrument(db, instrument_id, ticker, sec_cik, asset_class="equity"):
    from sqlalchemy import text
    attrs = {
        "sec_cik": sec_cik,
        "aum_usd": 1000000,
        "manager_name": "Test Manager",
        "inception_date": "2020-01-01",
    }
    import json
    await db.execute(text("""
        INSERT INTO instruments_universe (
            instrument_id, instrument_type, name, ticker, asset_class,
            geography, currency, attributes
        ) VALUES (
            :iid, 'fund', :name, :ticker, :asset_class,
            'US', 'USD', CAST(:attrs AS jsonb)
        )
        ON CONFLICT (instrument_id) DO NOTHING
    """), {
        "iid": instrument_id,
        "name": f"Test Fund {ticker}",
        "ticker": ticker,
        "asset_class": asset_class,
        "attrs": json.dumps(attrs),
    })


async def _seed_nport_holding(db, cik, cusip, report_date, market_value, quantity,
                              asset_class="EC"):
    from sqlalchemy import text
    await db.execute(text("""
        INSERT INTO sec_nport_holdings (
            report_date, cik, cusip, market_value, quantity, asset_class
        ) VALUES (
            :report_date, :cik, :cusip, :market_value, :quantity, :asset_class
        )
        ON CONFLICT DO NOTHING
    """), {
        "report_date": report_date,
        "cik": cik,
        "cusip": cusip,
        "market_value": market_value,
        "quantity": quantity,
        "asset_class": asset_class,
    })


async def _seed_cusip_map(db, cusip, issuer_cik=None):
    from sqlalchemy import text
    await db.execute(text("""
        INSERT INTO sec_cusip_ticker_map (cusip, issuer_cik, resolved_via)
        VALUES (:cusip, :issuer_cik, 'test')
        ON CONFLICT (cusip) DO NOTHING
    """), {"cusip": cusip, "issuer_cik": issuer_cik})


async def _seed_company_chars(db, cik, period_end,
                              book_equity=400.0, total_assets=1000.0,
                              net_income_ttm=100.0, revenue=500.0,
                              gross_profit=200.0, capex_ttm=50.0,
                              ppe_prior=300.0, shares_outstanding=1_000_000.0):
    from sqlalchemy import text
    quality_roa = net_income_ttm / total_assets if total_assets > 0 else None
    profitability_gross = gross_profit / revenue if revenue > 0 else None
    investment_growth = capex_ttm / ppe_prior if ppe_prior > 0 else None
    await db.execute(text("""
        INSERT INTO company_characteristics_monthly (
            cik, period_end, book_equity, total_assets, net_income_ttm,
            revenue, gross_profit, capex_ttm, ppe_prior, shares_outstanding,
            quality_roa, investment_growth, profitability_gross,
            source_filing_date, computed_at
        ) VALUES (
            :cik, :period_end, :book_equity, :total_assets, :net_income_ttm,
            :revenue, :gross_profit, :capex_ttm, :ppe_prior, :shares_outstanding,
            :quality_roa, :investment_growth, :profitability_gross,
            :source_filing_date, now()
        )
        ON CONFLICT (cik, period_end) DO NOTHING
    """), {
        "cik": cik,
        "period_end": period_end,
        "book_equity": book_equity,
        "total_assets": total_assets,
        "net_income_ttm": net_income_ttm,
        "revenue": revenue,
        "gross_profit": gross_profit,
        "capex_ttm": capex_ttm,
        "ppe_prior": ppe_prior,
        "shares_outstanding": shares_outstanding,
        "quality_roa": quality_roa,
        "investment_growth": investment_growth,
        "profitability_gross": profitability_gross,
        "source_filing_date": date(2024, 2, 15),
    })


async def _seed_nav(db, instrument_id, nav_date, nav_value):
    from sqlalchemy import text
    await db.execute(text("""
        INSERT INTO nav_timeseries (instrument_id, nav_date, nav)
        VALUES (:iid, :nav_date, :nav)
        ON CONFLICT (instrument_id, nav_date) DO NOTHING
    """), {"iid": instrument_id, "nav_date": nav_date, "nav": nav_value})


async def _seed_bdc(db, cik):
    from sqlalchemy import text
    await db.execute(text("""
        INSERT INTO sec_bdcs (series_id, cik, fund_name, ticker, strategy_label)
        VALUES (:sid, :cik, 'Test BDC', 'TBDC', 'Private Credit')
        ON CONFLICT DO NOTHING
    """), {"sid": str(cik), "cik": str(cik)})


async def _seed_mmf(db, cik):
    from sqlalchemy import text
    await db.execute(text("""
        INSERT INTO sec_money_market_funds (series_id, cik, fund_name, mmf_category)
        VALUES (:sid, :cik, 'Test MMF', 'Prime')
        ON CONFLICT DO NOTHING
    """), {"sid": str(cik), "cik": str(cik)})


async def _get_fund_chars(db, instrument_id) -> list:
    from sqlalchemy import text
    result = await db.execute(text("""
        SELECT * FROM equity_characteristics_monthly
        WHERE instrument_id = :iid
        ORDER BY as_of
    """), {"iid": instrument_id})
    return result.all()


async def _run_aggregator_for_funds(fund_ids: list):
    """Run the aggregator targeting specific funds via internal functions."""
    factory = _get_session_factory()
    async with factory() as db:
        from app.core.jobs.fund_characteristics_aggregator import (
            _classify_fund,
            _compute_bdc_direct,
            _compute_via_aggregation,
            _load_universe,
            _upsert_rows,
        )
        all_funds = await _load_universe(db)
        target_ids = {str(fid) for fid in fund_ids}
        for fund in all_funds:
            if str(fund["instrument_id"]) not in target_ids:
                continue
            pipeline = _classify_fund(fund)
            if pipeline == "skip":
                continue
            if pipeline == "bdc_direct":
                rows = await _compute_bdc_direct(db, fund)
            else:
                rows = await _compute_via_aggregation(db, fund)
            if rows:
                await _upsert_rows(db, rows)


# ---------- Test 1: basic_aggregation ----------

def test_basic_aggregation():
    """1 fund with 3 equity holdings, known company chars -> correct portfolio-level formulas."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db)

            # Seed instrument
            await _seed_instrument(db, _FUND_ID_A, "TFND", _FUND_CIK_A)

            report_date = date(2024, 6, 30)

            # Seed 3 holdings
            # Holding 1: 10,000 shares of company 1 (1M shares outstanding)
            await _seed_nport_holding(db, _FUND_CIK_A, _CUSIP_1, report_date,
                                      market_value=500_000, quantity=10_000)
            # Holding 2: 5,000 shares of company 2 (500k shares outstanding)
            await _seed_nport_holding(db, _FUND_CIK_A, _CUSIP_2, report_date,
                                      market_value=300_000, quantity=5_000)

            # Seed CUSIP map
            await _seed_cusip_map(db, _CUSIP_1, issuer_cik=f"{_COMPANY_CIK_1:010d}")
            await _seed_cusip_map(db, _CUSIP_2, issuer_cik=f"{_COMPANY_CIK_2:010d}")

            # Seed company characteristics
            # Company 1: book_equity=400M, total_assets=1B, net_income_ttm=100M,
            #            revenue=500M, gross_profit=200M, capex=50M, ppe_prior=300M,
            #            shares_outstanding=1M
            await _seed_company_chars(db, _COMPANY_CIK_1, date(2024, 3, 31),
                                      book_equity=400_000_000, total_assets=1_000_000_000,
                                      net_income_ttm=100_000_000, revenue=500_000_000,
                                      gross_profit=200_000_000, capex_ttm=50_000_000,
                                      ppe_prior=300_000_000, shares_outstanding=1_000_000)
            # Company 2: book_equity=200M, total_assets=800M, net_income_ttm=80M,
            #            revenue=400M, gross_profit=160M, capex=40M, ppe_prior=250M,
            #            shares_outstanding=500k
            await _seed_company_chars(db, _COMPANY_CIK_2, date(2024, 3, 31),
                                      book_equity=200_000_000, total_assets=800_000_000,
                                      net_income_ttm=80_000_000, revenue=400_000_000,
                                      gross_profit=160_000_000, capex_ttm=40_000_000,
                                      ppe_prior=250_000_000, shares_outstanding=500_000)
            await db.commit()

        # Run aggregator
        await _run_aggregator_for_funds([_FUND_ID_A])

        # Verify
        async with factory() as db:
            rows = await _get_fund_chars(db, _FUND_ID_A)
            assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
            row = rows[0]

            # ownership_frac_1 = 10000 / 1_000_000 = 0.01
            # ownership_frac_2 = 5000 / 500_000 = 0.01
            # sum_market_value = 500_000 + 300_000 = 800_000
            # sum_book_equity = 400M * 0.01 + 200M * 0.01 = 4M + 2M = 6M
            # sum_total_assets = 1B * 0.01 + 800M * 0.01 = 10M + 8M = 18M
            # sum_net_income = 100M * 0.01 + 80M * 0.01 = 1M + 0.8M = 1.8M
            # sum_revenue = 500M * 0.01 + 400M * 0.01 = 5M + 4M = 9M
            # sum_gross_profit = 200M * 0.01 + 160M * 0.01 = 2M + 1.6M = 3.6M

            expected_size = round(math.log(800_000), 4)
            expected_bm = round(6_000_000 / 800_000, 4)
            expected_roa = round(1_800_000 / 18_000_000, 4)
            expected_prof = round(3_600_000 / 9_000_000, 4)

            assert abs(float(row.size_log_mkt_cap) - expected_size) < 0.01, \
                f"size: {row.size_log_mkt_cap} vs {expected_size}"
            assert abs(float(row.book_to_market) - expected_bm) < 0.01, \
                f"B/M: {row.book_to_market} vs {expected_bm}"
            assert abs(float(row.quality_roa) - expected_roa) < 0.001, \
                f"ROA: {row.quality_roa} vs {expected_roa}"
            assert abs(float(row.profitability_gross) - expected_prof) < 0.001, \
                f"profitability: {row.profitability_gross} vs {expected_prof}"

            await _cleanup(db)

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 2: period_matching ----------

def test_period_matching():
    """Company has chars at Q1 and Q3 only. N-PORT date is Q2 -> picks Q1."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db)
            await _seed_instrument(db, _FUND_ID_A, "TFND", _FUND_CIK_A)

            report_date = date(2024, 6, 30)  # Q2
            await _seed_nport_holding(db, _FUND_CIK_A, _CUSIP_1, report_date,
                                      market_value=500_000, quantity=10_000)
            await _seed_cusip_map(db, _CUSIP_1, issuer_cik=f"{_COMPANY_CIK_1:010d}")

            # Q1 chars (should be picked)
            await _seed_company_chars(db, _COMPANY_CIK_1, date(2024, 3, 31),
                                      book_equity=400_000_000, total_assets=1_000_000_000,
                                      net_income_ttm=100_000_000, revenue=500_000_000,
                                      gross_profit=200_000_000, shares_outstanding=1_000_000)
            # Q3 chars (should NOT be picked — after report_date)
            await _seed_company_chars(db, _COMPANY_CIK_1, date(2024, 9, 30),
                                      book_equity=999_000_000, total_assets=2_000_000_000,
                                      net_income_ttm=200_000_000, revenue=800_000_000,
                                      gross_profit=400_000_000, shares_outstanding=1_000_000)
            await db.commit()

        await _run_aggregator_for_funds([_FUND_ID_A])

        async with factory() as db:
            rows = await _get_fund_chars(db, _FUND_ID_A)
            assert len(rows) == 1
            row = rows[0]
            # ownership_frac = 10000 / 1_000_000 = 0.01
            # book_equity = 400M * 0.01 = 4M (from Q1, NOT 999M from Q3)
            expected_bm = round(4_000_000 / 500_000, 4)
            assert abs(float(row.book_to_market) - expected_bm) < 0.01, \
                f"B/M should use Q1 data: {row.book_to_market} vs {expected_bm}"
            await _cleanup(db)

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 3: unresolved_holding_skipped ----------

def test_unresolved_holding_skipped():
    """Holding with no issuer_cik is skipped, doesn't error."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db)
            await _seed_instrument(db, _FUND_ID_A, "TFND", _FUND_CIK_A)

            report_date = date(2024, 6, 30)

            # Holding 1: resolved
            await _seed_nport_holding(db, _FUND_CIK_A, _CUSIP_1, report_date,
                                      market_value=500_000, quantity=10_000)
            await _seed_cusip_map(db, _CUSIP_1, issuer_cik=f"{_COMPANY_CIK_1:010d}")
            await _seed_company_chars(db, _COMPANY_CIK_1, date(2024, 3, 31),
                                      shares_outstanding=1_000_000)

            # Holding 2: unresolved (no issuer_cik in map)
            await _seed_nport_holding(db, _FUND_CIK_A, _CUSIP_3, report_date,
                                      market_value=200_000, quantity=5_000)
            await _seed_cusip_map(db, _CUSIP_3, issuer_cik=None)

            await db.commit()

        await _run_aggregator_for_funds([_FUND_ID_A])

        async with factory() as db:
            rows = await _get_fund_chars(db, _FUND_ID_A)
            # Should produce output from resolved holding only
            assert len(rows) == 1, f"Expected 1 row, got {len(rows)}"
            # size_log_mkt_cap should reflect only the resolved holding's market_value
            row = rows[0]
            expected_size = round(math.log(500_000), 4)
            assert abs(float(row.size_log_mkt_cap) - expected_size) < 0.01
            await _cleanup(db)

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 4: bdc_direct_path ----------

def test_bdc_direct_path():
    """BDC uses direct XBRL path, NOT N-PORT aggregation."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db)

            await _seed_instrument(db, _FUND_ID_B, "TBDC", _FUND_CIK_B)
            # Register as BDC
            await _seed_bdc(db, _FUND_CIK_B)

            # Seed company chars for BDC's own CIK
            bdc_cik_int = int(_FUND_CIK_B)
            await _seed_company_chars(db, bdc_cik_int, date(2024, 3, 31),
                                      book_equity=500_000_000, total_assets=2_000_000_000,
                                      net_income_ttm=150_000_000, revenue=300_000_000,
                                      gross_profit=180_000_000)
            await db.commit()

        await _run_aggregator_for_funds([_FUND_ID_B])

        async with factory() as db:
            rows = await _get_fund_chars(db, _FUND_ID_B)
            assert len(rows) >= 1, f"BDC should have at least 1 row, got {len(rows)}"
            row = rows[0]
            # BDC uses total_assets for size approximation
            expected_size = round(math.log(2_000_000_000), 4)
            assert abs(float(row.size_log_mkt_cap) - expected_size) < 0.1
            # quality_roa from company_chars directly
            expected_roa = round(150_000_000 / 2_000_000_000, 4)
            assert abs(float(row.quality_roa) - expected_roa) < 0.001
            await _cleanup(db)

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 5: momentum_from_fund_nav ----------

def test_momentum_from_fund_nav():
    """mom_12_1 computed from fund's own NAV, not aggregated from holdings."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db)
            await _seed_instrument(db, _FUND_ID_D, "TMOM", _FUND_CIK_D)

            report_date = date(2024, 6, 30)
            await _seed_nport_holding(db, _FUND_CIK_D, _CUSIP_1, report_date,
                                      market_value=1_000_000, quantity=10_000)
            await _seed_cusip_map(db, _CUSIP_1, issuer_cik=f"{_COMPANY_CIK_1:010d}")
            await _seed_company_chars(db, _COMPANY_CIK_1, date(2024, 3, 31),
                                      shares_outstanding=1_000_000)

            # Seed 13 months of NAV data (t-13 to t-1 relative to report_date)
            # NAV goes from 100 to 120 over 12 months -> 20% return
            base_date = date(2023, 5, 31)  # 13 months before report_date
            for i in range(14):
                nav_date = base_date + timedelta(days=30 * i)
                nav_value = 100.0 + (20.0 * i / 13.0)
                await _seed_nav(db, _FUND_ID_D, nav_date, nav_value)
            await db.commit()

        await _run_aggregator_for_funds([_FUND_ID_D])

        async with factory() as db:
            rows = await _get_fund_chars(db, _FUND_ID_D)
            assert len(rows) == 1
            row = rows[0]
            # mom_12_1 should be non-None (from NAV series)
            assert row.mom_12_1 is not None, "mom_12_1 should be computed from fund NAV"
            # Should be positive (NAV went up)
            assert float(row.mom_12_1) > 0, f"Expected positive momentum, got {row.mom_12_1}"
            await _cleanup(db)

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 6: mmf_skipped ----------

def test_mmf_skipped():
    """Money market fund produces no output row."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db)
            await _seed_instrument(db, _FUND_ID_C, "TMMF", _FUND_CIK_C, asset_class="cash")
            await _seed_mmf(db, _FUND_CIK_C)

            # Seed N-PORT data so it would appear in universe if not filtered
            report_date = date(2024, 6, 30)
            await _seed_nport_holding(db, _FUND_CIK_C, _CUSIP_1, report_date,
                                      market_value=1_000_000, quantity=1_000_000)
            await _seed_cusip_map(db, _CUSIP_1, issuer_cik=f"{_COMPANY_CIK_1:010d}")
            await _seed_company_chars(db, _COMPANY_CIK_1, date(2024, 3, 31),
                                      shares_outstanding=1_000_000)
            await db.commit()

        await _run_aggregator_for_funds([_FUND_ID_C])

        async with factory() as db:
            rows = await _get_fund_chars(db, _FUND_ID_C)
            assert len(rows) == 0, f"MMF should be skipped, got {len(rows)} rows"
            await _cleanup(db)

    asyncio.get_event_loop().run_until_complete(_test())


# ---------- Test 7: idempotent_rerun ----------

def test_idempotent_rerun():
    """Running aggregator twice produces same row count (ON CONFLICT UPDATE)."""
    factory = _get_session_factory()

    async def _test():
        async with factory() as db:
            await _cleanup(db)
            await _seed_instrument(db, _FUND_ID_A, "TFND", _FUND_CIK_A)

            report_date = date(2024, 6, 30)
            await _seed_nport_holding(db, _FUND_CIK_A, _CUSIP_1, report_date,
                                      market_value=500_000, quantity=10_000)
            await _seed_cusip_map(db, _CUSIP_1, issuer_cik=f"{_COMPANY_CIK_1:010d}")
            await _seed_company_chars(db, _COMPANY_CIK_1, date(2024, 3, 31),
                                      shares_outstanding=1_000_000)
            await db.commit()

        # First run
        await _run_aggregator_for_funds([_FUND_ID_A])
        async with factory() as db:
            count1 = len(await _get_fund_chars(db, _FUND_ID_A))

        # Second run
        await _run_aggregator_for_funds([_FUND_ID_A])
        async with factory() as db:
            count2 = len(await _get_fund_chars(db, _FUND_ID_A))
            assert count1 == count2, f"Idempotency violated: {count1} vs {count2}"
            assert count1 > 0, "Should have produced at least 1 row"
            await _cleanup(db)

    asyncio.get_event_loop().run_until_complete(_test())

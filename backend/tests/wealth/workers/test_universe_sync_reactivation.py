"""Test is_active reactivation across all universe_sync phases (PR-Q94).

Wave 6 Session 09 C-01: _deactivate_no_nav flips is_active=false for instruments
lacking nav_timeseries rows. All ON CONFLICT DO UPDATE SET clauses must restore
is_active=true on the next sync run once NAV arrives.

Tests for ETF, Registered, and BDC call the actual sync functions end-to-end.
Tests for ESMA and MMF exercise the ON CONFLICT SQL pattern directly because
the full sync functions process all rows in the source tables and pre-existing
data quality issues (duplicate yahoo_tickers via esma_securities JOIN, composite
FK on sec_fund_classes) would cause spurious failures unrelated to the fix.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db.engine import async_session_factory

# ── Helpers ──────────────────────────────────────────────────────────────


async def _get_is_active(db, ticker: str) -> bool | None:
    """Read is_active for a given ticker in instruments_universe."""
    row = (
        await db.execute(
            text("SELECT is_active FROM instruments_universe WHERE ticker = :t"),
            {"t": ticker},
        )
    ).first()
    return row[0] if row else None


async def _get_instrument_id(db, ticker: str) -> uuid.UUID | None:
    """Read instrument_id for a given ticker in instruments_universe."""
    row = (
        await db.execute(
            text("SELECT instrument_id FROM instruments_universe WHERE ticker = :t"),
            {"t": ticker},
        )
    ).first()
    return row[0] if row else None


async def _insert_nav_row(db, instrument_id: uuid.UUID) -> None:
    """Insert a single nav_timeseries row for the instrument."""
    await db.execute(
        text("""
            INSERT INTO nav_timeseries (instrument_id, nav_date, nav, return_1d)
            VALUES (:iid, :d, :nav, :ret)
            ON CONFLICT (instrument_id, nav_date) DO NOTHING
        """),
        {
            "iid": instrument_id,
            "d": date.today() - timedelta(days=1),
            "nav": Decimal("100.00"),
            "ret": Decimal("0.001"),
        },
    )


async def _cleanup_ticker(db, ticker: str) -> None:
    """Remove all test data for a ticker (FK-safe order).

    Rolls back any failed transaction before running cleanup DML.
    """
    await db.rollback()
    iid_row = (
        await db.execute(
            text("SELECT instrument_id FROM instruments_universe WHERE ticker = :t"),
            {"t": ticker},
        )
    ).first()
    if iid_row:
        iid = iid_row[0]
        await db.execute(
            text("DELETE FROM nav_timeseries WHERE instrument_id = :iid"),
            {"iid": iid},
        )
    await db.execute(
        text("DELETE FROM instruments_universe WHERE ticker = :t"),
        {"t": ticker},
    )
    await db.commit()


# ── Phase 1: SEC ETFs ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_etf_reactivation_after_deactivate():
    """is_active restored to true when ETF is re-synced after deactivation."""
    from app.domains.wealth.workers.universe_sync import (
        _deactivate_no_nav,
        _sync_sec_etfs,
    )

    ticker = "Q94ETF"

    async with async_session_factory() as db:
        try:
            # Seed sec_etfs source row
            await db.execute(
                text("""
                    INSERT INTO sec_etfs (series_id, cik, fund_name, ticker, strategy_label)
                    VALUES (:sid, :cik, :name, :ticker, :strat)
                    ON CONFLICT (series_id) DO NOTHING
                """),
                {
                    "sid": "S000099901",
                    "cik": "0009990001",
                    "name": "Q94 Test ETF",
                    "ticker": ticker,
                    "strat": "Large Cap Equity",
                },
            )
            await db.commit()

            # Phase 1: sync creates instrument with is_active=true
            await _sync_sec_etfs(db)
            assert await _get_is_active(db, ticker) is True

            # Deactivate (no NAV rows exist)
            await _deactivate_no_nav(db)
            assert await _get_is_active(db, ticker) is False

            # Insert NAV row
            iid = await _get_instrument_id(db, ticker)
            assert iid is not None
            await _insert_nav_row(db, iid)
            await db.commit()

            # Re-run sync: is_active restored via ON CONFLICT UPDATE
            await _sync_sec_etfs(db)
            assert await _get_is_active(db, ticker) is True
        finally:
            await _cleanup_ticker(db, ticker)
            await db.execute(
                text("DELETE FROM sec_etfs WHERE series_id = :sid"),
                {"sid": "S000099901"},
            )
            await db.commit()


# ── Phase 3: SEC Registered Funds ────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_registered_reactivation_after_deactivate():
    """is_active restored to true when registered fund is re-synced after deactivation.

    _sync_sec_registered was previously DO NOTHING, converted to DO UPDATE SET
    is_active = true by PR-Q94 (with DISTINCT ON to handle duplicate tickers
    across CIKs) so that deactivated instruments are reactivated on re-sync.
    """
    from app.domains.wealth.workers.universe_sync import (
        _deactivate_no_nav,
        _sync_sec_registered,
    )

    ticker = "Q94REG"

    async with async_session_factory() as db:
        try:
            # Seed sec_registered_funds source row
            await db.execute(
                text("""
                    INSERT INTO sec_registered_funds (cik, fund_name, ticker, strategy_label, fund_type)
                    VALUES (:cik, :name, :ticker, :strat, :ftype)
                    ON CONFLICT (cik) DO NOTHING
                """),
                {
                    "cik": "0009990002",
                    "name": "Q94 Test Registered Fund",
                    "ticker": ticker,
                    "strat": "Growth Equity",
                    "ftype": "mutual_fund",
                },
            )
            await db.commit()

            # Phase 3: sync creates instrument with is_active=true
            await _sync_sec_registered(db)
            assert await _get_is_active(db, ticker) is True

            # Deactivate (no NAV rows exist)
            await _deactivate_no_nav(db)
            assert await _get_is_active(db, ticker) is False

            # Insert NAV row
            iid = await _get_instrument_id(db, ticker)
            assert iid is not None
            await _insert_nav_row(db, iid)
            await db.commit()

            # Re-run sync: is_active restored via ON CONFLICT DO UPDATE
            await _sync_sec_registered(db)
            assert await _get_is_active(db, ticker) is True
        finally:
            await _cleanup_ticker(db, ticker)
            await db.execute(
                text("DELETE FROM sec_registered_funds WHERE cik = :cik"),
                {"cik": "0009990002"},
            )
            await db.commit()


# ── Phase 3b: SEC BDCs ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sec_bdc_reactivation_after_deactivate():
    """is_active restored to true when BDC is re-synced after deactivation."""
    from app.domains.wealth.workers.universe_sync import (
        _deactivate_no_nav,
        _sync_sec_bdcs,
    )

    ticker = "Q94BDC"

    async with async_session_factory() as db:
        try:
            # Seed sec_bdcs source row
            await db.execute(
                text("""
                    INSERT INTO sec_bdcs (series_id, cik, fund_name, ticker, strategy_label)
                    VALUES (:sid, :cik, :name, :ticker, :strat)
                    ON CONFLICT (series_id) DO NOTHING
                """),
                {
                    "sid": "S000099903",
                    "cik": "0009990003",
                    "name": "Q94 Test BDC",
                    "ticker": ticker,
                    "strat": "Private Credit",
                },
            )
            await db.commit()

            # Phase 3b: sync creates instrument with is_active=true
            await _sync_sec_bdcs(db)
            assert await _get_is_active(db, ticker) is True

            # Deactivate (no NAV rows exist)
            await _deactivate_no_nav(db)
            assert await _get_is_active(db, ticker) is False

            # Insert NAV row
            iid = await _get_instrument_id(db, ticker)
            assert iid is not None
            await _insert_nav_row(db, iid)
            await db.commit()

            # Re-run sync: is_active restored via ON CONFLICT UPDATE
            await _sync_sec_bdcs(db)
            assert await _get_is_active(db, ticker) is True
        finally:
            await _cleanup_ticker(db, ticker)
            await db.execute(
                text("DELETE FROM sec_bdcs WHERE series_id = :sid"),
                {"sid": "S000099903"},
            )
            await db.commit()


# ── Phase 4: ESMA UCITS (SQL mechanism test) ─────────────────────────────


@pytest.mark.asyncio
async def test_esma_fund_reactivation_after_deactivate():
    """is_active restored to true via ESMA ON CONFLICT clause after deactivation.

    Tests the ON CONFLICT SQL mechanism directly rather than calling
    _sync_esma_funds end-to-end, because the full sync processes all
    esma_funds rows and pre-existing duplicate yahoo_tickers (via the
    esma_securities LEFT JOIN) cause CardinalityViolation unrelated to
    this fix. The SQL pattern tested here is identical to the one in
    _sync_esma_funds.
    """
    from app.domains.wealth.workers.universe_sync import _deactivate_no_nav

    ticker = "Q94E.L"

    async with async_session_factory() as db:
        try:
            # Step 1: Insert instrument directly (simulates initial sync)
            await db.execute(
                text("""
                    INSERT INTO instruments_universe
                        (instrument_id, instrument_type, name, ticker,
                         asset_class, geography, currency, is_active, attributes)
                    VALUES
                        (gen_random_uuid(), 'fund', 'Q94 Test UCITS Fund', :ticker,
                         'equity', 'dm_europe', 'EUR', true,
                         '{"fund_lei": "Q94D00000000000LEI01", "fund_subtype": "ucits",
                           "aum_usd": null, "manager_name": "Q94 ManCo",
                           "inception_date": null, "source": "universe_sync"}'::jsonb)
                    ON CONFLICT (ticker) DO NOTHING
                """),
                {"ticker": ticker},
            )
            await db.commit()
            assert await _get_is_active(db, ticker) is True

            # Step 2: Deactivate (no NAV rows exist)
            await _deactivate_no_nav(db)
            assert await _get_is_active(db, ticker) is False

            # Step 3: Insert NAV row
            iid = await _get_instrument_id(db, ticker)
            assert iid is not None
            await _insert_nav_row(db, iid)
            await db.commit()

            # Step 4: Re-upsert using ESMA ON CONFLICT pattern (is_active = EXCLUDED.is_active)
            await db.execute(
                text("""
                    INSERT INTO instruments_universe
                        (instrument_id, instrument_type, name, ticker,
                         asset_class, geography, currency, is_active, attributes)
                    VALUES
                        (gen_random_uuid(), 'fund', 'Q94 Test UCITS Fund', :ticker,
                         'equity', 'dm_europe', 'EUR', true,
                         '{"fund_lei": "Q94D00000000000LEI01", "fund_subtype": "ucits",
                           "aum_usd": null, "manager_name": "Q94 ManCo",
                           "inception_date": null, "source": "universe_sync"}'::jsonb)
                    ON CONFLICT (ticker) DO UPDATE SET
                        name = EXCLUDED.name,
                        is_active = EXCLUDED.is_active,
                        attributes = instruments_universe.attributes || EXCLUDED.attributes,
                        updated_at = now()
                """),
                {"ticker": ticker},
            )
            await db.commit()

            # Assert: is_active restored to true
            assert await _get_is_active(db, ticker) is True
        finally:
            await _cleanup_ticker(db, ticker)


# ── Phase 5: SEC Money Market Funds (SQL mechanism test) ─────────────────


@pytest.mark.asyncio
async def test_sec_mmf_reactivation_after_deactivate():
    """is_active restored to true via MMF ON CONFLICT clause after deactivation.

    Tests the ON CONFLICT SQL mechanism directly rather than calling
    _sync_sec_mmfs end-to-end, because seeding the MMF source tables
    requires satisfying a composite FK (sec_fund_classes.cik → sec_registered_funds.cik)
    which would create excessive coupling to unrelated table state.
    The SQL pattern tested here is identical to the one in _sync_sec_mmfs.
    """
    from app.domains.wealth.workers.universe_sync import _deactivate_no_nav

    ticker = "Q94MMF"

    async with async_session_factory() as db:
        try:
            # Step 1: Insert instrument directly (simulates initial sync)
            await db.execute(
                text("""
                    INSERT INTO instruments_universe
                        (instrument_id, instrument_type, name, ticker,
                         asset_class, geography, currency, is_active, attributes)
                    VALUES
                        (gen_random_uuid(), 'fund', 'Q94 Test MMF', :ticker,
                         'cash', 'north_america', 'USD', true,
                         '{"series_id": "S000099905", "fund_subtype": "mmf",
                           "sec_universe": "money_market", "strategy_label": "Money Market",
                           "aum_usd": null, "manager_name": "Q94 MMF Manager",
                           "inception_date": null, "source": "universe_sync"}'::jsonb)
                    ON CONFLICT (ticker) DO NOTHING
                """),
                {"ticker": ticker},
            )
            await db.commit()
            assert await _get_is_active(db, ticker) is True

            # Step 2: Deactivate (no NAV rows exist)
            await _deactivate_no_nav(db)
            assert await _get_is_active(db, ticker) is False

            # Step 3: Insert NAV row
            iid = await _get_instrument_id(db, ticker)
            assert iid is not None
            await _insert_nav_row(db, iid)
            await db.commit()

            # Step 4: Re-upsert using MMF ON CONFLICT pattern (is_active = EXCLUDED.is_active)
            await db.execute(
                text("""
                    INSERT INTO instruments_universe
                        (instrument_id, instrument_type, name, ticker,
                         asset_class, geography, currency, is_active, attributes)
                    VALUES
                        (gen_random_uuid(), 'fund', 'Q94 Test MMF', :ticker,
                         'cash', 'north_america', 'USD', true,
                         '{"series_id": "S000099905", "fund_subtype": "mmf",
                           "sec_universe": "money_market", "strategy_label": "Money Market",
                           "aum_usd": null, "manager_name": "Q94 MMF Manager",
                           "inception_date": null, "source": "universe_sync"}'::jsonb)
                    ON CONFLICT (ticker) DO UPDATE SET
                        name = EXCLUDED.name,
                        is_active = EXCLUDED.is_active,
                        asset_class = 'cash',
                        attributes = instruments_universe.attributes || EXCLUDED.attributes,
                        updated_at = now()
                """),
                {"ticker": ticker},
            )
            await db.commit()

            # Assert: is_active restored to true
            assert await _get_is_active(db, ticker) is True
        finally:
            await _cleanup_ticker(db, ticker)

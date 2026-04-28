"""Shared fixtures for worker smoke tests.

Seeds a minimal test org with one universe fund and one org-imported fund
against the real Docker-compose PostgreSQL. Module-scoped for efficiency —
all worker tests in this directory share the same seeded state.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.core.db.engine import async_session_factory

# Deterministic test-only UUIDs (f00d prefix — never conflicts with real tenants)
TEST_ORG_ID = uuid.UUID("f00d0000-0000-0000-0000-000000000001")
TEST_INSTRUMENT_ID = uuid.UUID("f00d0000-0000-0000-0000-000000000010")
TEST_INSTRUMENT_ORG_ID = uuid.UUID("f00d0000-0000-0000-0000-000000000011")


@pytest.fixture(scope="module")
async def seeded_test_org():
    """Seed a minimal org with one fund + NAV history for worker smoke tests.

    Yields the org_id; tears down all seeded data after module completes.
    """
    org_id = TEST_ORG_ID
    instrument_id = TEST_INSTRUMENT_ID
    instrument_org_id = TEST_INSTRUMENT_ORG_ID

    async with async_session_factory() as db:
        # Set RLS context for the test org (set_config with true = transaction-scoped)
        await db.execute(
            text("SELECT set_config('app.current_organization_id', :oid, true)"),
            {"oid": str(org_id)},
        )

        # 1. Seed instruments_universe (global, no RLS)
        await db.execute(
            text("""
                INSERT INTO instruments_universe
                    (instrument_id, instrument_type, name, ticker, asset_class,
                     geography, currency, is_active, attributes)
                VALUES
                    (:iid, 'fund', 'Q86 Smoke Test Fund', 'Q86TST', 'equity',
                     'US', 'USD', true,
                     CAST(:attrs AS jsonb))
                ON CONFLICT (instrument_id) DO NOTHING
            """),
            {
                "iid": instrument_id,
                "attrs": '{"aum_usd": 1000000000, "manager_name": "Q86 Test Manager", "inception_date": "2020-01-01"}',
            },
        )

        # 2. Seed instruments_org (org-scoped)
        await db.execute(
            text("""
                INSERT INTO instruments_org
                    (id, instrument_id, organization_id, block_id, approval_status)
                VALUES
                    (:ioid, :iid, :oid, NULL, 'watchlist')
                ON CONFLICT (id) DO NOTHING
            """),
            {"ioid": instrument_org_id, "iid": instrument_id, "oid": org_id},
        )

        # 3. Seed nav_timeseries — 60 days of synthetic NAV
        today = date.today()
        nav_values = []
        base_nav = Decimal("100.00")
        for i in range(60):
            d = today - timedelta(days=60 - i)
            nav = base_nav + Decimal(str(i * 0.1))
            ret_1d = Decimal("0.001") if i > 0 else Decimal("0")
            nav_values.append({"iid": instrument_id, "d": d, "nav": nav, "ret": ret_1d})

        for row in nav_values:
            await db.execute(
                text("""
                    INSERT INTO nav_timeseries (instrument_id, nav_date, nav, return_1d)
                    VALUES (:iid, :d, :nav, :ret)
                    ON CONFLICT (instrument_id, nav_date) DO NOTHING
                """),
                row,
            )

        # 4. Seed a minimal macro_data row (needed for risk_free_rate lookup)
        await db.execute(
            text("""
                INSERT INTO macro_data (series_id, obs_date, value)
                VALUES ('DFF', :d, 5.33)
                ON CONFLICT (series_id, obs_date) DO NOTHING
            """),
            {"d": today - timedelta(days=1)},
        )

        await db.commit()

    yield org_id

    # ── Teardown (FK-safe order: children before parents) ────
    async with async_session_factory() as db:
        # screening_results → screening_runs (FK)
        await db.execute(
            text("""
                DELETE FROM screening_results
                WHERE run_id IN (
                    SELECT run_id FROM screening_runs WHERE organization_id = :oid
                )
            """),
            {"oid": org_id},
        )
        await db.execute(
            text("DELETE FROM screening_runs WHERE organization_id = :oid"),
            {"oid": org_id},
        )
        await db.execute(
            text("DELETE FROM fund_risk_metrics WHERE instrument_id = :iid"),
            {"iid": instrument_id},
        )
        await db.execute(
            text("DELETE FROM nav_timeseries WHERE instrument_id = :iid"),
            {"iid": instrument_id},
        )
        await db.execute(
            text("DELETE FROM instruments_org WHERE organization_id = :oid"),
            {"oid": org_id},
        )
        await db.execute(
            text("DELETE FROM instruments_universe WHERE instrument_id = :iid"),
            {"iid": instrument_id},
        )
        await db.commit()

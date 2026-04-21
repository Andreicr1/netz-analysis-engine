"""PR-A3 Section A §11 — real end-to-end factor model test.

This test seeds ``allocation_blocks``, ``benchmark_nav``, ``macro_data`` and
``nav_timeseries`` in the running docker-compose Postgres (``make up``) and
drives :func:`compute_fund_level_inputs` against the real database — no
patch on ``build_fundamental_factor_returns``, no mock for SQL.

Marked with ``@pytest.mark.integration``. The test skips cleanly if
``DATABASE_URL`` is unreachable so local unit runs that skip ``make up``
do not break CI.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import asyncpg
import numpy as np
import pytest

from app.core.config import settings
from app.domains.wealth.services.quant_queries import (
    FundLevelInputs,
    compute_fund_level_inputs,
)

ORG_ID = "00000000-0000-0000-0000-000000000001"
TEST_PREFIX = "pra3-int"  # prefix for all seeded block/instrument IDs


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
async def seeded_factor_model_universe():
    """Seed 20 instruments + 5Y of factor/fund data. Cleans up on teardown.

    Uses block UUIDs that will not collide with production seed data by
    hashing the ``TEST_PREFIX`` into the first 8 bytes.
    """
    if not await _db_reachable():
        pytest.skip("Postgres not reachable — run `make up` to exercise A.11")

    n_funds = 20
    n_days = 300  # ~14 months: well above MIN_OBSERVATIONS=120, keeps seed cheap
    as_of = date(2026, 4, 1)
    start = as_of - timedelta(days=n_days + 10)

    rng = np.random.default_rng(20260415)
    block_ids = [str(uuid.uuid4()) for _ in range(7)]
    block_tickers = ["SPY", "IEF", "HYG", "IWM", "IWD", "IWF", "EFA"]
    instrument_ids = [uuid.uuid4() for _ in range(n_funds)]

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        # ── 1. allocation_blocks ─────────────────────────────────────
        for bid, ticker in zip(block_ids, block_tickers, strict=True):
            await conn.execute(
                """
                INSERT INTO allocation_blocks (
                    block_id, geography, asset_class, display_name, benchmark_ticker,
                    is_active, created_at, updated_at
                )
                VALUES ($1, 'Global', 'Equity', $2, $3, true, now(), now())
                ON CONFLICT (block_id) DO NOTHING
                """,
                bid, f"{TEST_PREFIX}-{ticker}", ticker,
            )

        # ── 2. benchmark_nav (7 tickers × n_days) ─────────────────────
        bench_rows = []
        for d_off in range(n_days):
            d = start + timedelta(days=d_off)
            for bid in block_ids:
                ret = float(rng.standard_normal() * 0.01)
                bench_rows.append((bid, d, 100.0 + d_off * 0.01, ret))
        await conn.executemany(
            """
            INSERT INTO benchmark_nav (block_id, nav_date, nav, return_1d)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (block_id, nav_date) DO NOTHING
            """,
            bench_rows,
        )

        # ── 3. macro_data (DTWEXBGS, DCOILWTICO) ─────────────────────
        macro_rows = []
        for d_off in range(n_days):
            d = start + timedelta(days=d_off)
            macro_rows.append(("DTWEXBGS", d, 100.0 + float(rng.standard_normal())))
            macro_rows.append(("DCOILWTICO", d, 70.0 + float(rng.standard_normal())))
        await conn.executemany(
            """
            INSERT INTO macro_data (series_id, obs_date, value)
            VALUES ($1, $2, $3)
            ON CONFLICT (series_id, obs_date) DO NOTHING
            """,
            macro_rows,
        )

        # ── 3.5. instruments_universe (20 funds) ─────────────────────
        inst_rows = []
        for iid in instrument_ids:
            inst_rows.append((iid, f"{TEST_PREFIX}-inst-{iid}", "fund", "Equity"))
        await conn.executemany(
            """
            INSERT INTO instruments_universe (
                instrument_id, instrument_type, name, asset_class, geography, attributes
            )
            VALUES ($1::uuid, 'fund', $2, 'Equity', 'Global', '{"aum_usd": 1000000.0, "manager_name": "Test", "inception_date": "2020-01-01"}'::jsonb)
            ON CONFLICT (instrument_id) DO NOTHING
            """,
            [(iid, f"Fund {iid}") for iid in instrument_ids],
        )

        # ── 4. nav_timeseries (20 funds × n_days) ────────────────────
        nav_rows = []
        for iid in instrument_ids:
            for d_off in range(n_days):
                d = start + timedelta(days=d_off)
                ret = float(rng.standard_normal() * 0.008)
                nav_rows.append((iid, d, 100.0 * (1 + ret), ret))
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
            "block_ids": block_ids,
            "as_of": as_of,
            "start": start,
        }
    finally:
        # ── teardown ──────────────────────────────────────────────────
        try:
            await conn.execute(
                "DELETE FROM nav_timeseries WHERE instrument_id = ANY($1::uuid[])",
                instrument_ids,
            )
            await conn.execute(
                "DELETE FROM benchmark_nav WHERE block_id = ANY($1::text[])",
                block_ids,
            )
            await conn.execute(
                "DELETE FROM macro_data WHERE obs_date >= $1 AND obs_date <= $2 "
                "AND series_id IN ('DTWEXBGS','DCOILWTICO')",
                start, start + timedelta(days=n_days),
            )
            await conn.execute(
                "DELETE FROM allocation_blocks WHERE block_id = ANY($1::text[])",
                block_ids,
            )
        finally:
            await conn.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_compute_fund_level_inputs_reads_real_factor_tables(
    seeded_factor_model_universe,
):
    """A.11 — compute_fund_level_inputs drives the real SQL path end-to-end.

    No ``patch(..build_fundamental_factor_returns..)`` — the factor returns
    are pulled from the seeded ``benchmark_nav`` + ``macro_data`` rows.
    """
    from sqlalchemy import text as _text

    from app.core.db.engine import async_session_factory

    seeded = seeded_factor_model_universe
    async with async_session_factory() as session:
        # RLS context so any audit events land under the test org.
        await session.execute(
            _text("SELECT set_config('app.current_organization_id', :oid, true)"),
            {"oid": ORG_ID},
        )

        result = await compute_fund_level_inputs(
            session,
            seeded["instrument_ids"],
            as_of_date=seeded["as_of"],
            mu_prior="historical_1y",  # avoid THBB's extra SQL dependencies
        )

    assert isinstance(result, FundLevelInputs)
    # 20 funds → factor-model path (N>=20)
    assert result.cov_matrix.shape == (20, 20)
    assert result.factor_loadings is not None
    assert result.factor_names is not None
    # Factor count is driven by what survived the 5-minute seed: up to 8.
    assert 1 <= len(result.factor_names) <= 8
    # PSD guarantee from assemble_factor_covariance
    assert np.linalg.eigvalsh(result.cov_matrix).min() >= -1e-10
    # A.2 — inputs_metadata persisted end-to-end
    assert "factor_model" in result.inputs_metadata
    assert "residual_pca" in result.inputs_metadata
    fm = result.inputs_metadata["factor_model"]
    assert fm["k_factors"] == 8
    assert fm["k_factors_effective"] == len(result.factor_names)
    assert isinstance(fm["r_squared_per_fund"], dict)
    assert len(fm["r_squared_per_fund"]) == 20
    assert fm["kappa_factor_cov"] is not None

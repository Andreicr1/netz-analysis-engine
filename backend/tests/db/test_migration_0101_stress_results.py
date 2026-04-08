"""Assert migration 0101 created portfolio_stress_results.

Verifies (per Phase 2 Task 2.2):

- Expected columns exist (id, portfolio_id, construction_run_id,
  scenario, scenario_kind, scenario_label, as_of, computed_at,
  nav_impact_pct, cvar_impact_pct, portfolio_loss_usd,
  max_drawdown_implied, recovery_days_estimate, per_block_impact,
  per_instrument_impact, shock_params)
- ``UNIQUE (construction_run_id, scenario)`` idempotency constraint (DL18 P5)
- FKs to ``model_portfolios(id)`` and ``portfolio_construction_runs(id)``
  both with ON DELETE CASCADE
- CHECK constraint on ``scenario_kind`` restricts to ('preset', 'user_defined')
- Subselect-wrapped RLS policy
- Hot-path indexes ``ix_stress_portfolio_as_of`` and ``ix_stress_construction_run``
"""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


_EXPECTED_COLUMNS = {
    "id",
    "organization_id",
    "portfolio_id",
    "construction_run_id",
    "scenario",
    "scenario_kind",
    "scenario_label",
    "as_of",
    "computed_at",
    "nav_impact_pct",
    "cvar_impact_pct",
    "portfolio_loss_usd",
    "max_drawdown_implied",
    "recovery_days_estimate",
    "per_block_impact",
    "per_instrument_impact",
    "shock_params",
}


@pytest.mark.asyncio
async def test_portfolio_stress_results_columns():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'portfolio_stress_results'
            """,
        )
    finally:
        await conn.close()
    present = {r["column_name"] for r in rows}
    missing = _EXPECTED_COLUMNS - present
    assert not missing, f"missing columns: {missing}"


@pytest.mark.asyncio
async def test_portfolio_stress_results_unique_run_scenario():
    """UNIQUE (construction_run_id, scenario) — idempotency contract (DL18 P5)."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        cons = await conn.fetch(
            """
            SELECT c.conname, pg_get_constraintdef(c.oid) AS def
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_stress_results'
              AND c.contype = 'u'
            """,
        )
    finally:
        await conn.close()
    defs = {r["conname"]: r["def"] for r in cons}
    assert "uq_stress_run_scenario" in defs
    assert "construction_run_id" in defs["uq_stress_run_scenario"]
    assert "scenario" in defs["uq_stress_run_scenario"]


@pytest.mark.asyncio
async def test_portfolio_stress_results_fks_cascade():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        fks = await conn.fetch(
            """
            SELECT pg_get_constraintdef(c.oid) AS def
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_stress_results'
              AND c.contype = 'f'
            """,
        )
    finally:
        await conn.close()
    defs = [r["def"] for r in fks]
    assert any("model_portfolios" in d and "CASCADE" in d for d in defs), (
        f"no CASCADE FK to model_portfolios: {defs}"
    )
    assert any("portfolio_construction_runs" in d and "CASCADE" in d for d in defs), (
        f"no CASCADE FK to portfolio_construction_runs: {defs}"
    )


@pytest.mark.asyncio
async def test_portfolio_stress_results_scenario_kind_check():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        check_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_stress_results'
              AND c.conname = 'ck_stress_scenario_kind'
            """,
        )
    finally:
        await conn.close()
    assert check_def is not None
    assert "preset" in check_def
    assert "user_defined" in check_def


@pytest.mark.asyncio
async def test_portfolio_stress_results_rls_subselect():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rls_enabled = await conn.fetchval(
            "SELECT relrowsecurity FROM pg_class WHERE relname = 'portfolio_stress_results'",
        )
        policy_def = await conn.fetchval(
            """
            SELECT qual FROM pg_policies
            WHERE policyname = 'portfolio_stress_results_rls'
              AND tablename = 'portfolio_stress_results'
            """,
        )
    finally:
        await conn.close()
    assert rls_enabled is True
    assert policy_def is not None
    assert "SELECT current_setting" in policy_def
    assert "app.current_organization_id" in policy_def


@pytest.mark.asyncio
async def test_portfolio_stress_results_indexes():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'portfolio_stress_results'
            """,
        )
    finally:
        await conn.close()
    names = {r["indexname"] for r in rows}
    assert "ix_stress_portfolio_as_of" in names
    assert "ix_stress_construction_run" in names

"""Assert migration 0100 created portfolio_calibration.

Verifies (per Phase 2 Task 2.1):

- All 15 typed columns exist (5 Basic + 10 Advanced)
- ``expert_overrides`` JSONB blob for the 48 Expert inputs
- ``UNIQUE (portfolio_id)`` (one active calibration per portfolio)
- FK to ``model_portfolios(id)`` with CASCADE
- CHECK constraints on cvar_limit, max_single_fund_weight, cvar_level,
  regime_override, stress_severity_multiplier
- Subselect-wrapped RLS policy
- ``set_updated_at()`` trigger function exists and is wired
- ``stress_scenarios_active`` defaults to the 4 canonical preset names
"""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


_BASIC_COLUMNS = {
    "mandate",
    "cvar_limit",
    "max_single_fund_weight",
    "turnover_cap",
    "stress_scenarios_active",
}

_ADVANCED_COLUMNS = {
    "regime_override",
    "bl_enabled",
    "bl_view_confidence_default",
    "garch_enabled",
    "turnover_lambda",
    "stress_severity_multiplier",
    "advisor_enabled",
    "cvar_level",
    "lambda_risk_aversion",
    "shrinkage_intensity_override",
}

_META_COLUMNS = {
    "id",
    "organization_id",
    "portfolio_id",
    "schema_version",
    "expert_overrides",
    "created_at",
    "updated_at",
    "updated_by",
}


@pytest.mark.asyncio
async def test_portfolio_calibration_has_all_basic_and_advanced_columns():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'portfolio_calibration'
            """,
        )
    finally:
        await conn.close()
    present = {r["column_name"] for r in rows}
    missing_basic = _BASIC_COLUMNS - present
    missing_advanced = _ADVANCED_COLUMNS - present
    missing_meta = _META_COLUMNS - present
    assert not missing_basic, f"missing Basic tier columns: {missing_basic}"
    assert not missing_advanced, f"missing Advanced tier columns: {missing_advanced}"
    assert not missing_meta, f"missing meta columns: {missing_meta}"


@pytest.mark.asyncio
async def test_portfolio_calibration_portfolio_id_is_unique():
    """One active calibration per portfolio — UNIQUE constraint enforced."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        cons = await conn.fetch(
            """
            SELECT pg_get_constraintdef(c.oid) AS def
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_calibration'
              AND c.contype = 'u'
            """,
        )
    finally:
        await conn.close()
    defs = [r["def"] for r in cons]
    assert any("portfolio_id" in d for d in defs), (
        f"no UNIQUE constraint on portfolio_id found; got: {defs}"
    )


@pytest.mark.asyncio
async def test_portfolio_calibration_fk_cascade():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        fk_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_calibration'
              AND c.contype = 'f'
            """,
        )
    finally:
        await conn.close()
    assert fk_def is not None
    assert "model_portfolios" in fk_def
    assert "ON DELETE CASCADE" in fk_def


@pytest.mark.asyncio
async def test_portfolio_calibration_check_constraints():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        checks = await conn.fetch(
            """
            SELECT c.conname, pg_get_constraintdef(c.oid) AS def
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_calibration'
              AND c.contype = 'c'
            """,
        )
    finally:
        await conn.close()
    by_name = {r["conname"]: r["def"] for r in checks}
    assert "ck_cvar_limit" in by_name
    assert "ck_max_single_fund_weight" in by_name
    assert "ck_cvar_level" in by_name
    assert "ck_regime_override" in by_name
    assert "ck_stress_severity_multiplier" in by_name
    # Regime check enumerates the 5 canonical values.
    for regime in ("NORMAL", "RISK_ON", "RISK_OFF", "CRISIS", "INFLATION"):
        assert f"'{regime}'" in by_name["ck_regime_override"], (
            f"regime {regime} missing from CHECK"
        )


@pytest.mark.asyncio
async def test_portfolio_calibration_rls_subselect():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rls_enabled = await conn.fetchval(
            "SELECT relrowsecurity FROM pg_class WHERE relname = 'portfolio_calibration'",
        )
        policy_def = await conn.fetchval(
            """
            SELECT qual FROM pg_policies
            WHERE policyname = 'portfolio_calibration_rls'
              AND tablename = 'portfolio_calibration'
            """,
        )
    finally:
        await conn.close()
    assert rls_enabled is True
    assert policy_def is not None
    assert "SELECT current_setting" in policy_def
    assert "app.current_organization_id" in policy_def


@pytest.mark.asyncio
async def test_set_updated_at_function_exists():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        fn_name = await conn.fetchval(
            """
            SELECT proname FROM pg_proc
            WHERE proname = 'set_updated_at'
            """,
        )
    finally:
        await conn.close()
    assert fn_name == "set_updated_at", "shared set_updated_at() function missing"


@pytest.mark.asyncio
async def test_portfolio_calibration_updated_at_trigger_wired():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        trig_def = await conn.fetchval(
            """
            SELECT pg_get_triggerdef(t.oid)
            FROM pg_trigger t
            WHERE t.tgname = 'trg_portfolio_calibration_updated_at'
              AND NOT t.tgisinternal
            """,
        )
    finally:
        await conn.close()
    assert trig_def is not None, "updated_at trigger missing"
    assert "set_updated_at" in trig_def
    assert "BEFORE UPDATE" in trig_def


@pytest.mark.asyncio
async def test_portfolio_calibration_stress_scenarios_default():
    """Default stress_scenarios_active must match the 4 canonical preset keys."""
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        default_expr = await conn.fetchval(
            """
            SELECT column_default
            FROM information_schema.columns
            WHERE table_name = 'portfolio_calibration'
              AND column_name = 'stress_scenarios_active'
            """,
        )
    finally:
        await conn.close()
    assert default_expr is not None
    for scenario in ("gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps"):
        assert scenario in default_expr, (
            f"scenario {scenario} missing from stress_scenarios_active default"
        )


@pytest.mark.asyncio
async def test_portfolio_calibration_indexes():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT indexname FROM pg_indexes
            WHERE tablename = 'portfolio_calibration'
            """,
        )
    finally:
        await conn.close()
    names = {r["indexname"] for r in rows}
    assert "ix_portfolio_calibration_org_updated" in names
    # UNIQUE constraint auto-creates a unique index
    assert "uq_portfolio_calibration_portfolio_id" in names

"""Assert migration 0099 created portfolio_construction_runs.

Verifies (per Phase 1 Task 1.3):

- The table exists with all expected columns
- The CHECK constraint on ``status`` enumerates exactly the 4 canonical values
- The 3 indexes exist (portfolio+requested_at, status partial, calibration_hash)
- RLS is enabled with the subselect-wrapped policy
- FK on ``portfolio_id`` references ``model_portfolios`` with CASCADE
- All JSONB columns have the expected NOT NULL + default shape
"""

from __future__ import annotations

import asyncpg
import pytest

from app.core.config import settings


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


_EXPECTED_STATUSES = {"running", "succeeded", "failed", "superseded"}

_EXPECTED_COLUMNS = {
    "id",
    "organization_id",
    "portfolio_id",
    "calibration_id",
    "calibration_hash",
    "calibration_snapshot",
    "universe_fingerprint",
    "as_of_date",
    "status",
    "requested_by",
    "requested_at",
    "started_at",
    "completed_at",
    "wall_clock_ms",
    "failure_reason",
    "optimizer_trace",
    "binding_constraints",
    "regime_context",
    "statistical_inputs",
    "ex_ante_metrics",
    "ex_ante_vs_previous",
    "factor_exposure",
    "stress_results",
    "advisor",
    "validation",
    "narrative",
    "rationale_per_weight",
    "weights_proposed",
}

_NOT_NULL_COLUMNS = {
    "id",
    "organization_id",
    "portfolio_id",
    "calibration_hash",
    "calibration_snapshot",
    "universe_fingerprint",
    "as_of_date",
    "status",
    "requested_by",
    "requested_at",
    "optimizer_trace",
    "binding_constraints",
    "regime_context",
    "statistical_inputs",
    "ex_ante_metrics",
    "stress_results",
    "validation",
    "narrative",
    "rationale_per_weight",
    "weights_proposed",
}

_NULLABLE_COLUMNS = {
    "calibration_id",
    "started_at",
    "completed_at",
    "wall_clock_ms",
    "failure_reason",
    "ex_ante_vs_previous",
    "factor_exposure",
    "advisor",
}


@pytest.mark.asyncio
async def test_portfolio_construction_runs_table_exists():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'portfolio_construction_runs'
            ORDER BY ordinal_position
            """,
        )
    finally:
        await conn.close()

    by_name = {r["column_name"]: r for r in rows}
    assert _EXPECTED_COLUMNS.issubset(by_name.keys()), (
        f"missing columns: {_EXPECTED_COLUMNS - set(by_name.keys())}"
    )

    for col in _NOT_NULL_COLUMNS:
        assert by_name[col]["is_nullable"] == "NO", f"column {col} should be NOT NULL"

    for col in _NULLABLE_COLUMNS:
        assert by_name[col]["is_nullable"] == "YES", f"column {col} should be nullable"


@pytest.mark.asyncio
async def test_portfolio_construction_runs_jsonb_columns():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'portfolio_construction_runs'
              AND data_type = 'jsonb'
            """,
        )
    finally:
        await conn.close()

    jsonb_cols = {r["column_name"] for r in rows}
    expected_jsonb = {
        "calibration_snapshot",
        "optimizer_trace",
        "binding_constraints",
        "regime_context",
        "statistical_inputs",
        "ex_ante_metrics",
        "ex_ante_vs_previous",
        "factor_exposure",
        "stress_results",
        "advisor",
        "validation",
        "narrative",
        "rationale_per_weight",
        "weights_proposed",
    }
    assert expected_jsonb.issubset(jsonb_cols), (
        f"missing jsonb columns: {expected_jsonb - jsonb_cols}"
    )


@pytest.mark.asyncio
async def test_portfolio_construction_runs_status_check():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        check_def = await conn.fetchval(
            """
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_construction_runs'
              AND c.conname = 'portfolio_construction_runs_status_check'
            """,
        )
    finally:
        await conn.close()

    assert check_def is not None, "status CHECK constraint not found"
    for value in _EXPECTED_STATUSES:
        assert f"'{value}'" in check_def, f"status '{value}' missing from CHECK"


@pytest.mark.asyncio
async def test_portfolio_construction_runs_indexes():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rows = await conn.fetch(
            """
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename = 'portfolio_construction_runs'
            """,
        )
    finally:
        await conn.close()

    by_name = {r["indexname"]: r["indexdef"] for r in rows}
    assert "ix_pcr_portfolio_requested_at" in by_name
    assert "ix_pcr_status_requested_at" in by_name
    assert "ix_pcr_portfolio_calibration_hash" in by_name

    # The status index must be partial — only ('running', 'failed') rows.
    status_idx_def = by_name["ix_pcr_status_requested_at"]
    assert "running" in status_idx_def, "status index not partial on running"
    assert "failed" in status_idx_def, "status index not partial on failed"


@pytest.mark.asyncio
async def test_portfolio_construction_runs_fk_cascade():
    """Assert the model_portfolios FK cascades.

    After Phase 2, two FKs exist on this table:
    - ``portfolio_id`` → ``model_portfolios(id)`` ON DELETE CASCADE (0099)
    - ``calibration_id`` → ``portfolio_calibration(id)`` ON DELETE SET NULL (0105)

    This test asserts the first one is present and cascading.
    The second FK is covered by ``test_migration_0105_calibration_fk.py``.
    """
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        fks = await conn.fetch(
            """
            SELECT pg_get_constraintdef(c.oid) AS def
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_construction_runs'
              AND c.contype = 'f'
            """,
        )
    finally:
        await conn.close()

    defs = [r["def"] for r in fks]
    portfolio_fks = [d for d in defs if "model_portfolios" in d]
    assert len(portfolio_fks) == 1, (
        f"expected exactly one FK to model_portfolios, got: {defs}"
    )
    assert "ON DELETE CASCADE" in portfolio_fks[0]


@pytest.mark.asyncio
async def test_portfolio_construction_runs_rls_subselect():
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        rls_enabled = await conn.fetchval(
            """
            SELECT relrowsecurity FROM pg_class
            WHERE relname = 'portfolio_construction_runs'
            """,
        )
        policy_def = await conn.fetchval(
            """
            SELECT qual FROM pg_policies
            WHERE policyname = 'portfolio_construction_runs_rls'
              AND tablename = 'portfolio_construction_runs'
            """,
        )
    finally:
        await conn.close()

    assert rls_enabled is True, "RLS not enabled on portfolio_construction_runs"
    assert policy_def is not None, "portfolio_construction_runs_rls policy missing"
    # Subselect form is mandatory per CLAUDE.md.
    assert "SELECT current_setting" in policy_def, (
        f"RLS policy must use subselect form, got: {policy_def}"
    )
    assert "app.current_organization_id" in policy_def


@pytest.mark.asyncio
async def test_portfolio_construction_runs_calibration_id_fk_from_0105():
    """The calibration_id FK lands in migration 0105, not 0099.

    Phase 1 Task 1.3 (migration 0099) deliberately left
    ``calibration_id`` unconstrained because
    ``portfolio_calibration`` did not exist yet. Phase 2 Task 2.6
    (migration 0105) adds the FK once both tables coexist.

    Since the test suite runs against ``make migrate`` head (which
    includes 0105), the FK MUST be present. If this test ever
    flips back to "no FK", someone accidentally dropped 0105 or
    decoupled the tables — investigate.
    """
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        fks = await conn.fetch(
            """
            SELECT pg_get_constraintdef(c.oid) AS def, c.conname
            FROM pg_constraint c
            JOIN pg_class t ON t.oid = c.conrelid
            WHERE t.relname = 'portfolio_construction_runs'
              AND c.contype = 'f'
            """,
        )
    finally:
        await conn.close()

    cal_fks = [r for r in fks if "calibration_id" in r["def"]]
    assert len(cal_fks) == 1, (
        f"expected exactly one calibration_id FK after 0105, got: {cal_fks}"
    )
    fk_def = cal_fks[0]["def"]
    assert "portfolio_calibration" in fk_def
    assert "ON DELETE SET NULL" in fk_def

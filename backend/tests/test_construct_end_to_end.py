"""End-to-end tests for the /construct pipeline.

Phase 3 Task 3.7 of `docs/superpowers/plans/2026-04-08-portfolio-enterprise-workbench.md`.

Covers three paths from the plan:

1. **Happy path** — executor runs to completion with ``status='succeeded'``
   and all enrichment columns populated (optimizer_trace, stress_results,
   advisor, validation, narrative, ex_ante_metrics, weights_proposed).
2. **Validation block path** — optimizer produces weights that violate
   min_diversification_count, the gate raises block-severity failures
   and the run is still persisted (the block doesn't fail the run —
   per OD-5 soft-block semantics the gate records the failure and
   the state machine keeps the ``approve`` action conditionally visible).
3. **Advisor disabled path** — ``calibration.advisor_enabled=False``
   means the run completes with ``advisor is None``.

The ``_run_construction_async`` call is patched via
``unittest.mock.patch`` so the tests don't need a fully seeded
StrategicAllocation + universe + NAV stack. This keeps the E2E focus
on the Phase 3 enrichment layer (the thing this phase introduces).

Also includes:
- Route smoke tests for the new Phase 3 endpoints (401/404/200 shape)
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from unittest.mock import patch

import asyncpg
import pytest
from httpx import AsyncClient

from app.core.config import settings

ORG_ID = "00000000-0000-0000-0000-000000000001"

_CANONICAL_BLOCKS = (
    "na_equity_large", "na_equity_growth", "na_equity_value", "na_equity_small",
    "dm_europe_equity", "dm_asia_equity", "em_equity",
    "fi_us_aggregate", "fi_us_treasury", "fi_us_short_term",
    "fi_us_high_yield", "fi_us_tips", "fi_ig_corporate", "fi_em_debt",
    "alt_real_estate", "alt_gold", "alt_commodities", "cash",
)

DEV_ACTOR_HEADER = {
    "X-DEV-ACTOR": json.dumps(
        {
            "actor_id": "test-user",
            "roles": ["ADMIN", "INVESTMENT_TEAM"],
            "fund_ids": [],
            "org_id": ORG_ID,
        },
    ),
}


def _asyncpg_dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


# ── Mock optimizer output ─────────────────────────────────────────


_HAPPY_OPTIMIZER_OUTPUT = {
    "profile": "moderate",
    "total_weight": 1.0,
    "funds": [
        {
            "instrument_id": "11111111-1111-1111-1111-111111111111",
            "fund_name": "Mock Large Cap",
            "block_id": "na_equity_large",
            "weight": 0.20,
            "score": 80,
        },
        {
            "instrument_id": "22222222-2222-2222-2222-222222222222",
            "fund_name": "Mock Small Cap",
            "block_id": "na_equity_small",
            "weight": 0.15,
            "score": 75,
        },
        {
            "instrument_id": "33333333-3333-3333-3333-333333333333",
            "fund_name": "Mock Treasury",
            "block_id": "fi_treasury",
            "weight": 0.30,
            "score": 85,
        },
        {
            "instrument_id": "44444444-4444-4444-4444-444444444444",
            "fund_name": "Mock IG Credit",
            "block_id": "fi_credit_ig",
            "weight": 0.20,
            "score": 78,
        },
        {
            "instrument_id": "55555555-5555-5555-5555-555555555555",
            "fund_name": "Mock Intl Equity",
            "block_id": "intl_equity_dm",
            "weight": 0.15,
            "score": 70,
        },
    ],
    "optimization": {
        "expected_return": 0.08,
        "portfolio_volatility": 0.12,
        "sharpe_ratio": 0.67,
        "solver": "CLARABEL",
        "status": "optimal",
        "cvar_95": -0.04,
        "cvar_limit": -0.05,
        "cvar_within_limit": True,
        "factor_exposures": {"average_r_squared": 0.62},
    },
}


_CONCENTRATED_OPTIMIZER_OUTPUT = {
    "profile": "moderate",
    "total_weight": 1.0,
    "funds": [
        {
            "instrument_id": "11111111-1111-1111-1111-111111111111",
            "fund_name": "Mock Single Holding",
            "block_id": "na_equity_large",
            "weight": 1.0,
            "score": 80,
        },
    ],
    "optimization": {
        "expected_return": 0.08,
        "portfolio_volatility": 0.12,
        "sharpe_ratio": 0.67,
        "solver": "CLARABEL",
        "status": "optimal",
        "cvar_95": -0.04,
        "cvar_limit": -0.05,
        "cvar_within_limit": True,
        "factor_exposures": {},
    },
}


# ── Fixtures: seed a portfolio row ────────────────────────────────


@pytest.fixture
async def seeded_portfolio():
    """Insert a ``model_portfolios`` row + 18 strategic_allocation rows
    (one per canonical block, NULL weights) for the test org.

    PR-A25's template-completeness gate (migration 0153) requires
    strategic_allocation rows for every (org, profile, canonical_block)
    tuple — without them the construction executor short-circuits to
    'failed' with reason 'template_incomplete' before the optimizer runs.

    Cleans up the portfolio + strategic_allocation + construction runs
    at teardown.
    """
    portfolio_id = uuid.uuid4()
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await conn.execute(
            """
            INSERT INTO model_portfolios (
                id, organization_id, profile, display_name,
                inception_nav, status, state, state_metadata, state_changed_at
            ) VALUES ($1, $2::uuid, 'moderate', 'E2E Test Portfolio',
                      1000, 'draft', 'draft', '{}'::jsonb, now())
            """,
            portfolio_id, ORG_ID,
        )

        # Clean up any stale strategic_allocation rows for this org+profile
        # (e.g. from a prior interrupted test run).
        await conn.execute(
            "DELETE FROM strategic_allocation "
            "WHERE organization_id = $1::uuid AND profile = 'moderate'",
            ORG_ID,
        )

        # Insert ONE strategic_allocation row. The AFTER INSERT trigger
        # (trg_enforce_allocation_template_sa) auto-creates the remaining
        # 17 canonical blocks. Then UPDATE all 18 to set approved_at
        # (PR-A26.2 realize-mode gate requires it).
        await conn.execute(
            """
            INSERT INTO strategic_allocation (
                allocation_id, organization_id, profile, block_id,
                target_weight, effective_from,
                excluded_from_portfolio, actor_source, created_at
            ) VALUES (
                gen_random_uuid(), $1::uuid, 'moderate', $2,
                NULL, CURRENT_DATE,
                false, 'test_fixture_seed', now()
            )
            """,
            ORG_ID, _CANONICAL_BLOCKS[0],
        )
        await conn.execute(
            "UPDATE strategic_allocation SET approved_at = now() "
            "WHERE organization_id = $1::uuid AND profile = 'moderate'",
            ORG_ID,
        )

        yield portfolio_id
    finally:
        try:
            await conn.execute(
                "DELETE FROM portfolio_construction_runs WHERE portfolio_id = $1",
                portfolio_id,
            )
            await conn.execute(
                "DELETE FROM portfolio_calibration WHERE portfolio_id = $1",
                portfolio_id,
            )
            await conn.execute(
                "DELETE FROM model_portfolios WHERE id = $1",
                portfolio_id,
            )
            # Clean up ALL strategic_allocation rows (ours + trigger-created)
            await conn.execute(
                "DELETE FROM strategic_allocation "
                "WHERE organization_id = $1::uuid AND profile = 'moderate'",
                ORG_ID,
            )
        finally:
            await conn.close()


async def _insert_calibration(
    portfolio_id: uuid.UUID,
    *,
    advisor_enabled: bool = True,
    max_single_fund_weight: float = 0.25,
    cvar_limit: float = 0.05,
) -> None:
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        await conn.execute(
            """
            INSERT INTO portfolio_calibration (
                organization_id, portfolio_id, mandate,
                cvar_limit, max_single_fund_weight, turnover_cap,
                stress_scenarios_active,
                bl_enabled, bl_view_confidence_default,
                garch_enabled, stress_severity_multiplier,
                advisor_enabled, cvar_level,
                expert_overrides
            ) VALUES (
                $1::uuid, $2, 'balanced',
                $3, $4, 0.30,
                ARRAY['gfc_2008','covid_2020','taper_2013','rate_shock_200bps']::text[],
                true, 1.0,
                true, 1.0,
                $5, 0.95,
                '{}'::jsonb
            )
            """,
            ORG_ID, portfolio_id,
            cvar_limit, max_single_fund_weight, advisor_enabled,
        )
    finally:
        await conn.close()


# ── Helper: run the executor with a mocked optimizer ─────────────


async def _run_executor_with_mock(
    portfolio_id: uuid.UUID,
    mock_output: dict,
) -> dict:
    """Call ``execute_construction_run`` with a patched ``_run_construction_async``.

    Returns the run row dict as persisted to the DB (read back via
    asyncpg — bypassing RLS so the test fixture can verify).
    """
    from app.core.db.engine import async_session_factory
    from app.domains.wealth.workers.construction_run_executor import (
        execute_construction_run,
    )

    async def _mocked(*_args, **_kwargs):
        return mock_output

    # The executor imports _run_construction_async lazily from the
    # routes module; patch at that exact reference.
    with patch(
        "app.domains.wealth.routes.model_portfolios._run_construction_async",
        side_effect=_mocked,
    ):
        async with async_session_factory() as session:
            # Set RLS context for the executor's writes.
            # Use set_config() instead of `SET LOCAL` because the latter
            # does not accept bind parameters in PostgreSQL — same
            # pattern used by the backtest job at model_portfolios.py:307.
            from sqlalchemy import text as _text
            await session.execute(
                _text("SELECT set_config('app.current_organization_id', :oid, true)"),
                {"oid": ORG_ID},
            )

            run = await execute_construction_run(
                db=session,
                portfolio_id=portfolio_id,
                organization_id=ORG_ID,
                requested_by="test-user",
                job_id=None,  # don't publish SSE events in tests
                as_of_date=date(2026, 4, 8),
            )
            run_id = run.id
            status = run.status
            await session.commit()

    # Read back via asyncpg, bypassing RLS
    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        row = await conn.fetchrow(
            "SELECT * FROM portfolio_construction_runs WHERE id = $1",
            run_id,
        )
    finally:
        await conn.close()
    assert row is not None, f"construction run {run_id} not persisted"
    result = dict(row)
    result["_returned_status"] = status
    return result


# ── Path 1: Happy path ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_construct_e2e_happy_path(seeded_portfolio):
    """Optimizer returns well-formed output → run succeeds with all
    enrichment columns populated."""
    await _insert_calibration(
        seeded_portfolio, advisor_enabled=True, max_single_fund_weight=0.25,
    )
    row = await _run_executor_with_mock(
        seeded_portfolio, _HAPPY_OPTIMIZER_OUTPUT,
    )

    assert row["status"] == "succeeded"
    assert row["failure_reason"] is None
    assert row["wall_clock_ms"] is not None
    assert row["wall_clock_ms"] > 0
    assert row["completed_at"] is not None

    # Enrichment columns
    optimizer_trace = json.loads(row["optimizer_trace"])
    assert optimizer_trace["solver"] == "CLARABEL"
    assert optimizer_trace["status"] == "optimal"

    ex_ante = json.loads(row["ex_ante_metrics"])
    assert ex_ante["expected_return"] == 0.08
    assert ex_ante["cvar_95"] == -0.04

    weights = json.loads(row["weights_proposed"])
    assert len(weights) == 5
    assert abs(sum(weights.values()) - 1.0) < 1e-6

    # Narrative section — both technical + client_safe present
    narrative = json.loads(row["narrative"])
    assert "technical" in narrative
    assert "client_safe" in narrative
    assert narrative["schema_version"] == 2
    assert len(narrative["technical"]["headline"]) > 0

    # Validation section — aggregate + list of 16 checks
    validation = json.loads(row["validation"])
    assert "passed" in validation
    assert "checks" in validation
    assert validation["summary"]["total"] == 16

    # Stress results — 4 preset scenarios were run
    stress_results = json.loads(row["stress_results"])
    assert len(stress_results) == 4
    scenarios = {s["scenario"] for s in stress_results}
    assert scenarios == {
        "gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps",
    }

    # Factor exposure passed through
    factor = json.loads(row["factor_exposure"])
    assert factor == {"average_r_squared": 0.62}


@pytest.mark.asyncio
async def test_construct_e2e_happy_path_persists_stress_rows(seeded_portfolio):
    """Each preset stress scenario must land as its own
    ``portfolio_stress_results`` row under the construction run."""
    await _insert_calibration(seeded_portfolio, advisor_enabled=True)
    row = await _run_executor_with_mock(
        seeded_portfolio, _HAPPY_OPTIMIZER_OUTPUT,
    )
    run_id = row["id"]

    conn = await asyncpg.connect(_asyncpg_dsn())
    try:
        stress_rows = await conn.fetch(
            "SELECT scenario, scenario_kind, nav_impact_pct "
            "FROM portfolio_stress_results "
            "WHERE construction_run_id = $1 "
            "ORDER BY scenario",
            run_id,
        )
    finally:
        await conn.close()

    assert len(stress_rows) == 4
    scenarios = {r["scenario"] for r in stress_rows}
    assert scenarios == {
        "gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps",
    }
    for r in stress_rows:
        assert r["scenario_kind"] == "preset"
        assert r["nav_impact_pct"] is not None


# ── Path 2: Validation block path ────────────────────────────────


@pytest.mark.asyncio
async def test_construct_e2e_validation_block_path(seeded_portfolio):
    """Concentrated (1 holding) + over-cap weight → multiple block
    failures in the 15-check gate. The run still persists; the gate
    output records the failure so the UI can render it."""
    await _insert_calibration(
        seeded_portfolio, advisor_enabled=True, max_single_fund_weight=0.25,
    )
    row = await _run_executor_with_mock(
        seeded_portfolio, _CONCENTRATED_OPTIMIZER_OUTPUT,
    )

    # Run itself "succeeded" (optimizer + stress + validation all ran) —
    # the block-severity failures are RECORDED in validation JSONB,
    # not raised as exceptions. This is the soft-block contract (OD-5).
    assert row["status"] == "succeeded"

    validation = json.loads(row["validation"])
    assert validation["passed"] is False, (
        "concentrated 1-fund portfolio should not pass min_diversification_count"
    )
    failed_ids = [c["id"] for c in validation["checks"] if not c["passed"]]
    assert "min_diversification_count" in failed_ids
    assert "max_single_fund_weight" in failed_ids

    # Both failures are block-severity
    check_by_id = {c["id"]: c for c in validation["checks"]}
    assert check_by_id["min_diversification_count"]["severity"] == "block"
    assert check_by_id["max_single_fund_weight"]["severity"] == "block"
    assert validation["summary"]["blocks_failed"] >= 2


# ── Path 3: Advisor disabled path ────────────────────────────────


@pytest.mark.asyncio
async def test_construct_e2e_advisor_disabled(seeded_portfolio):
    """With ``advisor_enabled=False`` the run completes but
    ``advisor`` is NULL in the persisted row."""
    await _insert_calibration(
        seeded_portfolio, advisor_enabled=False,
    )
    row = await _run_executor_with_mock(
        seeded_portfolio, _HAPPY_OPTIMIZER_OUTPUT,
    )
    assert row["status"] == "succeeded"
    assert row["advisor"] is None, (
        "advisor must be NULL when calibration.advisor_enabled=False"
    )


@pytest.mark.asyncio
async def test_construct_e2e_advisor_enabled(seeded_portfolio):
    """With ``advisor_enabled=True`` the run populates the advisor column."""
    await _insert_calibration(
        seeded_portfolio, advisor_enabled=True,
    )
    row = await _run_executor_with_mock(
        seeded_portfolio, _HAPPY_OPTIMIZER_OUTPUT,
    )
    assert row["status"] == "succeeded"
    assert row["advisor"] is not None
    advisor = json.loads(row["advisor"])
    assert "cvar_gap" in advisor
    assert "block_weights" in advisor
    assert advisor["profile"] == "moderate"


# ── Calibration snapshot is persisted ─────────────────────────────


@pytest.mark.asyncio
async def test_construct_e2e_persists_calibration_snapshot(seeded_portfolio):
    """The run must carry an immutable snapshot of the calibration
    that was active at run time (DL4 — historical replayability)."""
    await _insert_calibration(
        seeded_portfolio,
        advisor_enabled=True,
        cvar_limit=0.07,
    )
    row = await _run_executor_with_mock(
        seeded_portfolio, _HAPPY_OPTIMIZER_OUTPUT,
    )
    snapshot = json.loads(row["calibration_snapshot"])
    assert snapshot["mandate"] == "balanced"
    assert snapshot["advisor_enabled"] is True
    assert snapshot["cvar_limit"] == 0.07


# ── Route smoke tests (new Phase 3 endpoints) ────────────────────


BASE = "/api/v1/model-portfolios"
META_BASE = "/api/v1/portfolio"


@pytest.mark.asyncio
async def test_stress_test_scenarios_catalog_requires_auth(client: AsyncClient):
    resp = await client.get(f"{META_BASE}/stress-test/scenarios")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stress_test_scenarios_catalog_route_exists(client: AsyncClient):
    resp = await client.get(f"{META_BASE}/stress-test/scenarios")
    assert resp.status_code != 404


@pytest.mark.asyncio
async def test_stress_test_scenarios_catalog_shape(client: AsyncClient):
    """With dev actor header, the catalog returns the 4 canonical scenarios."""
    resp = await client.get(
        f"{META_BASE}/stress-test/scenarios",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "scenarios" in payload
    assert "as_of" in payload
    ids = {s["scenario_id"] for s in payload["scenarios"]}
    assert ids == {
        "gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps",
    }
    # Every entry has display_name + description + shock_components + kind
    for entry in payload["scenarios"]:
        assert entry["kind"] == "preset"
        assert len(entry["display_name"]) > 0
        assert len(entry["description"]) > 0
        assert isinstance(entry["shock_components"], dict)
        assert len(entry["shock_components"]) > 0


@pytest.mark.asyncio
async def test_regime_current_requires_auth(client: AsyncClient):
    resp = await client.get(f"{META_BASE}/regime/current")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_regime_current_route_exists(client: AsyncClient):
    resp = await client.get(f"{META_BASE}/regime/current")
    assert resp.status_code != 404


@pytest.mark.asyncio
async def test_regime_current_returns_client_safe_label(client: AsyncClient):
    """OD-22: ``client_safe_label`` must be present and translated."""
    resp = await client.get(
        f"{META_BASE}/regime/current",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "regime" in payload
    assert "client_safe_label" in payload
    # Whatever the raw regime, the label must be one of the 5 locked mappings
    assert payload["client_safe_label"] in {
        "Balanced", "Expansion", "Defensive", "Stress", "Inflation",
    }


@pytest.mark.asyncio
async def test_construct_route_requires_auth(client: AsyncClient):
    fake_id = "00000000-0000-0000-0000-0000000000aa"
    resp = await client.post(f"{BASE}/{fake_id}/construct")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_construct_route_exists(client: AsyncClient):
    fake_id = "00000000-0000-0000-0000-0000000000aa"
    resp = await client.post(f"{BASE}/{fake_id}/construct")
    assert resp.status_code != 404


@pytest.mark.asyncio
async def test_get_run_route_exists(client: AsyncClient):
    fake_portfolio = "00000000-0000-0000-0000-0000000000aa"
    fake_run = "00000000-0000-0000-0000-0000000000bb"
    resp = await client.get(f"{BASE}/{fake_portfolio}/runs/{fake_run}")
    assert resp.status_code != 404

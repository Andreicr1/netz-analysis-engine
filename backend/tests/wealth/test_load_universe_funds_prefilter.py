"""Tests for ``_load_universe_funds`` pre-filter cascade (PR-A7).

Covers the two-layer deterministic reduction from the full
``instruments_org`` set (~3,184 post auto-import) down to the
~350-fund tractable band that CLARABEL can actually solve:

* **Layer 0** — JOIN on ``strategic_allocation`` so only blocks in the
  caller's profile allocation survive.
* **Layer 2** — ``ROW_NUMBER() OVER (PARTITION BY block_id ORDER BY
  manager_score DESC, instrument_id ASC)`` caps each block at
  ``LAYER_2_TOP_N_PER_BLOCK`` rows.

Also covers the ``succeeded → degraded`` status gate introduced in §B:
when the optimizer result exits the CLARABEL cascade via
``heuristic_fallback``, the run is persisted as ``degraded`` rather
than ``succeeded``.

Every seeded test runs inside a single transaction that is **always
rolled back** at teardown — no commits, no leftover rows, no cross-test
contamination. Each test uses a unique ``profile`` string (``test_p_<hex>``)
so the SQL JOIN to ``strategic_allocation`` cannot match pre-existing
seed rows from other profiles. This is important because the test DB
connects as a superuser, which bypasses RLS — the profile namespace is
the deterministic isolation mechanism. The first test hits the real
local-dev ``403d8392`` org read-only and is marked ``integration`` so
CI can skip it when the live DB is not reachable.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.db.engine import async_session_factory
from app.domains.wealth.routes.model_portfolios import (
    LAYER_2_TOP_N_PER_BLOCK,
    _load_universe_funds,
)

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────


async def _set_rls(db: Any, org_id: str) -> None:
    """Apply transaction-scoped RLS context so instruments_org /
    strategic_allocation policies see the test org.
    """
    await db.execute(
        text("SELECT set_config('app.current_organization_id', :oid, true)"),
        {"oid": org_id},
    )


async def _seed_allocation_block(db: Any, block_id: str) -> None:
    """Ensure the allocation_blocks row exists (no-op if already present).

    ``allocation_blocks`` is global (no RLS) — a test block may outlive
    the test's transactional rollback. Using ``ON CONFLICT DO NOTHING``
    keeps re-runs safe, and the unique block_id namespace (``test_*``)
    prevents collision with real seed data.
    """
    await db.execute(
        text(
            """
            INSERT INTO allocation_blocks (
                block_id, geography, asset_class, display_name, is_active
            )
            VALUES (:block_id, 'US', 'equity', :block_id, true)
            ON CONFLICT (block_id) DO NOTHING
            """,
        ),
        {"block_id": block_id},
    )


async def _seed_strategic_allocation(
    db: Any,
    *,
    org_id: str,
    profile: str,
    block_id: str,
) -> None:
    """Insert a strategic_allocation row mapping (profile, block) for
    the given org, with an ``effective_from`` of yesterday.
    """
    await db.execute(
        text(
            """
            INSERT INTO strategic_allocation (
                allocation_id, organization_id, profile, block_id,
                target_weight, drift_min, drift_max, effective_from
            )
            VALUES (
                :allocation_id, :org_id, :profile, :block_id,
                0.1000, 0.0000, 0.2500, :effective_from
            )
            """,
        ),
        {
            "allocation_id": uuid.uuid4(),
            "org_id": org_id,
            "profile": profile,
            "block_id": block_id,
            "effective_from": date.today() - timedelta(days=1),
        },
    )


async def _seed_instrument(db: Any, name: str) -> uuid.UUID:
    """Insert a minimal instruments_universe row. Returns instrument_id.

    ``is_institutional`` is a GENERATED column (migration 0134 — reads
    ``attributes->>'is_institutional'``), so we drive it via ``attributes``.
    The ``chk_fund_attrs`` CHECK constraint requires every fund to carry
    ``aum_usd``, ``manager_name``, and ``inception_date`` in attributes.
    """
    instrument_id = uuid.uuid4()
    attributes = (
        '{"is_institutional": true, "aum_usd": 1000000000, '
        '"manager_name": "Test Manager", "inception_date": "2020-01-01"}'
    )
    await db.execute(
        text(
            """
            INSERT INTO instruments_universe (
                instrument_id, instrument_type, name, asset_class,
                geography, currency, is_active,
                attributes, created_at, updated_at
            )
            VALUES (
                :instrument_id, 'fund', :name, 'equity',
                'US', 'USD', true,
                CAST(:attributes AS jsonb), now(), now()
            )
            """,
        ),
        {
            "instrument_id": instrument_id,
            "name": name,
            "attributes": attributes,
        },
    )
    return instrument_id


async def _seed_instrument_org(
    db: Any,
    *,
    org_id: str,
    instrument_id: uuid.UUID,
    block_id: str,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO instruments_org (
                id, organization_id, instrument_id, block_id,
                approval_status, source
            )
            VALUES (
                gen_random_uuid(), :org_id, :instrument_id, :block_id,
                'approved', 'test'
            )
            """,
        ),
        {
            "org_id": org_id,
            "instrument_id": instrument_id,
            "block_id": block_id,
        },
    )


async def _seed_risk_metric(
    db: Any,
    *,
    instrument_id: uuid.UUID,
    manager_score: float | None,
    calc_date: date | None = None,
) -> None:
    """Insert a global (``organization_id IS NULL``) fund_risk_metrics row.

    This is the row the CTE's ``latest_risk`` subquery JOINs against.
    """
    await db.execute(
        text(
            """
            INSERT INTO fund_risk_metrics (
                instrument_id, calc_date, organization_id, manager_score
            )
            VALUES (
                :instrument_id, :calc_date, NULL, :manager_score
            )
            ON CONFLICT DO NOTHING
            """,
        ),
        {
            "instrument_id": instrument_id,
            "calc_date": calc_date or date.today(),
            "manager_score": manager_score,
        },
    )


# ── C.1 — Integration test against live org ──────────────────────────


@pytest.mark.integration
async def test_prefilter_reduces_to_target_cardinality() -> None:
    """Pre-filter cascade reduces 3,184 → ~300-400 for conservative profile.

    Layer 2 caps 50 per block × 7 populated blocks ≈ 350. Some blocks
    have <50 funds (cash 44, alt_gold 26) so the actual lands below
    7×50. The 200-400 band guards against both a runaway (>400 means
    the cap didn't apply) and a collapse (<200 means Layer 0 dropped
    too much).
    """
    org_id = "403d8392-ebfa-5890-b740-45da49c556eb"
    async with async_session_factory() as db:
        await _set_rls(db, org_id)

        # Runtime self-gate — the expected 200-400 band only holds when the
        # org has its full production-cloned catalog (≥1000 instruments).
        # On fresh CI / clean docker compose this is 0; skip rather than fail.
        # Seed via scripts/dev_seed_local.py to enable.
        inst_count = await db.scalar(
            text("SELECT COUNT(*) FROM instruments_org WHERE organization_id = :o"),
            {"o": org_id},
        )
        if inst_count < 1000:
            pytest.skip(
                f"requires dev-seeded DB (have {inst_count} instruments, "
                f"need ≥1000). Run scripts/dev_seed_local.py to enable."
            )

        funds = await _load_universe_funds(
            db, org_id, profile="conservative",
        )
    assert 200 <= len(funds) <= 400, (
        f"Got {len(funds)} funds for conservative profile — "
        f"expected 200-400 after Layer 0 + Layer 2 pre-filter"
    )
    # Every row must have block_id populated — Layer 0 requires the JOIN
    assert all(f["block_id"] for f in funds), "Some fund returned with null block"
    # No block should exceed the Layer 2 cap
    per_block: dict[str, int] = {}
    for f in funds:
        per_block[f["block_id"]] = per_block.get(f["block_id"], 0) + 1
    for block, n in per_block.items():
        assert n <= LAYER_2_TOP_N_PER_BLOCK, (
            f"Block {block} has {n} funds, exceeds cap {LAYER_2_TOP_N_PER_BLOCK}"
        )


# ── C.2 — Layer 0 profile filtering ──────────────────────────────────


@pytest.mark.integration
async def test_layer0_filters_blocks_outside_profile() -> None:
    """Funds in a block NOT present in the profile's strategic allocation
    must be excluded at SQL time.

    Seeds two ``instruments_org`` rows for a fresh org: one sitting in
    a block allocated to ``conservative`` and one sitting in a block
    that is NOT. Layer 0 must keep only the first.
    """
    org_id = str(uuid.uuid4())
    profile = f"test_p_{uuid.uuid4().hex[:10]}"
    in_profile_block = f"test_l0_in_{uuid.uuid4().hex[:8]}"
    out_profile_block = f"test_l0_out_{uuid.uuid4().hex[:8]}"

    async with async_session_factory() as db:
        try:
            await _set_rls(db, org_id)
            await _seed_allocation_block(db, in_profile_block)
            await _seed_allocation_block(db, out_profile_block)
            # Only the in-profile block gets a strategic_allocation row
            await _seed_strategic_allocation(
                db, org_id=org_id, profile=profile,
                block_id=in_profile_block,
            )

            in_iid = await _seed_instrument(db, "In-Profile Fund")
            out_iid = await _seed_instrument(db, "Out-Profile Fund")

            await _seed_instrument_org(
                db, org_id=org_id, instrument_id=in_iid,
                block_id=in_profile_block,
            )
            await _seed_instrument_org(
                db, org_id=org_id, instrument_id=out_iid,
                block_id=out_profile_block,
            )

            await _seed_risk_metric(db, instrument_id=in_iid, manager_score=0.75)
            await _seed_risk_metric(db, instrument_id=out_iid, manager_score=0.90)
            await db.flush()

            funds = await _load_universe_funds(
                db, org_id, profile=profile,
            )

            instrument_ids = {f["instrument_id"] for f in funds}
            assert str(in_iid) in instrument_ids, (
                "In-profile fund missing from pre-filter output"
            )
            assert str(out_iid) not in instrument_ids, (
                "Out-of-profile fund leaked through Layer 0"
            )
        finally:
            # Roll back the whole test transaction — no committed state
            # leaks between tests or into the real DB.
            await db.rollback()


# ── C.3 — Layer 2 top-N cap ──────────────────────────────────────────


@pytest.mark.integration
async def test_layer2_caps_top_n_per_block_by_manager_score() -> None:
    """Seeds 60 funds in a single block with manager_score 0.01…0.60 and
    asserts exactly ``LAYER_2_TOP_N_PER_BLOCK=50`` rows are returned,
    all with the 50 HIGHEST scores, ordered DESC.
    """
    org_id = str(uuid.uuid4())
    profile = f"test_p_{uuid.uuid4().hex[:10]}"
    block_id = f"test_l2_cap_{uuid.uuid4().hex[:8]}"
    n_seeded = 60

    async with async_session_factory() as db:
        try:
            await _set_rls(db, org_id)
            await _seed_allocation_block(db, block_id)
            await _seed_strategic_allocation(
                db, org_id=org_id, profile=profile, block_id=block_id,
            )
            # Seed 60 funds with monotonically increasing manager_score
            # so the cut is easy to validate: top 50 must be score >= 0.11.
            for i in range(n_seeded):
                iid = await _seed_instrument(db, f"Cap Test {i:02d}")
                await _seed_instrument_org(
                    db, org_id=org_id, instrument_id=iid, block_id=block_id,
                )
                # Score in [0.01, 0.60]
                await _seed_risk_metric(
                    db, instrument_id=iid,
                    manager_score=round((i + 1) / 100.0, 2),
                )
            await db.flush()

            funds = await _load_universe_funds(
                db, org_id, profile=profile,
            )

            assert len(funds) == LAYER_2_TOP_N_PER_BLOCK, (
                f"Expected exactly {LAYER_2_TOP_N_PER_BLOCK} rows, got {len(funds)}"
            )
            scores = [f["manager_score"] for f in funds]
            # DESC order — first element is the highest score, last is the
            # lowest kept
            assert scores == sorted(scores, reverse=True), (
                f"manager_score must be DESC, got {scores}"
            )
            # Lowest kept score must be 0.11 — the 10 lowest (0.01-0.10)
            # should have been dropped by the Top-N cap.
            min_kept = min(s for s in scores if s is not None)
            assert min_kept >= 0.11 - 1e-9, (
                f"Lowest kept score {min_kept}, expected >= 0.11 "
                f"(scores 0.01-0.10 should have been cut)"
            )
        finally:
            await db.rollback()


# ── C.4 — Deterministic ordering ─────────────────────────────────────


@pytest.mark.integration
async def test_prefilter_ordering_is_deterministic_across_runs() -> None:
    """Tie-break by instrument_id ASC must survive query planner churn.

    Seeds 10 funds in a block, all with the same manager_score, and
    runs the pre-filter twice back-to-back. The returned instrument_id
    sequences must match byte-for-byte.
    """
    org_id = str(uuid.uuid4())
    profile = f"test_p_{uuid.uuid4().hex[:10]}"
    block_id = f"test_det_{uuid.uuid4().hex[:8]}"

    async with async_session_factory() as db:
        try:
            await _set_rls(db, org_id)
            await _seed_allocation_block(db, block_id)
            await _seed_strategic_allocation(
                db, org_id=org_id, profile=profile, block_id=block_id,
            )
            for i in range(10):
                iid = await _seed_instrument(db, f"Determinism {i}")
                await _seed_instrument_org(
                    db, org_id=org_id, instrument_id=iid, block_id=block_id,
                )
                # Identical score so the instrument_id ASC tie-break is
                # the only thing making the ordering deterministic.
                await _seed_risk_metric(db, instrument_id=iid, manager_score=0.5)
            await db.flush()

            first = await _load_universe_funds(db, org_id, profile=profile)
            second = await _load_universe_funds(db, org_id, profile=profile)

            first_ids = [f["instrument_id"] for f in first]
            second_ids = [f["instrument_id"] for f in second]
            assert first_ids == second_ids, (
                f"Ordering drifted between runs: "
                f"first={first_ids} second={second_ids}"
            )
            # With the ASC tie-break the ids must be sorted lexicographically
            assert first_ids == sorted(first_ids), (
                f"Tie-broken ordering must be instrument_id ASC, got {first_ids}"
            )
        finally:
            await db.rollback()


# ── C.5 — succeeded → degraded status gate ───────────────────────────


@pytest.mark.integration
async def test_executor_marks_heuristic_fallback_runs_as_degraded() -> None:
    """When the optimizer result's ``solver`` is ``heuristic_fallback``
    the run terminates with ``status='degraded'``, not ``'succeeded'``.

    Patches ``_run_construction_async`` (imported lazily inside
    ``_execute_inner``) to return a fixed output with ``solver =
    heuristic_fallback`` and all 4 CLARABEL phases failed/skipped, then
    calls ``execute_construction_run`` against the real DB and asserts
    the persisted ``run.status``. Validates both the new CHECK
    constraint (migration 0141) and the status gate.
    """
    from unittest.mock import patch as mock_patch

    from app.domains.wealth.models.model_portfolio import ModelPortfolio
    from app.domains.wealth.workers.construction_run_executor import (
        execute_construction_run,
    )

    org_id = str(uuid.uuid4())
    portfolio_id = uuid.uuid4()

    fake_base_result: dict[str, Any] = {
        "funds": [
            {
                "instrument_id": str(uuid.uuid4()),
                "fund_name": "Heuristic Pick",
                "block_id": "test_deg_block",
                "weight": 1.0,
            },
        ],
        "profile": "moderate",
        "optimization": {
            "solver": "heuristic_fallback",
            "status": "fallback:insufficient_fund_data",
            "expected_return": None,
            "portfolio_volatility": None,
            "sharpe_ratio": None,
            "cvar_95": None,
            "cvar_limit": -0.08,
        },
        "taa": None,
    }

    async def _fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return fake_base_result

    async with async_session_factory() as db:
        try:
            await _set_rls(db, org_id)
            db.add(
                ModelPortfolio(
                    id=portfolio_id,
                    organization_id=uuid.UUID(org_id),
                    display_name="Degraded Path Test",
                    profile="moderate",
                    state="draft",
                    state_changed_by="test",
                    created_by="test",
                ),
            )
            await db.flush()

            with mock_patch(
                "app.domains.wealth.routes.model_portfolios._run_construction_async",
                new=_fake,
            ):
                run = await execute_construction_run(
                    db,
                    portfolio_id=portfolio_id,
                    organization_id=org_id,
                    requested_by="test-actor",
                    job_id=None,
                    as_of_date=date.today(),
                )

            assert run.status == "degraded", (
                f"Expected status='degraded' on heuristic_fallback, "
                f"got {run.status!r}. optimizer_trace={run.optimizer_trace!r}"
            )
            assert (run.optimizer_trace or {}).get("solver") == "heuristic_fallback"
        finally:
            await db.rollback()


# ── C.5b — Positive control: real solver result still yields succeeded ─


@pytest.mark.integration
async def test_executor_marks_real_solver_runs_as_succeeded() -> None:
    """Symmetry check — when the optimizer reports a real solver
    (CLARABEL / SCS), the run must still terminate ``succeeded``.

    Guards against over-matching: a naive implementation might set
    ``degraded`` any time ``solver is not None`` or any time the
    trace is non-empty.
    """
    from unittest.mock import patch as mock_patch

    from app.domains.wealth.models.model_portfolio import ModelPortfolio
    from app.domains.wealth.workers.construction_run_executor import (
        execute_construction_run,
    )

    org_id = str(uuid.uuid4())
    portfolio_id = uuid.uuid4()

    fake_base_result: dict[str, Any] = {
        "funds": [
            {
                "instrument_id": str(uuid.uuid4()),
                "fund_name": "CLARABEL Pick",
                "block_id": "test_ok_block",
                "weight": 1.0,
            },
        ],
        "profile": "moderate",
        "optimization": {
            "solver": "CLARABEL",
            "status": "optimal",
            "expected_return": 0.08,
            "portfolio_volatility": 0.12,
            "sharpe_ratio": 0.5,
            "cvar_95": -0.05,
            "cvar_limit": -0.08,
        },
        "taa": None,
    }

    async def _fake(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return fake_base_result

    async with async_session_factory() as db:
        try:
            await _set_rls(db, org_id)
            db.add(
                ModelPortfolio(
                    id=portfolio_id,
                    organization_id=uuid.UUID(org_id),
                    display_name="Success Control",
                    profile="moderate",
                    state="draft",
                    state_changed_by="test",
                    created_by="test",
                ),
            )
            await db.flush()

            with mock_patch(
                "app.domains.wealth.routes.model_portfolios._run_construction_async",
                new=_fake,
            ):
                run = await execute_construction_run(
                    db,
                    portfolio_id=portfolio_id,
                    organization_id=org_id,
                    requested_by="test-actor",
                    job_id=None,
                    as_of_date=date.today(),
                )
            assert run.status == "succeeded", (
                f"Real solver result must stay 'succeeded', got {run.status!r}"
            )
        finally:
            await db.rollback()

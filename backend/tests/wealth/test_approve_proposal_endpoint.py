"""PR-A26.2 Section C - approve-proposal endpoint unit coverage.

The handler talks to the DB directly via ``text()`` updates; we stub
``AsyncSession.execute``/``scalar`` in each test so the shape of the
SQL traffic is asserted without standing up Postgres. Live-DB smoke
coverage lives in ``backend/scripts/pr_a26_2_smoke.py``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.core.security.clerk_auth import Actor
from app.domains.wealth.models.model_portfolio import PortfolioConstructionRun
from app.domains.wealth.routes.model_portfolios import approve_proposal
from app.domains.wealth.schemas.model_portfolio import ApproveProposalRequest

_CANONICAL_BLOCKS: tuple[str, ...] = (
    "na_equity_large", "na_equity_growth", "na_equity_value", "na_equity_small",
    "dm_europe_equity", "dm_asia_equity", "em_equity",
    "fi_us_aggregate", "fi_us_treasury", "fi_us_short_term",
    "fi_us_high_yield", "fi_us_tips", "fi_ig_corporate", "fi_em_debt",
    "alt_real_estate", "alt_gold", "alt_commodities", "cash",
)


def _make_actor(role: str = "INVESTMENT_TEAM") -> Actor:
    from app.shared.enums import Role

    return Actor(
        actor_id="tester",
        name="Tester",
        email="tester@example.com",
        roles=[Role(role)],
        organization_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        fund_ids=[],
    )


def _make_user() -> Any:
    user = MagicMock()
    user.name = "tester"
    return user


def _make_run(
    *,
    winner_signal: str = "proposal_ready",
    cvar_feasible: bool = True,
    run_mode: str = "propose",
    n_bands: int = 18,
) -> PortfolioConstructionRun:
    bands = [
        {
            "block_id": _CANONICAL_BLOCKS[i],
            "target_weight": 1.0 / n_bands,
            "drift_min": 0.0,
            "drift_max": 1.0,
        }
        for i in range(min(n_bands, len(_CANONICAL_BLOCKS)))
    ]
    telemetry = {
        "winner_signal": winner_signal,
        "proposed_bands": bands,
        "proposal_metrics": {
            "target_cvar": 0.05,
            "expected_return": 0.08,
            "cvar_feasible": cvar_feasible,
        },
    }
    run = PortfolioConstructionRun(
        id=uuid.uuid4(),
        organization_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        portfolio_id=uuid.uuid4(),
        calibration_snapshot={},
        calibration_hash="x",
        universe_fingerprint="pending",
        status="succeeded",
        run_mode=run_mode,
        requested_by="tester",
    )
    run.cascade_telemetry = telemetry
    return run


def _make_db_for_approve(
    *,
    run: PortfolioConstructionRun | None,
) -> AsyncMock:
    """Stub AsyncSession that simulates the sequence the handler issues.

    Call pattern per handler:
      1. ``execute(run_stmt).scalar_one_or_none()`` → run or None
      2. ``scalar(text("SELECT now()"))`` → a timestamp
      3. 18 × ``execute(update sa).mappings().one_or_none()`` → band row
      4. ``execute(update approvals ...)`` (no return)
      5. ``execute(insert approvals ...)`` (no return)
      6. ``flush()``
    """
    db = AsyncMock()

    run_result = MagicMock()
    run_result.scalar_one_or_none.return_value = run

    now_ts = datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)
    db.scalar = AsyncMock(return_value=now_ts)

    # Each SA band update returns one row.
    def _make_sa_result(block_id: str) -> MagicMock:
        result = MagicMock()
        mappings = MagicMock()
        mappings.one_or_none.return_value = {
            "block_id": block_id,
            "target_weight": 0.05,
            "drift_min": 0.02,
            "drift_max": 0.08,
            "override_min": None,
            "override_max": None,
            "approved_at": now_ts,
            "approved_by": "tester",
            "excluded_from_portfolio": False,
        }
        result.mappings.return_value = mappings
        return result

    # Approvals supersede/insert — no RETURNING, so bare MagicMock ok.
    generic_result = MagicMock()

    execute_calls = {"i": 0}

    async def _execute(stmt, params: dict | None = None):
        execute_calls["i"] += 1
        # First call is the run lookup.
        if execute_calls["i"] == 1:
            return run_result
        # Next 18 are SA band updates.
        if 2 <= execute_calls["i"] <= 19 and params and "block_id" in params:
            return _make_sa_result(params["block_id"])
        return generic_result

    db.execute = AsyncMock(side_effect=_execute)
    return db


@pytest.mark.asyncio
async def test_approve_proposal_ready_happy_path() -> None:
    run = _make_run(winner_signal="proposal_ready", cvar_feasible=True)
    db = _make_db_for_approve(run=run)

    resp = await approve_proposal(
        profile="moderate",
        run_id=run.id,
        body=ApproveProposalRequest(),
        db=db,
        user=_make_user(),
        actor=_make_actor(),
        org_id="00000000-0000-0000-0000-000000000001",
    )

    assert resp.run_id == run.id
    assert resp.cvar_feasible_at_approval is True
    assert len(resp.strategic_snapshot) == 18


@pytest.mark.asyncio
async def test_approve_infeasible_without_confirm_409() -> None:
    run = _make_run(
        winner_signal="proposal_cvar_infeasible", cvar_feasible=False,
    )
    db = _make_db_for_approve(run=run)

    with pytest.raises(HTTPException) as excinfo:
        await approve_proposal(
            profile="moderate",
            run_id=run.id,
            body=ApproveProposalRequest(confirm_cvar_infeasible=False),
            db=db,
            user=_make_user(),
            actor=_make_actor(),
            org_id="00000000-0000-0000-0000-000000000001",
        )
    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_approve_infeasible_with_confirm_succeeds() -> None:
    run = _make_run(
        winner_signal="proposal_cvar_infeasible", cvar_feasible=False,
    )
    db = _make_db_for_approve(run=run)

    resp = await approve_proposal(
        profile="moderate",
        run_id=run.id,
        body=ApproveProposalRequest(
            confirm_cvar_infeasible=True,
            operator_message="accepting infeasible universe floor",
        ),
        db=db,
        user=_make_user(),
        actor=_make_actor(),
        org_id="00000000-0000-0000-0000-000000000001",
    )
    assert resp.cvar_feasible_at_approval is False


@pytest.mark.asyncio
async def test_approve_realize_run_404() -> None:
    run = _make_run(run_mode="realize")
    db = _make_db_for_approve(run=run)

    with pytest.raises(HTTPException) as excinfo:
        await approve_proposal(
            profile="moderate",
            run_id=run.id,
            body=ApproveProposalRequest(),
            db=db,
            user=_make_user(),
            actor=_make_actor(),
            org_id="00000000-0000-0000-0000-000000000001",
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_approve_missing_run_404() -> None:
    db = _make_db_for_approve(run=None)

    with pytest.raises(HTTPException) as excinfo:
        await approve_proposal(
            profile="moderate",
            run_id=uuid.uuid4(),
            body=ApproveProposalRequest(),
            db=db,
            user=_make_user(),
            actor=_make_actor(),
            org_id="00000000-0000-0000-0000-000000000001",
        )
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_approve_template_incomplete_500() -> None:
    """Propose run with fewer than 18 bands is a structural invariant bug."""
    run = _make_run(n_bands=17)
    db = _make_db_for_approve(run=run)

    with pytest.raises(HTTPException) as excinfo:
        await approve_proposal(
            profile="moderate",
            run_id=run.id,
            body=ApproveProposalRequest(),
            db=db,
            user=_make_user(),
            actor=_make_actor(),
            org_id="00000000-0000-0000-0000-000000000001",
        )
    assert excinfo.value.status_code == 500


@pytest.mark.asyncio
async def test_approve_rejects_unknown_profile() -> None:
    run = _make_run()
    db = _make_db_for_approve(run=run)

    with pytest.raises(HTTPException) as excinfo:
        await approve_proposal(
            profile="ultra",
            run_id=run.id,
            body=ApproveProposalRequest(),
            db=db,
            user=_make_user(),
            actor=_make_actor(),
            org_id="00000000-0000-0000-0000-000000000001",
        )
    assert excinfo.value.status_code == 400

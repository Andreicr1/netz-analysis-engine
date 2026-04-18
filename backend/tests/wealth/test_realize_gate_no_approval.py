"""PR-A26.2 Section E - realize-mode refuses to run without approvals.

Drives the pre-optimizer gate in ``_execute_inner`` with a stubbed
``_count_approved_blocks`` that reports ``approved < total`` and
asserts ``NoApprovedAllocationError`` bubbles out before the optimizer
is ever invoked. Propose mode bypasses the gate - it is the path that
SEEDS the approval.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.models.model_portfolio import PortfolioConstructionRun
from app.domains.wealth.workers import construction_run_executor as executor_mod
from app.domains.wealth.workers.construction_run_executor import (
    NoApprovedAllocationError,
    _execute_inner,
)
from quant_engine.allocation_template_service import TemplateReport
from quant_engine.block_coverage_service import CoverageReport


def _make_db_with_portfolio(profile: str, org_id: uuid.UUID) -> AsyncMock:
    portfolio_stub = MagicMock()
    portfolio_stub.profile = profile
    portfolio_stub.organization_id = org_id
    result = MagicMock()
    result.scalar_one_or_none.return_value = portfolio_stub
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _make_run(org_id: uuid.UUID, run_mode: str = "realize") -> PortfolioConstructionRun:
    return PortfolioConstructionRun(
        id=uuid.uuid4(),
        organization_id=org_id,
        portfolio_id=uuid.uuid4(),
        calibration_snapshot={},
        calibration_hash="x",
        universe_fingerprint="pending",
        status="running",
        run_mode=run_mode,
        requested_by="tester",
    )


def _template_complete(org_id: uuid.UUID, profile: str) -> TemplateReport:
    return TemplateReport(
        organization_id=org_id,
        profile=profile,
        is_complete=True,
        missing_canonical_blocks=[],
        extra_non_canonical_blocks=[],
    )


def _coverage_sufficient(org_id: uuid.UUID, profile: str) -> CoverageReport:
    return CoverageReport(
        organization_id=org_id,
        profile=profile,
        is_sufficient=True,
        gaps=[],
        total_target_weight_at_risk=0.0,
    )


@pytest.mark.asyncio
async def test_realize_mode_aborts_when_no_approvals() -> None:
    org_id = uuid.uuid4()
    profile = "moderate"
    db = _make_db_with_portfolio(profile, org_id)
    run = _make_run(org_id, run_mode="realize")
    optimizer_mock = AsyncMock()

    with patch.object(
        executor_mod,
        "validate_template_completeness",
        new=AsyncMock(return_value=_template_complete(org_id, profile)),
    ), patch.object(
        executor_mod,
        "validate_block_coverage",
        new=AsyncMock(return_value=_coverage_sufficient(org_id, profile)),
    ), patch.object(
        executor_mod,
        "_count_approved_blocks",
        new=AsyncMock(return_value=(0, 18)),
    ), patch(
        "app.domains.wealth.routes.model_portfolios._run_construction_async",
        new=optimizer_mock,
    ):
        with pytest.raises(NoApprovedAllocationError) as excinfo:
            await _execute_inner(
                db=db,
                run=run,
                portfolio_id=run.portfolio_id,
                calibration_snapshot={},
                job_id=None,
                propose_mode=False,
            )

    assert excinfo.value.approved_count == 0
    assert excinfo.value.total_count == 18
    optimizer_mock.assert_not_called()


@pytest.mark.asyncio
async def test_realize_mode_partial_approval_still_refused() -> None:
    org_id = uuid.uuid4()
    profile = "moderate"
    db = _make_db_with_portfolio(profile, org_id)
    run = _make_run(org_id, run_mode="realize")
    optimizer_mock = AsyncMock()

    with patch.object(
        executor_mod,
        "validate_template_completeness",
        new=AsyncMock(return_value=_template_complete(org_id, profile)),
    ), patch.object(
        executor_mod,
        "validate_block_coverage",
        new=AsyncMock(return_value=_coverage_sufficient(org_id, profile)),
    ), patch.object(
        executor_mod,
        "_count_approved_blocks",
        new=AsyncMock(return_value=(17, 18)),
    ), patch(
        "app.domains.wealth.routes.model_portfolios._run_construction_async",
        new=optimizer_mock,
    ):
        with pytest.raises(NoApprovedAllocationError):
            await _execute_inner(
                db=db,
                run=run,
                portfolio_id=run.portfolio_id,
                calibration_snapshot={},
                job_id=None,
                propose_mode=False,
            )
    optimizer_mock.assert_not_called()


@pytest.mark.asyncio
async def test_propose_mode_bypasses_the_gate() -> None:
    org_id = uuid.uuid4()
    profile = "moderate"
    db = _make_db_with_portfolio(profile, org_id)
    run = _make_run(org_id, run_mode="propose")

    # Optimizer mock raises a benign sentinel so we can stop the test
    # as soon as control flow passes the gate. Also stub downstream
    # helpers so post-optimizer logic doesn't crash with mocks.
    optimizer_mock = AsyncMock(side_effect=AssertionError("stop-post-gate"))
    count_mock = AsyncMock(return_value=(0, 18))

    with patch.object(
        executor_mod,
        "validate_template_completeness",
        new=AsyncMock(return_value=_template_complete(org_id, profile)),
    ), patch.object(
        executor_mod,
        "validate_block_coverage",
        new=AsyncMock(return_value=_coverage_sufficient(org_id, profile)),
    ), patch.object(
        executor_mod, "_count_approved_blocks", new=count_mock,
    ), patch(
        "app.domains.wealth.routes.model_portfolios._run_construction_async",
        new=optimizer_mock,
    ):
        try:
            await _execute_inner(
                db=db,
                run=run,
                portfolio_id=run.portfolio_id,
                calibration_snapshot={},
                job_id=None,
                propose_mode=True,
            )
        except AssertionError as exc:
            assert str(exc) == "stop-post-gate"

    # Propose never queries approval state.
    count_mock.assert_not_called()


@pytest.mark.asyncio
async def test_realize_mode_proceeds_when_all_blocks_approved() -> None:
    org_id = uuid.uuid4()
    profile = "moderate"
    db = _make_db_with_portfolio(profile, org_id)
    run = _make_run(org_id, run_mode="realize")

    optimizer_mock = AsyncMock(side_effect=AssertionError("stop-post-gate"))

    with patch.object(
        executor_mod,
        "validate_template_completeness",
        new=AsyncMock(return_value=_template_complete(org_id, profile)),
    ), patch.object(
        executor_mod,
        "validate_block_coverage",
        new=AsyncMock(return_value=_coverage_sufficient(org_id, profile)),
    ), patch.object(
        executor_mod,
        "_count_approved_blocks",
        new=AsyncMock(return_value=(18, 18)),
    ), patch(
        "app.domains.wealth.routes.model_portfolios._run_construction_async",
        new=optimizer_mock,
    ):
        try:
            await _execute_inner(
                db=db,
                run=run,
                portfolio_id=run.portfolio_id,
                calibration_snapshot={},
                job_id=None,
                propose_mode=False,
            )
        except AssertionError as exc:
            assert str(exc) == "stop-post-gate"

    optimizer_mock.assert_called_once()

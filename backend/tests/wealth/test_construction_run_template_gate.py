"""PR-A25 — construction_run_executor template-gate wiring tests.

Mirrors ``test_construction_run_coverage_gate.py``. Verifies that the
template completeness check runs BEFORE the coverage check, raises
``TemplateIncompleteError`` on a missing canonical block, and keeps
both the optimizer and the coverage validator off the hot path.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.models.model_portfolio import PortfolioConstructionRun
from app.domains.wealth.schemas.sanitized import WinnerSignal
from app.domains.wealth.workers import construction_run_executor as executor_mod
from app.domains.wealth.workers.construction_run_executor import (
    TemplateIncompleteError,
    _execute_inner,
    _persist_template_failure,
)
from quant_engine.allocation_template_service import TemplateReport


def _incomplete_report() -> TemplateReport:
    return TemplateReport(
        organization_id=uuid.uuid4(),
        profile="moderate",
        is_complete=False,
        missing_canonical_blocks=["fi_us_short_term", "alt_commodities"],
        extra_non_canonical_blocks=[],
    )


@pytest.mark.asyncio
async def test_persist_template_failure_populates_telemetry() -> None:
    run = PortfolioConstructionRun(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        portfolio_id=uuid.uuid4(),
        calibration_snapshot={},
        calibration_hash="x",
        universe_fingerprint="pending",
        status="running",
        requested_by="tester",
    )
    report = _incomplete_report()
    db = AsyncMock()
    await _persist_template_failure(db, run=run, report=report)

    assert run.status == "failed"
    assert "template_incomplete" in (run.failure_reason or "")
    telemetry = run.cascade_telemetry or {}
    assert (
        telemetry["winner_signal"]
        == WinnerSignal.TEMPLATE_INCOMPLETE.value
    )
    assert telemetry["operator_signal"] == telemetry["winner_signal"]
    assert telemetry["cascade_summary"] == "template_incomplete"
    assert telemetry["template_report"]["missing_canonical_blocks"] == [
        "fi_us_short_term", "alt_commodities",
    ]
    assert telemetry["operator_message"]["severity"] == "error"


@pytest.mark.asyncio
async def test_execute_inner_raises_before_coverage_and_optimizer() -> None:
    """Template gate fires first: neither the coverage gate nor the
    optimizer are reached when the template is incomplete.
    """
    report = _incomplete_report()

    portfolio_stub = MagicMock()
    portfolio_stub.profile = "moderate"
    portfolio_stub.organization_id = report.organization_id
    portfolio_result = MagicMock()
    portfolio_result.scalar_one_or_none.return_value = portfolio_stub

    db = AsyncMock()
    db.execute = AsyncMock(return_value=portfolio_result)

    run = PortfolioConstructionRun(
        id=uuid.uuid4(),
        organization_id=report.organization_id,
        portfolio_id=uuid.uuid4(),
        calibration_snapshot={},
        calibration_hash="x",
        universe_fingerprint="pending",
        status="running",
        requested_by="tester",
    )

    optimizer_mock = AsyncMock()
    coverage_mock = AsyncMock()

    with patch.object(
        executor_mod,
        "validate_template_completeness",
        new=AsyncMock(return_value=report),
    ), patch.object(
        executor_mod,
        "validate_block_coverage",
        new=coverage_mock,
    ), patch(
        "app.domains.wealth.routes.model_portfolios._run_construction_async",
        new=optimizer_mock,
    ):
        with pytest.raises(TemplateIncompleteError) as exc_info:
            await _execute_inner(
                db=db,
                run=run,
                portfolio_id=run.portfolio_id,
                calibration_snapshot={},
                job_id=None,
            )

    assert exc_info.value.report.is_complete is False
    assert len(exc_info.value.report.missing_canonical_blocks) == 2
    coverage_mock.assert_not_called()
    optimizer_mock.assert_not_called()

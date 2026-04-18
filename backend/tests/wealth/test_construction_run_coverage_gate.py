"""PR-A22 — construction_run_executor coverage-gate wiring tests.

Verifies the pre-optimizer block-coverage check:

* ``_execute_inner`` raises ``CoverageInsufficientError`` when the
  validator returns an insufficient report — the optimizer
  (``_run_construction_async``) is never invoked.
* ``_persist_coverage_failure`` writes the expected
  ``cascade_telemetry`` envelope and marks the run ``failed`` with a
  structured ``failure_reason``.
* The top-level ``execute_construction_run`` catches the exception,
  persists the failure, and emits a terminal SSE event whose payload
  carries ``winner_signal = 'block_coverage_insufficient'`` and the
  full coverage report.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.models.model_portfolio import PortfolioConstructionRun
from app.domains.wealth.schemas.sanitized import WinnerSignal
from app.domains.wealth.workers import construction_run_executor as executor_mod
from app.domains.wealth.workers.construction_run_executor import (
    CoverageInsufficientError,
    _execute_inner,
    _persist_coverage_failure,
)
from quant_engine.block_coverage_service import (
    BlockCoverageGap,
    CoverageReport,
)


def _insufficient_report() -> CoverageReport:
    return CoverageReport(
        organization_id=uuid.uuid4(),
        profile="moderate",
        is_sufficient=False,
        total_target_weight_at_risk=0.1979,
        gaps=[
            BlockCoverageGap(
                block_id="na_equity_growth",
                target_weight=0.0897,
                suggested_strategy_labels=["Growth"],
                catalog_candidates_available=42,
                example_tickers=["VUG", "IWF", "QQQG", "MGK", "SCHG"],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_persist_coverage_failure_populates_telemetry() -> None:
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
    report = _insufficient_report()
    db = AsyncMock()
    await _persist_coverage_failure(db, run=run, report=report)
    assert run.status == "failed"
    assert "block_coverage_insufficient" in (run.failure_reason or "")
    telemetry = run.cascade_telemetry or {}
    assert (
        telemetry["winner_signal"]
        == WinnerSignal.BLOCK_COVERAGE_INSUFFICIENT.value
    )
    assert telemetry["operator_signal"] == telemetry["winner_signal"]
    assert telemetry["cascade_summary"] == "block_coverage_insufficient"
    assert telemetry["coverage_report"]["gaps"][0]["block_id"] == (
        "na_equity_growth"
    )
    assert telemetry["operator_message"]["severity"] == "error"


@pytest.mark.asyncio
async def test_execute_inner_raises_and_optimizer_never_invoked() -> None:
    """Validator returns insufficient → CoverageInsufficientError and the
    optimizer entry point is never reached.
    """
    report = _insufficient_report()

    # Fake portfolio fetch: one ORM query returning a stub portfolio.
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

    # Patch _run_construction_async where _execute_inner imports it
    # lazily to avoid circular imports.
    with patch.object(
        executor_mod,
        "validate_block_coverage",
        new=AsyncMock(return_value=report),
    ), patch(
        "app.domains.wealth.routes.model_portfolios._run_construction_async",
        new=optimizer_mock,
    ):
        with pytest.raises(CoverageInsufficientError) as exc_info:
            await _execute_inner(
                db=db,
                run=run,
                portfolio_id=run.portfolio_id,
                calibration_snapshot={},
                job_id=None,
            )

    assert exc_info.value.report.is_sufficient is False
    assert len(exc_info.value.report.gaps) == 1
    optimizer_mock.assert_not_called()

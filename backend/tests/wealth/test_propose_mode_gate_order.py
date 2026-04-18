"""PR-A26.1 Section E — propose-mode honours pre-run gates.

Template completeness (A25) and block coverage (A22) gates must fire
BEFORE the propose-mode branch in ``_execute_inner``. A propose run
against an org with an incomplete canonical template must abort with
``TemplateIncompleteError`` exactly the same way realize mode does;
the optimizer must never be called.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.models.model_portfolio import PortfolioConstructionRun
from app.domains.wealth.workers import construction_run_executor as executor_mod
from app.domains.wealth.workers.construction_run_executor import (
    CoverageInsufficientError,
    TemplateIncompleteError,
    _execute_inner,
)
from quant_engine.allocation_template_service import TemplateReport
from quant_engine.block_coverage_service import (
    CoverageReport,
)


def _make_db_with_portfolio(profile: str, org_id: uuid.UUID) -> AsyncMock:
    portfolio_stub = MagicMock()
    portfolio_stub.profile = profile
    portfolio_stub.organization_id = org_id
    result = MagicMock()
    result.scalar_one_or_none.return_value = portfolio_stub
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    return db


def _make_run(org_id: uuid.UUID) -> PortfolioConstructionRun:
    return PortfolioConstructionRun(
        id=uuid.uuid4(),
        organization_id=org_id,
        portfolio_id=uuid.uuid4(),
        calibration_snapshot={},
        calibration_hash="x",
        universe_fingerprint="pending",
        status="running",
        run_mode="propose",
        requested_by="tester",
    )


@pytest.mark.asyncio
async def test_propose_mode_aborts_on_template_incomplete() -> None:
    org_id = uuid.uuid4()
    incomplete = TemplateReport(
        organization_id=org_id,
        profile="growth",
        is_complete=False,
        missing_canonical_blocks=["alt_commodities"],
        extra_non_canonical_blocks=[],
    )
    db = _make_db_with_portfolio("growth", org_id)
    run = _make_run(org_id)

    coverage_mock = AsyncMock()
    optimizer_mock = AsyncMock()

    with patch.object(
        executor_mod,
        "validate_template_completeness",
        new=AsyncMock(return_value=incomplete),
    ), patch.object(
        executor_mod, "validate_block_coverage", new=coverage_mock,
    ), patch(
        "app.domains.wealth.routes.model_portfolios._run_construction_async",
        new=optimizer_mock,
    ):
        with pytest.raises(TemplateIncompleteError):
            await _execute_inner(
                db=db,
                run=run,
                portfolio_id=run.portfolio_id,
                calibration_snapshot={},
                job_id=None,
                propose_mode=True,
            )

    coverage_mock.assert_not_called()
    optimizer_mock.assert_not_called()


@pytest.mark.asyncio
async def test_propose_mode_aborts_on_block_coverage_insufficient() -> None:
    org_id = uuid.uuid4()
    complete = TemplateReport(
        organization_id=org_id,
        profile="moderate",
        is_complete=True,
        missing_canonical_blocks=[],
        extra_non_canonical_blocks=[],
    )
    insufficient_coverage = CoverageReport(
        organization_id=org_id,
        profile="moderate",
        is_sufficient=False,
        gaps=[],
        total_target_weight_at_risk=0.40,
    )
    db = _make_db_with_portfolio("moderate", org_id)
    run = _make_run(org_id)

    optimizer_mock = AsyncMock()

    with patch.object(
        executor_mod,
        "validate_template_completeness",
        new=AsyncMock(return_value=complete),
    ), patch.object(
        executor_mod,
        "validate_block_coverage",
        new=AsyncMock(return_value=insufficient_coverage),
    ), patch(
        "app.domains.wealth.routes.model_portfolios._run_construction_async",
        new=optimizer_mock,
    ):
        with pytest.raises(CoverageInsufficientError):
            await _execute_inner(
                db=db,
                run=run,
                portfolio_id=run.portfolio_id,
                calibration_snapshot={},
                job_id=None,
                propose_mode=True,
            )

    optimizer_mock.assert_not_called()

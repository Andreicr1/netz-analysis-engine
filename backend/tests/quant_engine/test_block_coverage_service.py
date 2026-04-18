"""PR-A22 — block_coverage_service unit tests.

Pure unit coverage using an AsyncMock session. The validator's SQL is
simple enough that mocking the four query shapes is more maintainable
than seeding a real DB — and it isolates the test from the shared
``app.core.db.engine`` event loop contract.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from quant_engine.block_coverage_service import (
    BlockCoverageGap,
    CoverageReport,
    build_coverage_operator_message,
    validate_block_coverage,
)


def _make_session(
    *,
    allocations: list[tuple[str, float]],
    approved_counts: dict[str, int],
    catalog_counts: dict[str, int],
    catalog_tickers: dict[str, list[str]],
) -> AsyncMock:
    """Mock an ``AsyncSession`` whose ``execute`` matches the validator's
    four query shapes by inspecting bind parameters.
    """
    session = AsyncMock()

    class FakeResult:
        def __init__(
            self,
            *,
            rows: list[tuple] | None = None,
            scalar: int | None = None,
        ) -> None:
            self._rows = rows or []
            self._scalar = scalar

        def fetchall(self) -> list[tuple]:
            return self._rows

        def scalar_one(self) -> int:
            return self._scalar if self._scalar is not None else 0

    async def _execute(stmt, params=None):  # noqa: ANN001
        sql = str(stmt).lower()
        params = params or {}
        if "from strategic_allocation" in sql:
            return FakeResult(rows=list(allocations))
        if "from instruments_org" in sql and "count(" in sql:
            block_id = params.get("block_id")
            return FakeResult(scalar=approved_counts.get(block_id, 0))
        if (
            "from instruments_universe" in sql
            and "count(" in sql
        ):
            # Use a stable key — the labels list passed in. Tests key
            # counts by the first label in the list.
            labels = params.get("labels") or []
            key = labels[0] if labels else None
            return FakeResult(scalar=catalog_counts.get(key, 0))
        if "from instruments_universe" in sql:
            labels = params.get("labels") or []
            key = labels[0] if labels else None
            tickers = catalog_tickers.get(key, [])
            return FakeResult(rows=[(t,) for t in tickers])
        return FakeResult()

    session.execute = _execute
    return session


@pytest.mark.asyncio
async def test_all_blocks_covered_returns_sufficient() -> None:
    org_id = uuid.uuid4()
    session = _make_session(
        allocations=[("na_equity_large", 1.0)],
        approved_counts={"na_equity_large": 3},
        catalog_counts={},
        catalog_tickers={},
    )

    report = await validate_block_coverage(session, org_id, "moderate")
    assert report.is_sufficient is True
    assert report.gaps == []
    assert report.total_target_weight_at_risk == 0.0


@pytest.mark.asyncio
async def test_uncovered_block_with_catalog_candidates() -> None:
    org_id = uuid.uuid4()
    # na_equity_large maps (via block_mapping) to strategy labels
    # including "Large Blend" — that is the first label the validator
    # passes to the catalog queries.
    first_label = "Large Blend"
    session = _make_session(
        allocations=[("na_equity_large", 0.5)],
        approved_counts={"na_equity_large": 0},
        catalog_counts={first_label: 50},
        catalog_tickers={first_label: ["VOO", "IVV", "SPY", "VTI", "SCHX"]},
    )

    report = await validate_block_coverage(session, org_id, "moderate")
    assert report.is_sufficient is False
    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.block_id == "na_equity_large"
    assert gap.target_weight == pytest.approx(0.5)
    assert gap.catalog_candidates_available == 50
    assert gap.example_tickers == ["VOO", "IVV", "SPY", "VTI", "SCHX"]
    assert first_label in gap.suggested_strategy_labels
    assert report.total_target_weight_at_risk == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_uncovered_block_with_no_catalog_candidates() -> None:
    org_id = uuid.uuid4()
    # Synthetic block not present in block_mapping — the validator
    # sees an empty suggested_strategy_labels list and skips the
    # catalog queries entirely.
    session = _make_session(
        allocations=[("synthetic_block", 0.3)],
        approved_counts={"synthetic_block": 0},
        catalog_counts={},
        catalog_tickers={},
    )

    report = await validate_block_coverage(session, org_id, "aggressive")
    assert report.is_sufficient is False
    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.suggested_strategy_labels == []
    assert gap.catalog_candidates_available == 0
    assert gap.example_tickers == []
    assert report.total_target_weight_at_risk == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_multiple_blocks_mixed_coverage() -> None:
    org_id = uuid.uuid4()
    first_label = "Large Blend"
    session = _make_session(
        allocations=[
            ("na_equity_large", 0.4),
            ("fi_us_treasury", 0.3),
            ("alt_gold", 0.1),
        ],
        approved_counts={
            "na_equity_large": 0,
            "fi_us_treasury": 5,
            "alt_gold": 0,
        },
        catalog_counts={first_label: 10, "Precious Metals": 3},
        catalog_tickers={
            first_label: ["A", "B"],
            "Precious Metals": ["GLD", "IAU", "SGOL"],
        },
    )
    report = await validate_block_coverage(session, org_id, "balanced")
    assert report.is_sufficient is False
    # fi_us_treasury has 5 approved → not a gap. Two gaps expected.
    assert [g.block_id for g in report.gaps] == [
        "na_equity_large", "alt_gold",
    ]
    assert report.total_target_weight_at_risk == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_empty_strategic_allocation_is_sufficient() -> None:
    """Edge case: no allocation rows at all → nothing to validate."""
    org_id = uuid.uuid4()
    session = _make_session(
        allocations=[],
        approved_counts={},
        catalog_counts={},
        catalog_tickers={},
    )
    report = await validate_block_coverage(session, org_id, "moderate")
    assert report.is_sufficient is True
    assert report.gaps == []


def test_build_coverage_operator_message_shape() -> None:
    report = CoverageReport(
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
                example_tickers=["VUG", "IWF"],
            ),
        ],
    )
    msg = build_coverage_operator_message(report)
    assert msg["severity"] == "error"
    assert "19.8%" in msg["body"]
    assert "na_equity_growth" in msg["body"]
    assert "VUG" in msg["body"]
    assert msg["action_hint"] == "expand_universe_or_zero_weight"

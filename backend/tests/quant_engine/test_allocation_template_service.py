"""PR-A25 — allocation_template_service unit tests.

Mirror of ``test_block_coverage_service.py``. The validator issues two
queries (missing canonical, extra non-canonical) — mocking the
``AsyncSession`` keeps the test loop-agnostic and fast.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from quant_engine.allocation_template_service import (
    TemplateReport,
    build_template_operator_message,
    validate_template_completeness,
)


def _make_session(
    *,
    missing: list[str],
    extras: list[str],
) -> AsyncMock:
    """Mock an AsyncSession whose execute returns rows keyed by query text."""
    session = AsyncMock()

    class FakeResult:
        def __init__(self, rows: list[tuple]) -> None:
            self._rows = rows

        def fetchall(self) -> list[tuple]:
            return self._rows

    async def _execute(stmt, params=None):  # noqa: ANN001
        sql = str(stmt).lower()
        if "is_canonical = true" in sql and "sa.allocation_id is null" in sql:
            return FakeResult([(b,) for b in missing])
        if "is_canonical = false" in sql:
            return FakeResult([(b,) for b in extras])
        return FakeResult([])

    session.execute = _execute
    return session


@pytest.mark.asyncio
async def test_complete_template_returns_is_complete_true() -> None:
    org = uuid.uuid4()
    session = _make_session(missing=[], extras=[])
    report = await validate_template_completeness(session, org, "moderate")
    assert report.is_complete is True
    assert report.missing_canonical_blocks == []
    assert report.extra_non_canonical_blocks == []


@pytest.mark.asyncio
async def test_missing_canonical_block_fails() -> None:
    org = uuid.uuid4()
    session = _make_session(
        missing=["fi_us_short_term", "alt_commodities"],
        extras=[],
    )
    report = await validate_template_completeness(session, org, "conservative")
    assert report.is_complete is False
    assert report.missing_canonical_blocks == [
        "fi_us_short_term", "alt_commodities",
    ]


@pytest.mark.asyncio
async def test_extra_non_canonical_is_informational() -> None:
    """Extras are reported but do NOT fail the validator."""
    org = uuid.uuid4()
    session = _make_session(missing=[], extras=["fi_aggregate_legacy"])
    report = await validate_template_completeness(session, org, "growth")
    assert report.is_complete is True
    assert report.extra_non_canonical_blocks == ["fi_aggregate_legacy"]


@pytest.mark.asyncio
async def test_missing_and_extra_together() -> None:
    org = uuid.uuid4()
    session = _make_session(
        missing=["cash"],
        extras=["legacy_block"],
    )
    report = await validate_template_completeness(session, org, "moderate")
    assert report.is_complete is False
    assert report.missing_canonical_blocks == ["cash"]
    assert report.extra_non_canonical_blocks == ["legacy_block"]


def test_operator_message_shape() -> None:
    report = TemplateReport(
        organization_id=uuid.uuid4(),
        profile="moderate",
        is_complete=False,
        missing_canonical_blocks=["fi_us_short_term", "alt_commodities"],
    )
    msg = build_template_operator_message(report)
    assert msg["severity"] == "error"
    assert "missing 2 canonical allocation block" in msg["body"]
    assert "fi_us_short_term" in msg["body"]
    assert "alt_commodities" in msg["body"]
    assert msg["action_hint"] == "contact_engineering_template_trigger_failed"

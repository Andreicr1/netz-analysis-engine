"""Tests for LongFormReportEngine — G7.3."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from vertical_engines.wealth.long_form_report.long_form_report_engine import (
    LongFormReportEngine,
)
from vertical_engines.wealth.long_form_report.models import (
    CHAPTER_REGISTRY,
    LongFormReportResult,
)


class TestChapterRegistry:
    """8-chapter registry is complete."""

    def test_has_8_chapters(self) -> None:
        assert len(CHAPTER_REGISTRY) == 8

    def test_chapters_ordered(self) -> None:
        orders = [ch["order"] for ch in CHAPTER_REGISTRY]
        assert orders == list(range(1, 9))

    def test_expected_tags(self) -> None:
        tags = {ch["tag"] for ch in CHAPTER_REGISTRY}
        expected = {
            "macro_context",
            "strategic_allocation",
            "portfolio_composition",
            "performance_attribution",
            "risk_decomposition",
            "fee_analysis",
            "per_fund_highlights",
            "forward_outlook",
        }
        assert tags == expected


class TestLongFormReportResult:
    """Result model is correct."""

    def test_frozen_dataclass(self) -> None:
        result = LongFormReportResult(portfolio_id="test")
        with pytest.raises(AttributeError):
            result.status = "changed"  # type: ignore[misc]

    def test_default_status(self) -> None:
        result = LongFormReportResult(portfolio_id="test")
        assert result.status == "completed"
        assert result.chapters == []


class TestChapterIsolation:
    """Never-raises: each chapter failure is isolated."""

    @pytest.mark.asyncio
    async def test_failed_chapter_does_not_kill_others(self) -> None:
        """A chapter that raises returns status='failed' without killing the report."""
        engine = LongFormReportEngine()

        # Build a minimal context
        portfolio_id = uuid.uuid4()
        context: dict[str, Any] = {
            "portfolio": MagicMock(profile="moderate"),
            "portfolio_id": portfolio_id,
            "organization_id": str(uuid.uuid4()),
            "profile": "moderate",
            "as_of": date.today(),
            "funds_data": [],
            "macro_review": None,
            "strategic_allocations": [],
            "block_labels": {},
            "current_snapshot": None,
            "previous_snapshot": None,
            "benchmark_data": {},
        }

        db = AsyncMock()

        # Make one chapter handler raise
        original_macro = engine._chapter_macro_context

        async def _exploding_macro(*args: Any, **kwargs: Any) -> dict:
            raise RuntimeError("Macro DB connection exploded")

        engine._chapter_macro_context = _exploding_macro  # type: ignore[assignment]

        result = await engine._generate_chapter(
            "macro_context", 1, "Macro Context", context, db,
        )

        assert result.status == "failed"
        assert result.confidence == 0.0
        assert "exploded" in (result.error or "")

        # Restore
        engine._chapter_macro_context = original_macro  # type: ignore[assignment]

    @pytest.mark.asyncio
    async def test_all_chapters_attempted(self) -> None:
        """Even if some fail, all 8 chapters are attempted."""
        engine = LongFormReportEngine()
        portfolio_id = uuid.uuid4()

        # Mock _load_context
        mock_context: dict[str, Any] = {
            "portfolio": MagicMock(profile="growth"),
            "portfolio_id": portfolio_id,
            "organization_id": str(uuid.uuid4()),
            "profile": "growth",
            "as_of": date.today(),
            "funds_data": [],
            "macro_review": None,
            "strategic_allocations": [],
            "block_labels": {},
            "current_snapshot": None,
            "previous_snapshot": None,
            "benchmark_data": {},
        }

        db = AsyncMock()
        # Mock the content query for forward_outlook chapter
        db.execute.return_value = MagicMock(
            one_or_none=MagicMock(return_value=None),
            scalar_one_or_none=MagicMock(return_value=None),
        )

        with patch.object(engine, "_load_context", return_value=mock_context):
            result = await engine.generate(
                db,
                portfolio_id=str(portfolio_id),
                organization_id=str(uuid.uuid4()),
            )

        assert isinstance(result, LongFormReportResult)
        assert len(result.chapters) == 8
        # All chapters should have been attempted
        tags = {ch.tag for ch in result.chapters}
        expected_tags = {ch["tag"] for ch in CHAPTER_REGISTRY}
        assert tags == expected_tags


class TestChapterMacroContext:
    """Ch1: Macro Context pulls from MacroReview."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_review(self) -> None:
        engine = LongFormReportEngine()
        context: dict[str, Any] = {"macro_review": None}
        result = await engine._chapter_macro_context(context, AsyncMock())
        assert "summary" in result
        assert "No approved" in result["summary"]

    @pytest.mark.asyncio
    async def test_returns_data_when_review_exists(self) -> None:
        engine = LongFormReportEngine()
        context: dict[str, Any] = {
            "macro_review": {
                "as_of": date(2024, 3, 1),
                "report": {
                    "global_summary": "Markets stable",
                    "regions": [{"name": "US", "outlook": "positive"}],
                    "risk_assessment": "Low risk",
                },
            },
        }
        result = await engine._chapter_macro_context(context, AsyncMock())
        assert result["global_summary"] == "Markets stable"
        assert len(result["regions"]) == 1


class TestChapterStrategicAllocation:
    """Ch2: Strategic allocation returns block data."""

    @pytest.mark.asyncio
    async def test_returns_blocks(self) -> None:
        engine = LongFormReportEngine()
        context: dict[str, Any] = {
            "profile": "moderate",
            "strategic_allocations": [
                {"block_id": "equity_us", "target_weight": 0.4, "rationale": "Core growth"},
                {"block_id": "fixed_income", "target_weight": 0.6},
            ],
            "block_labels": {"equity_us": "US Equity", "fixed_income": "Fixed Income"},
        }
        result = await engine._chapter_strategic_allocation(context, AsyncMock())
        assert result["profile"] == "moderate"
        assert len(result["blocks"]) == 2
        assert result["blocks"][0]["display_name"] == "US Equity"


class TestChapterPerFundHighlights:
    """Ch7: Per-fund highlights detects newcomers/exits."""

    @pytest.mark.asyncio
    async def test_detects_newcomers_and_exits(self) -> None:
        engine = LongFormReportEngine()

        fund_a = str(uuid.uuid4())
        fund_b = str(uuid.uuid4())
        fund_c = str(uuid.uuid4())

        prev_snapshot = MagicMock()
        prev_snapshot.fund_selection = {
            "funds": [
                {"instrument_id": fund_a},
                {"instrument_id": fund_b},
            ],
        }

        context: dict[str, Any] = {
            "funds_data": [
                {"instrument_id": fund_a, "fund_name": "A", "weight": 0.6, "block_id": "eq"},
                {"instrument_id": fund_c, "fund_name": "C", "weight": 0.4, "block_id": "fi"},
            ],
            "current_snapshot": MagicMock(),
            "previous_snapshot": prev_snapshot,
        }

        result = await engine._chapter_per_fund_highlights(context, AsyncMock())
        assert result["total_funds"] == 2
        assert result["newcomers"] == 1  # fund_c is new
        assert result["exits"] == 1  # fund_b exited


class TestChapterFeeDrag:
    """Ch6: Fee analysis calls fee_drag/service.py."""

    @pytest.mark.asyncio
    async def test_returns_fee_analysis(self) -> None:
        engine = LongFormReportEngine()
        funds_data = [
            {
                "instrument_id": str(uuid.uuid4()),
                "fund_name": "Fund X",
                "instrument_type": "fund",
                "weight": 1.0,
                "attributes": {
                    "management_fee_pct": 1.0,
                    "expected_return_pct": 6.0,
                },
            },
        ]
        context: dict[str, Any] = {"funds_data": funds_data}
        result = await engine._chapter_fee_analysis(context, AsyncMock())
        assert result["available"] is True
        assert result["total_instruments"] == 1
        assert len(result["instruments"]) == 1

    @pytest.mark.asyncio
    async def test_returns_unavailable_when_no_funds(self) -> None:
        engine = LongFormReportEngine()
        context: dict[str, Any] = {"funds_data": []}
        result = await engine._chapter_fee_analysis(context, AsyncMock())
        assert result["available"] is False

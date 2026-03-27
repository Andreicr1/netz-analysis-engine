"""Tests for FactSheetEngine attribution and fee_drag integration (G7.4, G7.5)."""

from __future__ import annotations

import uuid
from datetime import date
from unittest.mock import MagicMock, patch

from vertical_engines.wealth.fact_sheet.fact_sheet_engine import FactSheetEngine
from vertical_engines.wealth.fact_sheet.models import (
    AttributionRow,
    FactSheetData,
)


class TestFactSheetAttribution:
    """G7.4: Attribution section present in institutional mode."""

    def test_attribution_rows_present_when_data_available(self) -> None:
        """FactSheetEngine._compute_attribution returns AttributionRow list."""
        engine = FactSheetEngine()

        funds_data = [
            {
                "instrument_id": str(uuid.uuid4()),
                "fund_name": "Fund A",
                "block_id": "equity_us",
                "weight": 0.6,
                "attributes": {"expected_return_pct": 8.0},
            },
            {
                "instrument_id": str(uuid.uuid4()),
                "fund_name": "Fund B",
                "block_id": "fixed_income",
                "weight": 0.4,
                "attributes": {"expected_return_pct": 4.0},
            },
        ]
        block_weights = {"equity_us": 0.6, "fixed_income": 0.4}

        # Mock benchmark_resolver to return data
        mock_bm_navs = {
            "equity_us": [
                {"nav_date": date(2024, 1, 2), "return_1d": 0.01},
                {"nav_date": date(2024, 1, 3), "return_1d": 0.005},
            ],
            "fixed_income": [
                {"nav_date": date(2024, 1, 2), "return_1d": 0.002},
                {"nav_date": date(2024, 1, 3), "return_1d": 0.001},
            ],
        }
        mock_block_weights = {"equity_us": 0.6, "fixed_income": 0.4}

        db = MagicMock()
        # Mock block labels query
        label_result = MagicMock()
        label_result.all.return_value = [
            ("equity_us", "US Equity"),
            ("fixed_income", "Fixed Income"),
        ]
        db.execute.return_value = label_result

        with patch(
            "app.domains.wealth.services.benchmark_resolver.fetch_benchmark_nav_series_sync",
            return_value=(mock_block_weights, mock_bm_navs),
        ):
            result = engine._compute_attribution(
                db, uuid.uuid4(), funds_data, block_weights
            )

        assert isinstance(result, list)
        assert len(result) > 0
        for row in result:
            assert isinstance(row, AttributionRow)
            assert hasattr(row, "allocation_effect")
            assert hasattr(row, "selection_effect")
            assert hasattr(row, "interaction_effect")
            assert hasattr(row, "total_effect")

    def test_attribution_returns_empty_when_no_benchmark(self) -> None:
        """Returns [] when benchmark data unavailable."""
        engine = FactSheetEngine()
        db = MagicMock()

        with patch(
            "app.domains.wealth.services.benchmark_resolver.fetch_benchmark_nav_series_sync",
            return_value=({}, {}),
        ):
            result = engine._compute_attribution(
                db, uuid.uuid4(), [], {}
            )

        assert result == []

    def test_attribution_never_raises(self) -> None:
        """Attribution failure returns [] (never-raises pattern)."""
        engine = FactSheetEngine()
        db = MagicMock()

        with patch(
            "app.domains.wealth.services.benchmark_resolver.fetch_benchmark_nav_series_sync",
            side_effect=RuntimeError("DB exploded"),
        ):
            result = engine._compute_attribution(
                db, uuid.uuid4(),
                [{"instrument_id": str(uuid.uuid4()), "block_id": "eq", "weight": 1.0, "attributes": {}}],
                {"eq": 1.0},
            )

        assert result == []


class TestFactSheetFeeDrag:
    """G7.5: Fee drag section present in institutional mode."""

    def test_fee_drag_present_when_data_available(self) -> None:
        """FactSheetEngine._compute_fee_drag returns dict."""
        engine = FactSheetEngine()

        funds_data = [
            {
                "instrument_id": str(uuid.uuid4()),
                "fund_name": "Fund A",
                "instrument_type": "fund",
                "weight": 0.6,
                "attributes": {
                    "management_fee_pct": 1.5,
                    "performance_fee_pct": 2.0,
                    "expected_return_pct": 8.0,
                },
            },
            {
                "instrument_id": str(uuid.uuid4()),
                "fund_name": "Fund B",
                "instrument_type": "fund",
                "weight": 0.4,
                "attributes": {
                    "management_fee_pct": 0.5,
                    "expected_return_pct": 4.0,
                },
            },
        ]

        result = engine._compute_fee_drag(funds_data, {"eq": 0.6, "fi": 0.4})

        assert result is not None
        assert "total_instruments" in result
        assert result["total_instruments"] == 2
        assert "weighted_gross_return" in result
        assert "weighted_net_return" in result
        assert "weighted_fee_drag_pct" in result
        assert "instruments" in result
        assert len(result["instruments"]) == 2

    def test_fee_drag_none_when_no_funds(self) -> None:
        """Returns None when no funds data."""
        engine = FactSheetEngine()
        result = engine._compute_fee_drag([], {})
        assert result is None

    def test_fee_drag_never_raises(self) -> None:
        """Fee drag failure returns None (never-raises pattern)."""
        engine = FactSheetEngine()
        # Pass invalid instrument_id to trigger error
        result = engine._compute_fee_drag(
            [{"fund_name": "X", "weight": 1.0}],  # missing instrument_id
            {"eq": 1.0},
        )
        assert result is None


class TestFactSheetDataModel:
    """FactSheetData model has new fields."""

    def test_fee_drag_field_defaults_to_none(self) -> None:
        data = FactSheetData(
            portfolio_id=uuid.uuid4(),
            portfolio_name="Test",
            profile="moderate",
            as_of=date.today(),
        )
        assert data.fee_drag is None
        assert data.attribution == []

    def test_fee_drag_field_accepts_dict(self) -> None:
        data = FactSheetData(
            portfolio_id=uuid.uuid4(),
            portfolio_name="Test",
            profile="moderate",
            as_of=date.today(),
            fee_drag={"total_instruments": 5, "weighted_fee_drag_pct": 0.3},
        )
        assert data.fee_drag["total_instruments"] == 5

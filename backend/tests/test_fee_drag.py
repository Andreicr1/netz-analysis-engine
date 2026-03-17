"""Tests for the Wealth Fee Drag Calculator — Sprint 5.

Covers:
- FeeBreakdown/FeeDragResult/PortfolioFeeDrag model integrity
- Fee extraction per instrument type (fund, bond, equity)
- Net return computation
- Fee drag ratio and efficiency flag
- Portfolio-level weighted aggregation
- Edge cases: zero gross return, missing fees, empty portfolio
"""

from __future__ import annotations

import uuid

import pytest

from vertical_engines.wealth.fee_drag.models import (
    FeeBreakdown,
    FeeDragResult,
    PortfolioFeeDrag,
)
from vertical_engines.wealth.fee_drag.service import FeeDragService

# ═══════════════════════════════════════════════════════════════════
#  Model integrity tests
# ═══════════════════════════════════════════════════════════════════


class TestModels:
    def test_fee_breakdown_frozen(self):
        fb = FeeBreakdown(
            management_fee_pct=1.5,
            performance_fee_pct=20.0,
            other_fees_pct=0.0,
            total_fee_pct=21.5,
        )
        with pytest.raises(AttributeError):
            fb.total_fee_pct = 0.0  # type: ignore[misc]

    def test_fee_drag_result_frozen(self):
        r = FeeDragResult(
            instrument_id=uuid.uuid4(),
            instrument_name="Test",
            instrument_type="fund",
            gross_expected_return=10.0,
            fee_breakdown=FeeBreakdown(1.0, 0.0, 0.0, 1.0),
            net_expected_return=9.0,
            fee_drag_pct=0.1,
            fee_efficient=True,
        )
        with pytest.raises(AttributeError):
            r.fee_efficient = False  # type: ignore[misc]

    def test_portfolio_fee_drag_frozen(self):
        p = PortfolioFeeDrag(
            total_instruments=0,
            weighted_gross_return=0.0,
            weighted_net_return=0.0,
            weighted_fee_drag_pct=0.0,
            inefficient_count=0,
            results=(),
        )
        with pytest.raises(AttributeError):
            p.total_instruments = 5  # type: ignore[misc]


# ═══════════════════════════════════════════════════════════════════
#  FeeDragService tests
# ═══════════════════════════════════════════════════════════════════


class TestFeeDragService:
    def test_fund_fee_extraction(self):
        svc = FeeDragService()
        result = svc.compute_fee_drag(
            instrument_id=uuid.uuid4(),
            instrument_name="Hedge Fund A",
            instrument_type="fund",
            attributes={
                "management_fee_pct": 2.0,
                "performance_fee_pct": 20.0,
                "expected_return_pct": 12.0,
            },
        )
        assert result.fee_breakdown.management_fee_pct == 2.0
        assert result.fee_breakdown.performance_fee_pct == 20.0
        assert result.fee_breakdown.total_fee_pct == 22.0
        assert result.net_expected_return == pytest.approx(-10.0)

    def test_bond_fee_extraction(self):
        svc = FeeDragService()
        result = svc.compute_fee_drag(
            instrument_id=uuid.uuid4(),
            instrument_name="Corp Bond",
            instrument_type="bond",
            attributes={
                "bid_ask_spread_pct": 0.5,
                "expected_return_pct": 5.0,
            },
        )
        assert result.fee_breakdown.other_fees_pct == 0.5
        assert result.fee_breakdown.total_fee_pct == 0.5
        assert result.net_expected_return == pytest.approx(4.5)

    def test_equity_fee_extraction(self):
        svc = FeeDragService()
        result = svc.compute_fee_drag(
            instrument_id=uuid.uuid4(),
            instrument_name="Tech Stock",
            instrument_type="equity",
            attributes={
                "brokerage_fee_pct": 0.1,
                "expected_return_pct": 15.0,
            },
        )
        assert result.fee_breakdown.other_fees_pct == 0.1
        assert result.net_expected_return == pytest.approx(14.9)

    def test_explicit_gross_return_overrides_attributes(self):
        svc = FeeDragService()
        result = svc.compute_fee_drag(
            instrument_id=uuid.uuid4(),
            instrument_name="Fund",
            instrument_type="fund",
            attributes={"expected_return_pct": 5.0, "management_fee_pct": 1.0},
            gross_expected_return=10.0,
        )
        assert result.gross_expected_return == 10.0
        assert result.net_expected_return == pytest.approx(9.0)

    def test_fee_efficient_below_threshold(self):
        svc = FeeDragService(fee_drag_threshold=0.50)
        result = svc.compute_fee_drag(
            instrument_id=uuid.uuid4(),
            instrument_name="Low Fee Fund",
            instrument_type="fund",
            attributes={"management_fee_pct": 0.5, "expected_return_pct": 10.0},
        )
        assert result.fee_drag_pct == pytest.approx(0.05)
        assert result.fee_efficient is True

    def test_fee_inefficient_above_threshold(self):
        svc = FeeDragService(fee_drag_threshold=0.30)
        result = svc.compute_fee_drag(
            instrument_id=uuid.uuid4(),
            instrument_name="Expensive Fund",
            instrument_type="fund",
            attributes={"management_fee_pct": 4.0, "expected_return_pct": 8.0},
        )
        assert result.fee_drag_pct == pytest.approx(0.50)
        assert result.fee_efficient is False

    def test_zero_gross_return(self):
        svc = FeeDragService()
        result = svc.compute_fee_drag(
            instrument_id=uuid.uuid4(),
            instrument_name="Zero Fund",
            instrument_type="fund",
            attributes={"management_fee_pct": 1.0},
            gross_expected_return=0.0,
        )
        assert result.fee_drag_pct == 1.0
        assert result.fee_efficient is False

    def test_no_fees(self):
        svc = FeeDragService()
        result = svc.compute_fee_drag(
            instrument_id=uuid.uuid4(),
            instrument_name="Free Fund",
            instrument_type="fund",
            attributes={"expected_return_pct": 10.0},
        )
        assert result.fee_breakdown.total_fee_pct == 0.0
        assert result.fee_drag_pct == 0.0
        assert result.fee_efficient is True


# ═══════════════════════════════════════════════════════════════════
#  Portfolio-level tests
# ═══════════════════════════════════════════════════════════════════


class TestPortfolioFeeDrag:
    def test_equal_weight_portfolio(self):
        svc = FeeDragService()
        id1, id2 = uuid.uuid4(), uuid.uuid4()
        instruments = [
            {
                "instrument_id": id1,
                "name": "Fund A",
                "instrument_type": "fund",
                "attributes": {"management_fee_pct": 1.0, "expected_return_pct": 10.0},
            },
            {
                "instrument_id": id2,
                "name": "Fund B",
                "instrument_type": "fund",
                "attributes": {"management_fee_pct": 3.0, "expected_return_pct": 10.0},
            },
        ]
        result = svc.compute_portfolio_fee_drag(instruments)
        assert result.total_instruments == 2
        assert result.weighted_gross_return == pytest.approx(10.0)
        assert result.weighted_net_return == pytest.approx(8.0)  # avg of 9.0 and 7.0

    def test_weighted_portfolio(self):
        svc = FeeDragService()
        id1, id2 = uuid.uuid4(), uuid.uuid4()
        instruments = [
            {
                "instrument_id": id1,
                "name": "Fund A",
                "instrument_type": "fund",
                "attributes": {"management_fee_pct": 1.0, "expected_return_pct": 10.0},
            },
            {
                "instrument_id": id2,
                "name": "Fund B",
                "instrument_type": "fund",
                "attributes": {"management_fee_pct": 3.0, "expected_return_pct": 10.0},
            },
        ]
        weights = {id1: 0.8, id2: 0.2}
        result = svc.compute_portfolio_fee_drag(instruments, weights)
        # weighted gross: (10*0.8 + 10*0.2) / 1.0 = 10
        # weighted net: (9*0.8 + 7*0.2) / 1.0 = 8.6
        assert result.weighted_net_return == pytest.approx(8.6)

    def test_empty_portfolio(self):
        svc = FeeDragService()
        result = svc.compute_portfolio_fee_drag([])
        assert result.total_instruments == 0
        assert result.weighted_fee_drag_pct == 0.0

    def test_inefficient_count(self):
        svc = FeeDragService(fee_drag_threshold=0.20)
        instruments = [
            {
                "instrument_id": uuid.uuid4(),
                "name": "Cheap Fund",
                "instrument_type": "fund",
                "attributes": {"management_fee_pct": 0.5, "expected_return_pct": 10.0},
            },
            {
                "instrument_id": uuid.uuid4(),
                "name": "Expensive Fund",
                "instrument_type": "fund",
                "attributes": {"management_fee_pct": 5.0, "expected_return_pct": 8.0},
            },
        ]
        result = svc.compute_portfolio_fee_drag(instruments)
        assert result.inefficient_count == 1

"""Tests for cashflow analytics service — deal-level investment performance."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from app.domains.credit.modules.deals.cashflow_service import (
    _INFLOW_TYPES,
    _OUTFLOW_TYPES,
    CashflowEntry,
    calculate_performance,
    calculate_portfolio_monitoring_metrics,
    list_cashflows,
)


def _make_cashflow_row(
    flow_type: str = "disbursement",
    amount: float = 1000.0,
    flow_date: date | None = None,
    currency: str = "USD",
    description: str | None = None,
):
    row = MagicMock()
    row.id = uuid.uuid4()
    row.deal_id = uuid.uuid4()
    row.fund_id = uuid.uuid4()
    row.flow_type = flow_type
    row.amount = amount
    row.currency = currency
    row.flow_date = flow_date or date(2026, 1, 15)
    row.description = description
    row.reference = None
    return row


FUND_ID = uuid.uuid4()
DEAL_ID = uuid.uuid4()


class TestListCashflows:
    def test_returns_entries_from_db(self):
        rows = [
            _make_cashflow_row("disbursement", 100_000, date(2025, 6, 1)),
            _make_cashflow_row("repayment_interest", 5_000, date(2025, 9, 1)),
        ]
        mock_db = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = rows
        mock_db.execute.return_value.scalars.return_value = scalars

        result = list_cashflows(mock_db, fund_id=FUND_ID, deal_id=DEAL_ID)

        assert len(result) == 2
        assert isinstance(result[0], CashflowEntry)
        assert result[0].flow_type == "disbursement"
        assert result[0].amount == Decimal(100000)
        assert result[1].flow_type == "repayment_interest"

    def test_empty_when_no_cashflows(self):
        mock_db = MagicMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        mock_db.execute.return_value.scalars.return_value = scalars

        result = list_cashflows(mock_db, fund_id=FUND_ID, deal_id=DEAL_ID)
        assert result == []


class TestCalculatePerformance:
    def test_moic_calculated_correctly(self):
        """MOIC = total_received / total_invested."""
        mock_db = MagicMock()

        # First call: group by flow_type
        type_rows = [
            MagicMock(flow_type="disbursement", total=100_000),
            MagicMock(flow_type="repayment_principal", total=80_000),
            MagicMock(flow_type="repayment_interest", total=25_000),
            MagicMock(flow_type="distribution", total=10_000),
        ]
        # Second call: first outflow date
        # Third call: first inflow date
        mock_db.execute = MagicMock(side_effect=[
            MagicMock(all=MagicMock(return_value=type_rows)),  # group by
            MagicMock(scalar=MagicMock(return_value=date(2025, 1, 1))),  # first out
            MagicMock(scalar=MagicMock(return_value=date(2025, 7, 1))),  # first in
        ])

        result = calculate_performance(mock_db, fund_id=FUND_ID, deal_id=DEAL_ID)

        assert result["total_invested"] == 100_000
        assert result["total_received"] == 115_000  # 80k + 25k + 10k
        assert result["net_cashflow"] == 15_000  # 115k - 100k
        assert result["moic"] == pytest.approx(1.15, abs=0.01)
        assert result["cash_to_cash_days"] == 181  # Jan 1 → Jul 1

    def test_no_outflows_returns_none_moic(self):
        mock_db = MagicMock()
        mock_db.execute = MagicMock(side_effect=[
            MagicMock(all=MagicMock(return_value=[])),  # no rows
            MagicMock(scalar=MagicMock(return_value=None)),  # no first out
            MagicMock(scalar=MagicMock(return_value=None)),  # no first in
        ])

        result = calculate_performance(mock_db, fund_id=FUND_ID, deal_id=DEAL_ID)

        assert result["total_invested"] == 0
        assert result["moic"] is None
        assert result["cash_to_cash_days"] is None


class TestCalculatePortfolioMonitoringMetrics:
    def test_full_metrics_computed(self):
        mock_db = MagicMock()

        type_rows = [
            MagicMock(flow_type="capital_call", total=200_000),
            MagicMock(flow_type="distribution", total=50_000),
            MagicMock(flow_type="repayment_interest", total=30_000),
            MagicMock(flow_type="repayment_principal", total=100_000),
        ]

        cashflow_rows = [
            _make_cashflow_row("capital_call", 200_000, date(2025, 1, 1)),
            _make_cashflow_row("repayment_interest", 30_000, date(2025, 6, 1)),
            _make_cashflow_row("repayment_principal", 100_000, date(2025, 12, 1)),
            _make_cashflow_row("distribution", 50_000, date(2026, 1, 1)),
        ]

        scalars = MagicMock()
        scalars.all.return_value = cashflow_rows

        mock_db.execute = MagicMock(side_effect=[
            MagicMock(all=MagicMock(return_value=type_rows)),  # group by
            # IRR: total inflows
            MagicMock(scalar=MagicMock(return_value=180_000)),
            # IRR: first outflow
            MagicMock(scalar=MagicMock(return_value=date(2025, 1, 1))),
            # IRR: first inflow
            MagicMock(scalar=MagicMock(return_value=date(2025, 6, 1))),
            # Events
            MagicMock(scalars=MagicMock(return_value=scalars)),
        ])

        result = calculate_portfolio_monitoring_metrics(
            mock_db, fund_id=FUND_ID, deal_id=DEAL_ID,
        )

        assert result["total_contributions"] == 200_000
        assert result["total_distributions"] == 50_000
        assert result["interest_received"] == 30_000
        assert result["principal_returned"] == 100_000
        # net = (50k + 30k + 100k) - 200k = -20k
        assert result["net_cash_position"] == -20_000
        # cash_to_cash = 180k / 200k = 0.9
        assert result["cash_to_cash_multiple"] == pytest.approx(0.9, abs=0.01)
        assert isinstance(result["cashflow_events"], list)
        assert len(result["cashflow_events"]) == 4

    def test_empty_deal_returns_zeros(self):
        mock_db = MagicMock()

        scalars = MagicMock()
        scalars.all.return_value = []

        mock_db.execute = MagicMock(side_effect=[
            MagicMock(all=MagicMock(return_value=[])),  # group by
            # IRR calls
            MagicMock(scalar=MagicMock(return_value=None)),
            # Events
            MagicMock(scalars=MagicMock(return_value=scalars)),
        ])

        result = calculate_portfolio_monitoring_metrics(
            mock_db, fund_id=FUND_ID, deal_id=DEAL_ID,
        )

        assert result["total_contributions"] == 0
        assert result["total_distributions"] == 0
        assert result["cash_to_cash_multiple"] == 0
        assert result["cashflow_events"] == []


class TestFlowTypeCategories:
    def test_outflow_types_are_outflows(self):
        assert "disbursement" in _OUTFLOW_TYPES
        assert "capital_call" in _OUTFLOW_TYPES

    def test_inflow_types_are_inflows(self):
        assert "repayment_principal" in _INFLOW_TYPES
        assert "repayment_interest" in _INFLOW_TYPES
        assert "distribution" in _INFLOW_TYPES

    def test_no_overlap(self):
        assert set() == _OUTFLOW_TYPES & _INFLOW_TYPES

"""Unit tests for prospectus data integration in Manager Spotlight and Fact Sheet."""

from unittest.mock import MagicMock


def test_holding_row_backwards_compatible():
    """HoldingRow positional-only construction still works (no prospectus fields)."""
    from vertical_engines.wealth.fact_sheet.models import HoldingRow

    h = HoldingRow(fund_name="Test Fund", block_id="equity", weight=0.25)
    assert h.fund_name == "Test Fund"
    assert h.block_id == "equity"
    assert h.weight == 0.25
    assert h.one_year_return is None
    assert h.expense_ratio is None
    assert h.holding_status == "Core"


def test_holding_row_with_prospectus_fields():
    """HoldingRow accepts new prospectus fields."""
    from vertical_engines.wealth.fact_sheet.models import HoldingRow

    h = HoldingRow(
        fund_name="VOO",
        block_id="equity_us",
        weight=0.30,
        one_year_return=24.5,
        expense_ratio=0.03,
        holding_status="Core",
    )
    assert h.one_year_return == 24.5
    assert h.expense_ratio == 0.03


def test_spotlight_build_user_content_with_prospectus():
    """Manager Spotlight serializes prospectus data in user content."""
    from vertical_engines.wealth.manager_spotlight import ManagerSpotlight

    engine = ManagerSpotlight()
    fund_data = {
        "name": "Vanguard S&P 500",
        "prospectus_data_source": "SEC DERA RR1 Prospectus",
        "expense_ratio_pct": 0.03,
        "net_expense_ratio_pct": 0.03,
        "management_fee_pct": 0.03,
        "portfolio_turnover_pct": 2.0,
        "avg_annual_return_1y": 24.5,
        "avg_annual_return_5y": 15.2,
        "avg_annual_return_10y": 12.8,
        "prospectus_fee_filing_date": "2025-01-15",
        "annual_return_history": [
            {"year": 2023, "annual_return_pct": 26.3},
            {"year": 2024, "annual_return_pct": 24.5},
        ],
    }

    content = engine._build_user_content(fund_data, {}, {})
    assert "SEC DERA RR1 Prospectus" in content
    assert "Total Expense Ratio: 0.0300%" in content
    assert "1-Year:  24.50%" in content
    assert "5-Year:  15.20%" in content
    assert "10-Year: 12.80%" in content
    assert "2023: +26.30%" in content
    assert "2024: +24.50%" in content


def test_spotlight_build_user_content_no_prospectus():
    """Manager Spotlight works fine without prospectus data."""
    from vertical_engines.wealth.manager_spotlight import ManagerSpotlight

    engine = ManagerSpotlight()
    fund_data = {"name": "Private Fund", "fund_type": "Hedge Fund"}

    content = engine._build_user_content(fund_data, {}, {})
    assert "SEC DERA RR1 Prospectus" not in content
    assert "Private Fund" in content


def test_enrich_holdings_no_instruments():
    """_enrich_holdings_with_prospectus returns original when no instrument_ids."""
    from vertical_engines.wealth.fact_sheet.fact_sheet_engine import FactSheetEngine
    from vertical_engines.wealth.fact_sheet.models import HoldingRow

    engine = FactSheetEngine()
    db = MagicMock()
    holdings = [HoldingRow(fund_name="X", block_id="eq", weight=0.5)]

    result = engine._enrich_holdings_with_prospectus(db, [], holdings)
    assert result is holdings  # returns same list when no instrument_ids

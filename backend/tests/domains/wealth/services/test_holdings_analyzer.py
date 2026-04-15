"""Unit tests for holdings analyzer with synthetic fixtures."""
from datetime import date

import pytest

from app.domains.wealth.services.holdings_analyzer import analyze_holdings


def _holding(asset_class, pct_of_nav, sector=None, isin=None, currency=None):
    return {
        "asset_class": asset_class,
        "pct_of_nav": pct_of_nav,
        "sector": sector,
        "isin": isin,
        "currency": currency,
        "report_date": date(2026, 3, 31),
    }


class TestAssetClassBucketing:
    def test_equity_dominant_fund(self):
        holdings = [
            _holding("EC", 10, "Technology", "US0378331005"),
            _holding("EC", 8, "Financials", "US0231351067"),
            _holding("EC", 7, "Healthcare", "US02079K3059"),
            _holding("EC", 5, "Energy", "US7185461040"),
            _holding("EC", 70, "Consumer Discretionary", "US0231351067"),
        ]
        r = analyze_holdings(holdings)
        assert r.equity_pct == 100.0
        assert r.fixed_income_pct == 0.0

    def test_fixed_income_dominant(self):
        holdings = [
            _holding("DBT", 30, isin="US912810TQ07"),
            _holding("UST", 40, isin="US912810TQ07"),
            _holding("CORP", 25, isin="US12345678"),
            _holding("ST", 5),
        ]
        r = analyze_holdings(holdings)
        assert r.fixed_income_pct == 95.0
        assert r.cash_pct == 5.0

    def test_balanced_60_40(self):
        holdings = [
            _holding("EC", 60, "Technology", "US0378331005"),
            _holding("DBT", 40, isin="US912810TQ07"),
        ]
        r = analyze_holdings(holdings)
        assert r.equity_pct == 60.0
        assert r.fixed_income_pct == 40.0

    def test_global_macro_signature(self):
        """Derivatives heavy + FX exposure = Global Macro."""
        holdings = [
            _holding("DFE", 30, currency="EUR"),
            _holding("DIR", 25),
            _holding("DCO", 15),
            _holding("ST", 30),
        ]
        r = analyze_holdings(holdings)
        assert r.derivatives_pct >= 70
        assert r.derivatives_fx_pct >= 30
        assert r.derivatives_ir_pct >= 25


class TestSectorConcentration:
    def test_top_sectors_and_hhi(self):
        holdings = [
            _holding("EC", 40, "Technology"),
            _holding("EC", 30, "Technology"),
            _holding("EC", 20, "Healthcare"),
            _holding("EC", 10, "Financials"),
        ]
        r = analyze_holdings(holdings)
        assert r.top_sectors[0][0] == "Technology"
        assert r.top_sectors[0][1] == 70.0
        assert r.sector_hhi == pytest.approx(5400.0)

    def test_zero_equity_no_sector_data(self):
        holdings = [_holding("DBT", 100, isin="US912810TQ07")]
        r = analyze_holdings(holdings)
        assert r.top_sectors == []
        assert r.sector_hhi == 0.0


class TestGeography:
    def test_us_dominant(self):
        holdings = [
            _holding("EC", 80, isin="US0378331005"),
            _holding("EC", 20, isin="US0231351067"),
        ]
        r = analyze_holdings(holdings)
        assert r.geography_us_pct == 100.0
        assert r.geography_europe_pct == 0.0

    def test_european_fund(self):
        holdings = [
            _holding("EC", 30, isin="DE0001234567"),
            _holding("EC", 25, isin="FR0012345678"),
            _holding("EC", 20, isin="GB0009876543"),
            _holding("EC", 25, isin="IT0123456789"),
        ]
        r = analyze_holdings(holdings)
        assert r.geography_europe_pct == 100.0

    def test_emerging_markets(self):
        holdings = [
            _holding("EC", 40, isin="CN1234567890"),
            _holding("EC", 25, isin="IN9876543210"),
            _holding("EC", 20, isin="BR0011223344"),
            _holding("EC", 15, isin="MX5566778899"),
        ]
        r = analyze_holdings(holdings)
        assert r.geography_em_pct == 100.0


class TestStyleTilts:
    def test_growth_tilted_portfolio(self):
        holdings = [
            _holding("EC", 30, "Technology", "US0378331005"),
            _holding("EC", 25, "Healthcare", "US02079K3059"),
            _holding("EC", 20, "Consumer Discretionary", "US0231351067"),
            _holding("EC", 15, "Financials", "US12345678"),
            _holding("EC", 10, "Energy", "US7185461040"),
        ]
        r = analyze_holdings(holdings)
        assert r.growth_tilt is not None
        assert r.growth_tilt > 0.3

    def test_value_tilted_portfolio(self):
        holdings = [
            _holding("EC", 30, "Financials"),
            _holding("EC", 25, "Energy"),
            _holding("EC", 20, "Utilities"),
            _holding("EC", 15, "Materials"),
            _holding("EC", 10, "Consumer Staples"),
        ]
        r = analyze_holdings(holdings)
        assert r.growth_tilt is not None
        assert r.growth_tilt < -0.3

    def test_fixed_income_has_no_style_tilt(self):
        holdings = [_holding("DBT", 100)]
        r = analyze_holdings(holdings)
        assert r.growth_tilt is None
        assert r.size_tilt is None


class TestEdgeCases:
    def test_empty_holdings_returns_empty_analysis(self):
        r = analyze_holdings([])
        assert r.n_holdings == 0
        assert r.total_nav_covered_pct == 0.0

    def test_coverage_quality_thresholds(self):
        r = analyze_holdings([_holding("EC", 95, "Technology")])
        assert r.coverage_quality == "high"
        r = analyze_holdings([_holding("EC", 75, "Technology")])
        assert r.coverage_quality == "medium"
        r = analyze_holdings([_holding("EC", 50, "Technology")])
        assert r.coverage_quality == "low"

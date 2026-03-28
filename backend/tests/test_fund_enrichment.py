"""Tests for gather_fund_enrichment() — Phase 1 fund enrichment in DD reports.

Covers:
- Early exit on missing CIK or wrong universe
- Registered fund base dict structure
- Share class population from SecFundClass
- Vehicle-specific branches (ETF, BDC, MMF)
- Exception resilience (returns {} on error)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _mock_fund(**kwargs):
    """Factory for SecRegisteredFund-like mock."""
    fund = MagicMock()
    fund.cik = kwargs.get("cik", "0001234567")
    fund.series_id = kwargs.get("series_id")
    fund.strategy_label = kwargs.get("strategy_label", "US Large Cap Growth")
    fund.is_index = kwargs.get("is_index", False)
    fund.is_non_diversified = kwargs.get("is_non_diversified", False)
    fund.is_target_date = kwargs.get("is_target_date", False)
    fund.is_fund_of_fund = kwargs.get("is_fund_of_fund", False)
    fund.is_master_feeder = kwargs.get("is_master_feeder", False)
    fund.is_sec_lending_authorized = kwargs.get("is_sec_lending_authorized", True)
    fund.did_lend_securities = kwargs.get("did_lend_securities", False)
    fund.has_swing_pricing = kwargs.get("has_swing_pricing", False)
    fund.did_pay_broker_research = kwargs.get("did_pay_broker_research", True)
    fund.management_fee = kwargs.get("management_fee")
    fund.net_operating_expenses = kwargs.get("net_operating_expenses")
    fund.monthly_avg_net_assets = kwargs.get("monthly_avg_net_assets", 5_000_000_000.0)
    fund.inception_date = kwargs.get("inception_date", "2010-01-15")
    return fund


def _mock_fund_class(**kwargs):
    """Factory for SecFundClass-like mock."""
    sc = MagicMock()
    sc.class_id = kwargs.get("class_id", "C000012345")
    sc.ticker = kwargs.get("ticker", "VFINX")
    sc.expense_ratio_pct = kwargs.get("expense_ratio_pct", 0.14)
    sc.advisory_fees_paid = kwargs.get("advisory_fees_paid", 1_500_000.0)
    sc.net_assets = kwargs.get("net_assets", 40_000_000_000.0)
    sc.holdings_count = kwargs.get("holdings_count", 507)
    sc.portfolio_turnover_pct = kwargs.get("portfolio_turnover_pct", 3.0)
    sc.avg_annual_return_pct = kwargs.get("avg_annual_return_pct", 12.5)
    return sc


def _mock_session(fund=None, class_rows=None, vehicle=None, vehicle_type=None):
    """Build a sync Session mock with chained .query().filter().first()/.all()."""
    db = MagicMock()

    def _query_side_effect(model):
        chain = MagicMock()
        filter_chain = MagicMock()
        chain.filter.return_value = filter_chain

        model_name = model.__name__ if hasattr(model, "__name__") else str(model)

        if model_name == "SecRegisteredFund":
            filter_chain.first.return_value = fund
        elif model_name == "SecFundClass":
            filter_chain.all.return_value = class_rows or []
        elif model_name in ("SecEtf", "SecBdc", "SecMoneyMarketFund"):
            filter_chain.first.return_value = vehicle if model_name == vehicle_type else None
        else:
            filter_chain.first.return_value = None
            filter_chain.all.return_value = []

        return chain

    db.query.side_effect = _query_side_effect
    return db


class TestGatherFundEnrichment:
    """Unit tests for sec_injection.gather_fund_enrichment()."""

    def test_returns_empty_when_no_cik(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        result = gather_fund_enrichment(MagicMock(), fund_cik=None, sec_universe="registered_us")
        assert result == {}

    def test_returns_empty_when_wrong_universe(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        result = gather_fund_enrichment(MagicMock(), fund_cik="0001234567", sec_universe="ucits_eu")
        assert result == {}

    @pytest.mark.parametrize("universe", ["etf", "bdc", "money_market", "private_us", None])
    def test_returns_empty_for_non_registered_universes(self, universe):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        result = gather_fund_enrichment(MagicMock(), fund_cik="0001234567", sec_universe=universe)
        assert result == {}

    def test_registered_fund_basic(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        fund = _mock_fund(strategy_label="US Equity Growth", is_index=True)
        db = _mock_session(fund=fund)

        result = gather_fund_enrichment(db, fund_cik="0001234567", sec_universe="registered_us")

        assert result["enrichment_available"] is True
        assert result["strategy_label"] == "US Equity Growth"
        assert result["classification"]["is_index"] is True
        assert result["classification"]["is_target_date"] is False
        assert result["operational"]["is_sec_lending_authorized"] is True
        assert result["monthly_avg_net_assets"] == 5_000_000_000.0
        assert result["fund_inception_date"] == "2010-01-15"

    def test_share_classes_populated(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        fund = _mock_fund()
        classes = [
            _mock_fund_class(class_id="C000001", ticker="VFINX", expense_ratio_pct=0.14),
            _mock_fund_class(class_id="C000002", ticker="VFIAX", expense_ratio_pct=0.04),
        ]
        db = _mock_session(fund=fund, class_rows=classes)

        result = gather_fund_enrichment(db, fund_cik="0001234567", sec_universe="registered_us")

        assert len(result["share_classes"]) == 2
        assert result["share_classes"][0]["class_id"] == "C000001"
        assert result["share_classes"][0]["expense_ratio_pct"] == 0.14
        assert result["share_classes"][1]["class_id"] == "C000002"
        assert result["share_classes"][1]["expense_ratio_pct"] == 0.04

    def test_etf_vehicle_specific(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        fund = _mock_fund(series_id="S000012345")
        etf = MagicMock()
        etf.tracking_difference_gross = 0.12
        etf.tracking_difference_net = 0.08
        etf.index_tracked = "S&P 500"
        db = _mock_session(fund=fund, vehicle=etf, vehicle_type="SecEtf")

        result = gather_fund_enrichment(db, fund_cik="0001234567", sec_universe="registered_us")

        assert result["vehicle_specific"]["type"] == "etf"
        assert result["vehicle_specific"]["index_tracked"] == "S&P 500"
        assert result["vehicle_specific"]["tracking_difference_net"] == 0.08

    def test_bdc_vehicle_specific(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        fund = _mock_fund(series_id="S000099999")
        bdc = MagicMock()
        bdc.investment_focus = "Private Credit"
        bdc.is_externally_managed = True
        db = _mock_session(fund=fund, vehicle=bdc, vehicle_type="SecBdc")

        result = gather_fund_enrichment(db, fund_cik="0001234567", sec_universe="registered_us")

        assert result["vehicle_specific"]["type"] == "bdc"
        assert result["vehicle_specific"]["investment_focus"] == "Private Credit"
        assert result["vehicle_specific"]["is_externally_managed"] is True

    def test_mmf_vehicle_specific(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        fund = _mock_fund(series_id="S000088888")
        mmf = MagicMock()
        mmf.mmf_category = "Government"
        mmf.weighted_avg_maturity = 25
        mmf.weighted_avg_life = 45
        mmf.seven_day_gross_yield = 4.85
        db = _mock_session(fund=fund, vehicle=mmf, vehicle_type="SecMoneyMarketFund")

        result = gather_fund_enrichment(db, fund_cik="0001234567", sec_universe="registered_us")

        assert result["vehicle_specific"]["type"] == "mmf"
        assert result["vehicle_specific"]["mmf_category"] == "Government"
        assert result["vehicle_specific"]["seven_day_gross_yield"] == 4.85

    def test_exception_returns_empty(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        db = MagicMock()
        db.query.side_effect = RuntimeError("connection lost")

        result = gather_fund_enrichment(db, fund_cik="0001234567", sec_universe="registered_us")
        assert result == {}

    def test_ncen_fees_populated_when_present(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        fund = _mock_fund(management_fee=0.75, net_operating_expenses=1.20)
        db = _mock_session(fund=fund)

        result = gather_fund_enrichment(db, fund_cik="0001234567", sec_universe="registered_us")

        assert result["ncen_fees"]["management_fee"] == 0.75
        assert result["ncen_fees"]["net_operating_expenses"] == 1.20

    def test_ncen_fees_empty_when_none(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        fund = _mock_fund(management_fee=None, net_operating_expenses=None)
        db = _mock_session(fund=fund)

        result = gather_fund_enrichment(db, fund_cik="0001234567", sec_universe="registered_us")

        assert result["ncen_fees"] == {}

    def test_no_vehicle_specific_without_series_id(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        fund = _mock_fund(series_id=None)
        db = _mock_session(fund=fund)

        result = gather_fund_enrichment(db, fund_cik="0001234567", sec_universe="registered_us")

        assert "vehicle_specific" not in result

    def test_returns_empty_when_fund_not_found(self):
        from vertical_engines.wealth.dd_report.sec_injection import gather_fund_enrichment

        db = _mock_session(fund=None)

        result = gather_fund_enrichment(db, fund_cik="0009999999", sec_universe="registered_us")
        assert result == {}

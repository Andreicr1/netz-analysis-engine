"""Unit tests for holdings analyzer with synthetic fixtures.

The analyzer treats ``sec_nport_holdings.sector`` as N-PORT issuerCat
(CORP/MUN/UST/USGSE/USGA/RF/PF/NUSS/OTHER) — *not* GICS. Tests use those
codes as ``sector`` values to mirror production data.
"""
from datetime import date

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
        # All EC/CORP — production-realistic shape.
        holdings = [
            _holding("EC", 10, "CORP", "US0378331005"),
            _holding("EC", 8, "CORP", "US0231351067"),
            _holding("EC", 7, "CORP", "US02079K3059"),
            _holding("EC", 5, "CORP", "US7185461040"),
            _holding("EC", 70, "CORP", "US0231351067"),
        ]
        r = analyze_holdings(holdings)
        assert r.equity_pct == 100.0
        assert r.fixed_income_pct == 0.0

    def test_fixed_income_dominant(self):
        holdings = [
            _holding("DBT", 30, "CORP"),
            _holding("UST", 40, "UST"),
            _holding("DBT", 25, "CORP"),
            _holding("ST", 5),
        ]
        r = analyze_holdings(holdings)
        assert r.fixed_income_pct == 95.0
        assert r.cash_pct == 5.0

    def test_balanced_60_40(self):
        holdings = [
            _holding("EC", 60, "CORP", "US0378331005"),
            _holding("DBT", 40, "CORP"),
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

    def test_mbs_and_loans_bucketed_as_fixed_income(self):
        holdings = [
            _holding("ABS-MBS", 60, "CORP"),
            _holding("LON", 30, "CORP"),
            _holding("ST", 10),
        ]
        r = analyze_holdings(holdings)
        assert r.fixed_income_pct == 90.0
        assert r.fi_mbs_pct == 60.0
        assert r.fi_loan_pct == 30.0

    def test_real_estate_asset_class(self):
        holdings = [
            _holding("RE", 80, "CORP", "US0378331005"),
            _holding("EC", 15, "CORP", "US12345678"),
            _holding("ST", 5),
        ]
        r = analyze_holdings(holdings)
        assert r.equity_pct == 95.0
        assert r.equity_real_estate_pct == 80.0


class TestFixedIncomeSubtypes:
    def test_government_bond_breakdown(self):
        holdings = [
            _holding("UST", 50, "UST"),
            _holding("DBT", 25, "USGSE"),
            _holding("DBT", 20, "USGA"),
            _holding("ST", 5),
        ]
        r = analyze_holdings(holdings)
        assert r.fi_government_pct == 95.0
        assert r.fi_municipal_pct == 0.0
        assert r.fi_corporate_pct == 0.0

    def test_municipal_bond_breakdown(self):
        holdings = [
            _holding("DBT", 90, "MUN"),
            _holding("ST", 10),
        ]
        r = analyze_holdings(holdings)
        assert r.fi_municipal_pct == 90.0
        assert r.fi_government_pct == 0.0

    def test_corporate_bond_breakdown(self):
        holdings = [
            _holding("DBT", 70, "CORP"),
            _holding("DBT", 25, "CORP"),
            _holding("ST", 5),
        ]
        r = analyze_holdings(holdings)
        assert r.fi_corporate_pct == 95.0
        assert r.fi_government_pct == 0.0

    def test_corp_on_equity_does_not_register_as_fi_corporate(self):
        """The CORP/EC false-positive guard: CORP issuerCat on equity must
        NOT be counted as fi_corporate (otherwise every equity fund would
        look like 100% corporate bonds)."""
        holdings = [
            _holding("EC", 95, "CORP", "US0378331005"),
            _holding("ST", 5),
        ]
        r = analyze_holdings(holdings)
        assert r.equity_pct == 95.0
        assert r.fi_corporate_pct == 0.0


class TestGeography:
    def test_us_dominant(self):
        holdings = [
            _holding("EC", 80, "CORP", "US0378331005"),
            _holding("EC", 20, "CORP", "US0231351067"),
        ]
        r = analyze_holdings(holdings)
        assert r.geography_us_pct == 100.0
        assert r.geography_europe_pct == 0.0

    def test_european_fund(self):
        holdings = [
            _holding("EC", 30, "CORP", "DE0001234567"),
            _holding("EC", 25, "CORP", "FR0012345678"),
            _holding("EC", 20, "CORP", "GB0009876543"),
            _holding("EC", 25, "CORP", "IT0123456789"),
        ]
        r = analyze_holdings(holdings)
        assert r.geography_europe_pct == 100.0

    def test_emerging_markets(self):
        holdings = [
            _holding("EC", 40, "CORP", "CN1234567890"),
            _holding("EC", 25, "CORP", "IN9876543210"),
            _holding("EC", 20, "CORP", "BR0011223344"),
            _holding("EC", 15, "CORP", "MX5566778899"),
        ]
        r = analyze_holdings(holdings)
        assert r.geography_em_pct == 100.0


class TestEdgeCases:
    def test_empty_holdings_returns_empty_analysis(self):
        r = analyze_holdings([])
        assert r.n_holdings == 0
        assert r.total_nav_covered_pct == 0.0

    def test_coverage_quality_thresholds(self):
        r = analyze_holdings([_holding("EC", 95, "CORP")])
        assert r.coverage_quality == "high"
        r = analyze_holdings([_holding("EC", 75, "CORP")])
        assert r.coverage_quality == "medium"
        r = analyze_holdings([_holding("EC", 50, "CORP")])
        assert r.coverage_quality == "low"

    def test_coverage_over_130_treated_as_low(self):
        """Trust-CIK aggregation produces pct_of_nav sums >> 100%. Those
        rows conflate multiple sub-funds and must NOT be trusted for
        single-fund classification — the analyzer flags them as low
        coverage so Layer 0 skips them and the cascade falls through to
        Layer 1 (Tiingo) or Layer 2 (name regex)."""
        # Simulate a trust CIK aggregating 5 funds (~500% total)
        many = [_holding("EC", 100, "CORP", "US0378331005") for _ in range(5)]
        r = analyze_holdings(many)
        assert r.total_nav_covered_pct == 500.0
        assert r.coverage_quality == "low"

    def test_coverage_135_just_over_threshold_is_low(self):
        r = analyze_holdings([_holding("EC", 135, "CORP")])
        assert r.coverage_quality == "low"

    def test_coverage_125_within_threshold_is_high(self):
        r = analyze_holdings([_holding("EC", 125, "CORP")])
        assert r.coverage_quality == "high"

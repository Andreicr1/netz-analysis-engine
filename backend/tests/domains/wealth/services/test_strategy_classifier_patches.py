"""Regression tests for classifier patches round 1."""
from app.domains.wealth.services.strategy_classifier import (
    STRATEGY_LABELS,
    classify_fund,
)


class TestTaxonomyExpansion:
    def test_structured_credit_in_taxonomy(self):
        assert "Structured Credit" in STRATEGY_LABELS


class TestTaxFreeMunicipal:
    def test_franklin_california_tax_free(self):
        result = classify_fund(
            fund_name="Franklin California Intermediate-Term Tax-Free Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Municipal Bond"

    def test_tax_free_in_description(self):
        result = classify_fund(
            fund_name="Generic Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=(
                "invests at least 80% of its assets in tax-free municipal obligations"
            ),
        )
        assert result.strategy_label == "Municipal Bond"


class TestGovernmentBondPatterns:
    def test_limited_term_us_government_fund(self):
        result = classify_fund(
            fund_name="Limited Term U.S. Government Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Government Bond"

    def test_integrity_short_term_government(self):
        result = classify_fund(
            fund_name="Integrity Short Term Government Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Government Bond"

    def test_government_securities_fund(self):
        result = classify_fund(
            fund_name="Pioneer Government Securities",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Government Bond"

    def test_government_obligations(self):
        result = classify_fund(
            fund_name="BlackRock Government Obligations Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Government Bond"


class TestPESubstrategies:
    def test_secondaries_fund(self):
        result = classify_fund(
            fund_name="Apollo Global Private Equity Secondaries Fund",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Private Equity"
        assert "secondaries" in (result.matched_pattern or "")

    def test_coinvest_fund(self):
        result = classify_fund(
            fund_name="Blackstone Co-Invest Partners",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Private Equity"
        assert "coinvest" in (result.matched_pattern or "")

    def test_growth_equity_fund(self):
        result = classify_fund(
            fund_name="General Atlantic Growth Equity Fund",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Private Equity"
        assert "growth" in (result.matched_pattern or "")

    def test_infrastructure_pe(self):
        result = classify_fund(
            fund_name="KKR Global Infrastructure Investors",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Infrastructure"


class TestStructuredCredit:
    def test_battalion_clo(self):
        result = classify_fund(
            fund_name="BATTALION CLO XVI",
            fund_type="Securitized Asset Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Structured Credit"

    def test_voya_clo(self):
        result = classify_fund(
            fund_name="VOYA CLO 2020-1",
            fund_type="Securitized Asset Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Structured Credit"

    def test_clo_in_description(self):
        result = classify_fund(
            fund_name="Generic Fund",
            fund_type="Mutual Fund",
            tiingo_description=(
                "invests in collateralized loan obligations and other "
                "structured credit instruments"
            ),
        )
        assert result.strategy_label == "Structured Credit"

    def test_cdo_in_description(self):
        result = classify_fund(
            fund_name="Generic Fund",
            fund_type="Mutual Fund",
            tiingo_description=(
                "the fund invests primarily in CDOs and CLOs across the "
                "capital structure"
            ),
        )
        assert result.strategy_label == "Structured Credit"


class TestStyleWithoutSize:
    def test_vanguard_selected_value(self):
        result = classify_fund(
            fund_name="Vanguard Selected Value Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Value"
        assert "style_only" in (result.matched_pattern or "")

    def test_dodge_and_cox_growth(self):
        result = classify_fund(
            fund_name="Dodge & Cox Growth Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Growth"

    def test_generic_value_fund(self):
        result = classify_fund(
            fund_name="American Century Value Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Value"


class TestHedgeFallback:
    def test_hedge_fund_with_no_substrategy_match(self):
        result = classify_fund(
            fund_name="Generic Alpha Partners",
            fund_type="Hedge Fund",
            tiingo_description=None,
        )
        assert result.strategy_label is not None
        assert result.strategy_label in ("Multi-Strategy", "Hedge Fund")


class TestNoRegressions:
    def test_goldman_still_not_precious_metals(self):
        result = classify_fund(
            fund_name="GOLDMAN SACHS TRUST - LARGE CAP GROWTH FUND",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Growth"

    def test_credit_allocation_still_balanced(self):
        result = classify_fund(
            fund_name="Credit Allocation Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Balanced"

    def test_pgim_real_estate_income_still_real_estate(self):
        result = classify_fund(
            fund_name="PGIM Real Estate Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"

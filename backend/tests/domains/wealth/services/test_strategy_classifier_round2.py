"""Regression tests for Round 2 classifier patches.

Patches covered:
    P1 — Long/Short UCITS gate fix (outside hedge fund_type)
    P2 — Standalone Convertible Securities (non-hedge mutual funds)
    P3 — Sector Equity name patterns
    P4 — Mortgage-Backed / Asset-Backed Securities
    P5 — Long-leverage ETFs (2x/3x/ultra/daily bull)
    P6 — ESG / Sustainable (equity vs bond)
    P7 — European Bond + European Equity (ESMA UCITS coverage)
    P8 — Asian Equity + Emerging Markets Debt
"""
from __future__ import annotations

import pytest

from app.domains.wealth.services.strategy_classifier import (
    STRATEGY_LABELS,
    classify_fund,
)


class TestTaxonomyExpansion:
    @pytest.mark.parametrize(
        "label",
        [
            "European Equity",
            "Asian Equity",
            "ESG/Sustainable Equity",
            "European Bond",
            "Emerging Markets Debt",
            "ESG/Sustainable Bond",
            "Mortgage-Backed Securities",
            "Asset-Backed Securities",
            "Convertible Securities",
        ],
    )
    def test_new_label_in_taxonomy(self, label: str) -> None:
        assert label in STRATEGY_LABELS

    def test_taxonomy_size_after_round2(self) -> None:
        # Round 1 had 42 labels. Round 2 adds 9 (3 equity geo/thematic + 5
        # FI geo/sector/thematic + 1 convertible securities) → 51.
        assert len(STRATEGY_LABELS) == 51


class TestLongShortUCITS:
    """CRITICAL BUG FIX: Long/Short gate was limited to hedge fund_type."""

    def test_ucits_long_short_equity(self) -> None:
        result = classify_fund(
            fund_name="Pictet Long Short Global Equity",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "Long/Short Equity"

    def test_hedge_fund_long_short_still_works(self) -> None:
        result = classify_fund(
            fund_name="Bridgewater Long/Short Equity Fund",
            fund_type="Hedge Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Long/Short Equity"

    def test_long_short_in_description(self) -> None:
        result = classify_fund(
            fund_name="Global Alpha Fund",
            fund_type="UCITS",
            tiingo_description=(
                "employs a long-short equity strategy with paired positions "
                "in US and European markets across multiple sectors"
            ),
        )
        assert result.strategy_label == "Long/Short Equity"


class TestConvertibleSecurities:
    def test_columbia_convertible_securities(self) -> None:
        result = classify_fund(
            fund_name="Columbia Convertible Securities Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Convertible Securities"

    def test_franklin_convertible(self) -> None:
        result = classify_fund(
            fund_name="Franklin Convertible Securities",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Convertible Securities"

    def test_hedge_fund_convertible_arbitrage_still_works(self) -> None:
        result = classify_fund(
            fund_name="Marathon Convertible Arbitrage",
            fund_type="Hedge Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Convertible Arbitrage"


class TestSectorEquity:
    @pytest.mark.parametrize(
        "name,expected_sector",
        [
            ("Fidelity Select Energy Portfolio", "energy"),
            ("Vanguard Health Care ETF", "healthcare"),
            ("First Trust Technology Dividend", "technology"),
            ("iShares Global Financials ETF", "financials"),
            ("Utilities Select Sector SPDR", "utilities"),
            ("Consumer Discretionary Select Sector", "consumer"),
            ("Industrial Select Sector SPDR", "industrials"),
        ],
    )
    def test_sector_etf(self, name: str, expected_sector: str) -> None:
        result = classify_fund(
            fund_name=name,
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Sector Equity"
        assert expected_sector in (result.matched_pattern or "")


class TestMortgageAndAssetBacked:
    def test_pimco_mortgage_securities(self) -> None:
        result = classify_fund(
            fund_name="PIMCO Mortgage-Backed Securities Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Mortgage-Backed Securities"

    def test_cmbs_fund(self) -> None:
        result = classify_fund(
            fund_name="BlackRock CMBS Opportunity Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Mortgage-Backed Securities"

    def test_asset_backed_securities(self) -> None:
        result = classify_fund(
            fund_name="TCW Asset-Backed Securities Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Asset-Backed Securities"

    def test_abs_capital_firm_not_abs_fund(self) -> None:
        """Firm name 'ABS Capital' must not trigger ABS classification."""
        result = classify_fund(
            fund_name="ABS Capital Partners Growth Fund",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Private Equity"

    def test_mortgage_real_estate_still_real_estate(self) -> None:
        """Round 1 regression: 'Mortgage Real Estate ETF' stays Real Estate."""
        result = classify_fund(
            fund_name="iShares Mortgage Real Estate ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"


class TestLongLeverageETFs:
    def test_proshares_ultra_sp500(self) -> None:
        """ProShares Ultra S&P 500 (2x) classifies underlying as Large Blend."""
        result = classify_fund(
            fund_name="ProShares Ultra S&P 500",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Blend"
        assert "leveraged" in (result.matched_pattern or "")

    def test_direxion_daily_3x_bull(self) -> None:
        result = classify_fund(
            fund_name="Direxion Daily Financial Bull 3X Shares",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Sector Equity"
        assert "leveraged" in (result.matched_pattern or "")

    def test_inverse_still_works(self) -> None:
        """Round 1 regression: inverse ETFs still classify their underlying."""
        result = classify_fund(
            fund_name="ProShares Short Real Estate",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"
        assert "short" in (result.matched_pattern or "")


class TestESGSustainable:
    def test_blackrock_sustainable_equity(self) -> None:
        result = classify_fund(
            fund_name="BlackRock Sustainable Advantage Large Cap Core",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "ESG/Sustainable Equity"

    def test_vanguard_esg_etf(self) -> None:
        result = classify_fund(
            fund_name="Vanguard ESG U.S. Stock ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "ESG/Sustainable Equity"

    def test_esg_bond_fund(self) -> None:
        result = classify_fund(
            fund_name="iShares ESG Aware U.S. Aggregate Bond ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "ESG/Sustainable Bond"

    def test_sri_fund(self) -> None:
        result = classify_fund(
            fund_name="Parnassus Core SRI Equity Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "ESG/Sustainable Equity"


class TestEuropeanBondAndEquity:
    def test_european_bond_fund(self) -> None:
        result = classify_fund(
            fund_name="Fidelity European Bond Fund",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "European Bond"

    def test_european_sovereign(self) -> None:
        result = classify_fund(
            fund_name="BlackRock European Sovereign",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "European Bond"

    def test_european_equity(self) -> None:
        result = classify_fund(
            fund_name="Fidelity European Equity Fund",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "European Equity"

    def test_eurozone_equity(self) -> None:
        result = classify_fund(
            fund_name="Lyxor EuroZone Equity",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "European Equity"


class TestAsianEquityAndEMDebt:
    def test_asian_equity_fund(self) -> None:
        result = classify_fund(
            fund_name="Matthews Asian Growth Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Asian Equity"

    def test_china_equity(self) -> None:
        result = classify_fund(
            fund_name="Invesco China Focus Equity Fund",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "Asian Equity"

    def test_japan_equity(self) -> None:
        result = classify_fund(
            fund_name="Fidelity Japan Smaller Companies",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "Asian Equity"

    def test_em_debt_fund(self) -> None:
        result = classify_fund(
            fund_name="PIMCO Emerging Markets Debt Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Emerging Markets Debt"

    def test_em_equity_still_works(self) -> None:
        """Round 1 regression: EM Equity patterns still work for equity names."""
        result = classify_fund(
            fund_name="DFA Emerging Markets Equity Portfolio",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Emerging Markets Equity"


class TestNoRegressions:
    """Ensure Round 1 + existing tests still pass."""

    def test_goldman_still_not_precious_metals(self) -> None:
        result = classify_fund(
            fund_name="GOLDMAN SACHS TRUST - LARGE CAP GROWTH FUND",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Growth"

    def test_credit_allocation_still_balanced(self) -> None:
        result = classify_fund(
            fund_name="Credit Allocation Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Balanced"

    def test_pe_secondaries_still_works(self) -> None:
        result = classify_fund(
            fund_name="Apollo Private Equity Secondaries Fund",
            fund_type="Private Equity Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Private Equity"
        assert "secondaries" in (result.matched_pattern or "")

    def test_structured_credit_still_works(self) -> None:
        result = classify_fund(
            fund_name="BATTALION CLO XVI",
            fund_type="Securitized Asset Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Structured Credit"

    def test_tax_free_still_municipal(self) -> None:
        result = classify_fund(
            fund_name="Franklin California Intermediate-Term Tax-Free Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Municipal Bond"

    def test_hedge_generic_fallback_preserved(self) -> None:
        result = classify_fund(
            fund_name="Generic Alpha Partners",
            fund_type="Hedge Fund",
            tiingo_description=None,
        )
        assert result.strategy_label in ("Multi-Strategy", "Hedge Fund")

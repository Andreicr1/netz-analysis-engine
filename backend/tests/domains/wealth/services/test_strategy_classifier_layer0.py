"""Layer 0 (N-PORT holdings) regression tests for the strategy classifier.

Pins the bug patterns Layer 0 must resolve, plus the false positives the
issuerCat-aware rewrite must avoid:

  - Vanguard Target Retirement 2055 → was Government Bond from regex on
    "2055"; Layer 0 sees ~88% equity → US Equity bucket (not a bond).
  - CAPITAL WORLD GROWTH & INCOME → was Intermediate-Term Bond from the
    "Income" keyword; Layer 0 sees ~95% equity → equity bucket.
  - RIVERVIEW GLOBAL MACRO → was International Equity from "Global"; Layer
    0 detects derivatives-heavy composition → Global Macro.
  - REIT funds → Real Estate from asset_class=RE (NOT from GICS sector).
  - Voya US Bond Index regression: must NOT classify as Sector Equity
    just because all equity holdings carry issuerCat=CORP. The previous
    GICS-assumption rule misfired on this. The new rule has no
    sector-equity bucket; equity-dominant funds get Large Blend or a
    geography-based label, never "Sector Equity".
  - Government / Municipal funds: must classify by issuerCat
    (UST/USGSE/USGA → Govt; MUN → Muni), not collapse to generic
    Intermediate-Term Bond.
"""
from __future__ import annotations

from datetime import date

from app.domains.wealth.services.holdings_analyzer import HoldingsAnalysis
from app.domains.wealth.services.strategy_classifier import classify_fund


def _ha(**kwargs) -> HoldingsAnalysis:
    """Build a HoldingsAnalysis with sensible defaults for tests."""
    defaults = dict(
        as_of_date=date(2026, 3, 31),
        n_holdings=200,
        total_nav_covered_pct=98.0,
        equity_pct=0.0, fixed_income_pct=0.0, cash_pct=0.0,
        derivatives_pct=0.0, other_pct=0.0,
        geography_us_pct=0.0, geography_europe_pct=0.0,
        geography_asia_developed_pct=0.0, geography_em_pct=0.0,
        geography_other_pct=0.0,
        coverage_quality="high",
    )
    defaults.update(kwargs)
    return HoldingsAnalysis(**defaults)


class TestRegressionBugPatterns:
    def test_target_date_2055_not_government_bond(self):
        """88% equity Target Retirement fund must NOT be a bond label."""
        h = _ha(
            equity_pct=88, fixed_income_pct=10, cash_pct=2,
            geography_us_pct=65, geography_europe_pct=15,
            geography_asia_developed_pct=10, geography_em_pct=8,
            geography_other_pct=2,
        )
        result = classify_fund(
            fund_name="Vanguard Target Retirement 2055",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label is not None
        assert "Bond" not in result.strategy_label
        assert "Government" not in result.strategy_label

    def test_equity_income_not_bond(self):
        """95% equity 'Growth & Income' fund must NOT be a bond label."""
        h = _ha(
            equity_pct=95, fixed_income_pct=3, cash_pct=2,
            geography_us_pct=55, geography_europe_pct=25,
            geography_asia_developed_pct=10, geography_em_pct=10,
        )
        result = classify_fund(
            fund_name="CAPITAL WORLD GROWTH & INCOME",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label is not None
        assert "Bond" not in result.strategy_label
        # 55% US, 45% non-US → falls through to Large Blend (no GICS, no MC).
        assert result.strategy_label == "Large Blend"
        assert result.source == "nport_holdings"

    def test_global_macro_from_derivatives(self):
        """Derivatives >60% with FX/IR mix → Global Macro."""
        h = _ha(
            equity_pct=5, fixed_income_pct=5, cash_pct=25,
            derivatives_pct=65,
            geography_us_pct=40, geography_europe_pct=20,
            geography_asia_developed_pct=10, geography_em_pct=15,
            geography_other_pct=15,
            derivatives_fx_pct=20, derivatives_ir_pct=20,
            derivatives_commodity_pct=10, derivatives_equity_pct=10,
            derivatives_credit_pct=5,
            non_usd_currency_pct=40,
        )
        result = classify_fund(
            fund_name="RIVERVIEW GLOBAL MACRO FUND",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Global Macro"
        assert result.source == "nport_holdings"
        assert result.matched_pattern == "holdings:global_macro"


class TestCorpFalsePositiveGuard:
    """The CORP/Sector-Equity false-positive bug found in the first run."""

    def test_voya_us_bond_index_does_not_become_sector_equity(self):
        """Voya US Bond Index in production has equity holdings tagged
        EC/CORP and Treasuries tagged DBT/UST. The OLD rule treated
        'CORP' as a GICS sector and produced 'Sector Equity'. The NEW
        rule has no GICS-sector bucket; this fund is FI-dominant via
        DBT/UST → Government Bond."""
        h = _ha(
            equity_pct=40,    # Apple/NVIDIA/Microsoft (EC/CORP)
            fixed_income_pct=58,
            cash_pct=2,
            fi_government_pct=58,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="Voya U.S. Bond Index Portfolio",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        # 60-40 split → Balanced is the correct Layer 0 read.
        # Critical: must NOT be "Sector Equity".
        assert result.strategy_label != "Sector Equity"
        assert result.strategy_label == "Balanced"

    def test_us_equity_dominant_lands_in_large_blend_not_sector(self):
        """100% EC/CORP equity sleeve must NOT trigger Sector Equity.
        Without GICS or market cap, Large Blend is the safest default."""
        h = _ha(
            equity_pct=98, cash_pct=2,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="NICHOLAS FUND INC",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label != "Sector Equity"
        assert result.strategy_label == "Large Blend"
        assert result.matched_pattern == "holdings:us_equity_generic"


class TestFixedIncomeSubtypeDispatch:
    def test_treasury_dominant_government_bond(self):
        h = _ha(
            fixed_income_pct=95, cash_pct=5,
            fi_government_pct=90,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="Vanguard Long-Term Treasury Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Government Bond"
        assert result.matched_pattern == "holdings:fi_government"

    def test_municipal_dominant_municipal_bond(self):
        h = _ha(
            fixed_income_pct=95, cash_pct=5,
            fi_municipal_pct=92,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="Western Asset California Municipals Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Municipal Bond"
        assert result.matched_pattern == "holdings:fi_municipal"

    def test_corporate_default_investment_grade(self):
        h = _ha(
            fixed_income_pct=95, cash_pct=5,
            fi_corporate_pct=80,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="Generic Corporate Bond Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Investment Grade Bond"
        assert result.matched_pattern == "holdings:fi_corporate_generic"

    def test_mbs_dominant_classifies_as_mbs(self):
        h = _ha(
            fixed_income_pct=92, cash_pct=8,
            fi_mbs_pct=85,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="Vanguard Mortgage-Backed Securities ETF",
            fund_type="ETF",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Mortgage-Backed Securities"
        assert result.matched_pattern == "holdings:fi_mbs"

    def test_em_debt_geography_overrides_subtype(self):
        h = _ha(
            fixed_income_pct=90, cash_pct=10,
            fi_government_pct=60,
            geography_em_pct=70, geography_us_pct=20,
            geography_europe_pct=10,
        )
        result = classify_fund(
            fund_name="Generic EM Debt",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Emerging Markets Debt"

    def test_european_bond_geography(self):
        h = _ha(
            fixed_income_pct=95, cash_pct=5,
            fi_government_pct=70,
            geography_europe_pct=70, geography_us_pct=30,
        )
        result = classify_fund(
            fund_name="Generic Eurozone Bond",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "European Bond"


class TestEquityGeographyAndREIT:
    def test_emerging_markets_equity(self):
        h = _ha(
            equity_pct=95, cash_pct=5,
            geography_em_pct=70, geography_us_pct=15,
            geography_europe_pct=10, geography_asia_developed_pct=5,
        )
        result = classify_fund(
            fund_name="Generic EM Equity",
            fund_type="ETF",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Emerging Markets Equity"

    def test_european_equity_geography(self):
        h = _ha(
            equity_pct=92, cash_pct=8,
            geography_europe_pct=80, geography_us_pct=10,
            geography_asia_developed_pct=10,
        )
        result = classify_fund(
            fund_name="Generic Europe Fund",
            fund_type="ETF",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "European Equity"

    def test_international_equity_when_non_us_dominant(self):
        h = _ha(
            equity_pct=95, cash_pct=5,
            geography_us_pct=20, geography_europe_pct=30,
            geography_asia_developed_pct=30, geography_em_pct=20,
        )
        result = classify_fund(
            fund_name="Generic International Equity",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "International Equity"

    def test_reit_dominant_real_estate(self):
        """REIT funds with asset_class=RE dominating equity sleeve."""
        h = _ha(
            equity_pct=95, cash_pct=5,
            equity_real_estate_pct=80,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="iShares US Real Estate ETF",
            fund_type="ETF",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Real Estate"
        assert result.matched_pattern == "holdings:reit_dominant"


class TestBalancedAndTargetDate:
    def test_balanced_60_40(self):
        h = _ha(
            equity_pct=60, fixed_income_pct=40,
            geography_us_pct=80, geography_europe_pct=20,
        )
        result = classify_fund(
            fund_name="Generic Balanced Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Balanced"

    def test_target_date_with_name_hint(self):
        h = _ha(
            equity_pct=55, fixed_income_pct=40, cash_pct=5,
            geography_us_pct=70, geography_europe_pct=20, geography_em_pct=10,
        )
        result = classify_fund(
            fund_name="Vanguard Target Retirement 2040",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Target Date"

    def test_cash_dominant(self):
        h = _ha(cash_pct=95, fixed_income_pct=5)
        result = classify_fund(
            fund_name="Some Money Market",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Cash Equivalent"


class TestCoverageQualityGate:
    def test_low_coverage_falls_through_to_tiingo(self):
        h = _ha(
            n_holdings=5, total_nav_covered_pct=40,
            equity_pct=95, fixed_income_pct=3, cash_pct=2,
            equity_real_estate_pct=80,
            geography_us_pct=100,
            coverage_quality="low",
        )
        result = classify_fund(
            fund_name="Generic Fund",
            fund_type="Mutual Fund",
            tiingo_description=(
                "The fund invests primarily in large cap growth stocks "
                "of US companies."
            ),
            holdings_analysis=h,
        )
        assert result.source == "tiingo_description"
        assert result.strategy_label == "Large Growth"

    def test_medium_coverage_still_fires_layer_0(self):
        h = _ha(
            total_nav_covered_pct=82,
            equity_pct=95, fixed_income_pct=3, cash_pct=2,
            equity_real_estate_pct=70,
            geography_us_pct=100,
            coverage_quality="medium",
        )
        result = classify_fund(
            fund_name="Some REIT Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.source == "nport_holdings"
        assert result.strategy_label == "Real Estate"

    def test_no_holdings_falls_through(self):
        result = classify_fund(
            fund_name="Vanguard 500 Index Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=None,
        )
        assert result.source in ("name_regex", "fallback")

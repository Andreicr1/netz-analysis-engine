"""Regression tests for Round 2.5 cascade classifier patches.

Three bug patterns were identified after applying P0+P1 of run b5623a5b
and sampling the residual P2 (asset_class_change) bucket:

    1. ``name:international`` over-fired on bond funds that mention
       "global" / "world" / "foreign" — moved bonds into International
       Equity.
    2. ``name:general_bond`` swallowed HY ("High Income") and IG ("IG
       Corporate") funds because the specific patterns didn't match
       the institutional shorthand.
    3. ``desc:mbs`` fired on funds that merely mention MBS in
       boilerplate "may also invest in" disclosures — money market,
       inflation-protected, and multi-asset funds were leaking into
       Mortgage-Backed Securities.

Each test below pins the specific real-world fund name from the sample
that exposed the bug, so a regression would clearly identify which
patch broke.
"""

from __future__ import annotations

from app.domains.wealth.services.strategy_classifier import classify_fund


class TestInternationalGuard:
    """name:international must not steal bond funds."""

    def test_global_ig_corporate_stays_bond(self) -> None:
        # Real run b5623a5b sample: was "Target Date" → "International Equity"
        result = classify_fund(
            fund_name="LOMBARD ODIER FUNDS-TARGETNETZERO GLOBAL IG CORPORATE",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "Investment Grade Bond"
        assert result.matched_pattern is not None
        assert "ig_bond" in result.matched_pattern

    def test_global_bond_stays_bond(self) -> None:
        result = classify_fund(
            fund_name="Lombard Odier Global Bond Fund",
            fund_type="UCITS",
            tiingo_description=None,
        )
        # Should NOT be International Equity; the bond keyword in the
        # name routes it to a bond bucket.
        assert result.strategy_label != "International Equity"

    def test_world_credit_fund_not_international_equity(self) -> None:
        result = classify_fund(
            fund_name="PIMCO World Credit Bond Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label != "International Equity"

    def test_pure_international_equity_still_works(self) -> None:
        # Make sure the guard doesn't break the happy path.
        result = classify_fund(
            fund_name="Vanguard International Stock Index Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "International Equity"


class TestEmergingMarketsDebt:
    """Relaxed EMD pattern catches bond funds tagged with just 'emerging'."""

    def test_emerging_value_bond_is_emd(self) -> None:
        # Real sample: was "EM Debt" → "Intermediate-Term Bond"
        result = classify_fund(
            fund_name="LOMBARD ODIER FUNDS-EMERGING VALUE BOND",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "Emerging Markets Debt"

    def test_emerging_markets_credit_is_emd(self) -> None:
        result = classify_fund(
            fund_name="Ashmore Emerging Markets Total Return Credit Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Emerging Markets Debt"

    def test_emerging_markets_equity_unaffected(self) -> None:
        result = classify_fund(
            fund_name="iShares MSCI Emerging Markets ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Emerging Markets Equity"


class TestHighYieldCoversHighIncome:
    """name:high_yield must catch the ubiquitous 'High Income' label."""

    def test_high_income_fund_is_high_yield(self) -> None:
        # Real samples: AB HIGH INCOME FUND, NICHOLAS HIGH INCOME,
        # Pioneer Diversified High Income, Eaton Vance High Income 2022
        # Target Term Trust — all were going to Intermediate-Term Bond.
        result = classify_fund(
            fund_name="AB HIGH INCOME FUND INC",
            fund_type="Closed-End Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "High Yield Bond"

    def test_diversified_high_income_is_hy(self) -> None:
        result = classify_fund(
            fund_name="Pioneer Diversified High Income Fund, Inc.",
            fund_type="Closed-End Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "High Yield Bond"

    def test_equity_income_not_hy(self) -> None:
        # "Equity Income" should NOT be classified as High Yield Bond —
        # the bond/income gate at name:general_bond filters out equity.
        result = classify_fund(
            fund_name="T. Rowe Price Equity Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label != "High Yield Bond"


class TestIGBondAbbreviation:
    """name:ig_bond must catch \\bIG\\b shorthand and bare 'corporate bond'."""

    def test_ig_bond_abbreviation(self) -> None:
        result = classify_fund(
            fund_name="iShares IG Bond ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Investment Grade Bond"

    def test_ig_corporate_abbreviation(self) -> None:
        result = classify_fund(
            fund_name="LOMBARD ODIER FUNDS-TARGETNETZERO GLOBAL IG CORPORATE",
            fund_type="UCITS",
            tiingo_description=None,
        )
        assert result.strategy_label == "Investment Grade Bond"

    def test_corporate_credit_fund_is_ig(self) -> None:
        result = classify_fund(
            fund_name="Vanguard Long-Term Corporate Bond Index Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Investment Grade Bond"


class TestMBSPrimaryFocus:
    """desc:mbs must require MBS to be a PRIMARY investment focus."""

    def test_money_market_with_secondary_mbs_mention(self) -> None:
        # Boilerplate "may also invest in mortgage-backed securities"
        # appearing 300+ chars in must NOT trigger desc:mbs.
        long_desc = (
            "The fund invests primarily in short-term money market "
            "instruments including commercial paper, Treasury bills, "
            "and certificates of deposit. The fund maintains a stable "
            "net asset value and seeks to preserve capital. "
            "The fund may also invest in mortgage-backed securities "
            "as a small portion of the portfolio for diversification."
        )
        result = classify_fund(
            fund_name="Scharf Global Opportunity Fund",
            fund_type="Mutual Fund",
            tiingo_description=long_desc,
        )
        assert result.strategy_label != "Mortgage-Backed Securities"

    def test_inflation_protected_with_secondary_mbs(self) -> None:
        long_desc = (
            "The fund seeks to provide inflation protection through "
            "investments in Treasury Inflation-Protected Securities "
            "and other inflation-linked instruments issued by the U.S. "
            "government. The portfolio may include mortgage-backed "
            "securities for incremental yield."
        )
        result = classify_fund(
            fund_name="Transamerica Inflation-Protected Securities",
            fund_type="Mutual Fund",
            tiingo_description=long_desc,
        )
        assert result.strategy_label != "Mortgage-Backed Securities"

    def test_primary_mbs_focus_still_classifies(self) -> None:
        # A real MBS fund mentions MBS at the top of the description.
        result = classify_fund(
            fund_name="PIMCO Mortgage-Backed Securities Fund",
            fund_type="Mutual Fund",
            tiingo_description=(
                "The fund invests primarily in mortgage-backed securities "
                "including agency and non-agency MBS, with a focus on "
                "high credit quality and intermediate duration."
            ),
        )
        assert result.strategy_label == "Mortgage-Backed Securities"

    def test_generic_securities_word_not_mbs(self) -> None:
        # Defensive: the word "securities" alone in description must
        # never trigger the MBS pattern.
        result = classify_fund(
            fund_name="ABC Money Market Securities Fund",
            fund_type="Mutual Fund",
            tiingo_description=(
                "Invests in short-term money market securities "
                "for liquidity and capital preservation."
            ),
        )
        assert result.strategy_label != "Mortgage-Backed Securities"

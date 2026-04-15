"""Layer 0 (N-PORT holdings) regression tests for the strategy classifier.

**Layer 0 scope is FI-only.** Equity-side classification is intentionally
deferred to Layer 1 (Tiingo description) and Layer 2 (name regex) until
Phase 4.5 lands the data we'd need to do it right (CUSIP→GICS,
per-holding country-of-domicile, market cap, credit rating, and a
trust-CIK fix in universe_sync). See the ``_classify_from_holdings``
docstring for the full rationale.

These tests pin:
  • The FI subtype dispatch (Government / Municipal / Corporate / MBS /
    ABS / EM Debt / European Bond) at the institutional-grade thresholds
    Andrei specified
  • The asset-mix gates (Cash, Balanced with real-FI, Target Date,
    Global Macro)
  • The deliberate equity-side abstention (equity-dominant funds MUST
    return source != "nport_holdings")
  • The original bug patterns from Round 1 (CORP false positive, trust-
    CIK aggregation, cash-buffer Balanced misfire)
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


# ───────────────────────────────────────────────────────────────────
# FI subtype dispatch — the heart of FI-only Layer 0
# ───────────────────────────────────────────────────────────────────


class TestFixedIncomeSubtypeDispatch:
    def test_government_bond_classification(self):
        """Treasury-dominant fund (UST + USGSE + USGA > 60% of NAV)."""
        h = _ha(
            fixed_income_pct=92, cash_pct=8,
            fi_government_pct=85,
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
        assert result.source == "nport_holdings"

    def test_municipal_bond_classification(self):
        """MUN issuerCat > 50% of NAV → Municipal Bond."""
        h = _ha(
            fixed_income_pct=95, cash_pct=5,
            fi_municipal_pct=88,
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

    def test_corporate_bond_classification(self):
        """CORP issuerCat on debt > 60% of NAV → Investment Grade Bond.
        HY/IG disambiguation deferred to Phase 4.5 (needs credit ratings)."""
        h = _ha(
            fixed_income_pct=92, cash_pct=8,
            fi_corporate_pct=80,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="Loomis Sayles Corporate Bond Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Investment Grade Bond"
        assert result.matched_pattern == "holdings:fi_corporate"

    def test_mbs_classification(self):
        """asset_class=ABS-MBS > 50% of NAV → MBS."""
        h = _ha(
            fixed_income_pct=92, cash_pct=8,
            fi_mbs_pct=80,
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

    def test_abs_classification(self):
        """asset_class ∈ ABS-O/CBDO/APCP > 50% of NAV → ABS."""
        h = _ha(
            fixed_income_pct=92, cash_pct=8,
            fi_abs_pct=70,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="Loomis Sayles Securitized Asset Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Asset-Backed Securities"
        assert result.matched_pattern == "holdings:fi_abs"

    def test_em_debt_from_fi_and_geography(self):
        """FI-dominant + geography_em > 40% → Emerging Markets Debt
        (geography overrides issuerCat for cross-border funds)."""
        h = _ha(
            fixed_income_pct=90, cash_pct=10,
            fi_government_pct=60,  # would otherwise be Govt Bond
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
        assert result.matched_pattern == "holdings:em_debt"

    def test_european_bond_from_fi_and_geography(self):
        """FI-dominant + geography_europe > 50% → European Bond."""
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
        assert result.matched_pattern == "holdings:european_bond"

    def test_fi_dominant_mixed_credit_falls_to_generic(self):
        """FI-dominant with no single subtype above threshold →
        Intermediate-Term Bond (generic neutral label)."""
        h = _ha(
            fixed_income_pct=92, cash_pct=8,
            fi_government_pct=30, fi_municipal_pct=10,
            fi_corporate_pct=40, fi_mbs_pct=10,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="Generic Multi-Sector Bond Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Intermediate-Term Bond"
        assert result.matched_pattern == "holdings:fi_generic"


# ───────────────────────────────────────────────────────────────────
# Asset-mix outer dispatch — Cash, Balanced, Target Date, Global Macro
# ───────────────────────────────────────────────────────────────────


class TestAssetMixDispatch:
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
        assert result.matched_pattern == "holdings:global_macro"

    def test_cash_dominant_money_market(self):
        h = _ha(cash_pct=95, fixed_income_pct=5)
        result = classify_fund(
            fund_name="Some Money Market",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Cash Equivalent"
        assert result.matched_pattern == "holdings:cash_dominant"

    def test_balanced_with_real_bonds(self):
        """60/40 with genuine bond sleeve (not cash buffer)."""
        h = _ha(
            equity_pct=60, fixed_income_pct=40,
            fi_government_pct=15, fi_corporate_pct=20, fi_mbs_pct=5,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="Vanguard Wellington Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Balanced"

    def test_target_date_with_name_hint_and_real_fi(self):
        h = _ha(
            equity_pct=55, fixed_income_pct=40, cash_pct=5,
            fi_government_pct=15, fi_corporate_pct=20, fi_mbs_pct=5,
            geography_us_pct=70, geography_europe_pct=20, geography_em_pct=10,
        )
        result = classify_fund(
            fund_name="Vanguard Target Retirement 2040",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.strategy_label == "Target Date"


# ───────────────────────────────────────────────────────────────────
# Bug-pattern guards — false positives that motivated the FI-only scope
# ───────────────────────────────────────────────────────────────────


class TestEquityFallsThrough:
    """Equity-dominant funds must always fall through to Layer 1/2.
    Layer 0 deliberately abstains because ISIN geography is fooled by
    ADRs, sector lacks GICS, market cap is missing, etc. (see module
    docstring)."""

    def test_us_equity_dominant_falls_through(self):
        h = _ha(equity_pct=98, cash_pct=2, geography_us_pct=100)
        result = classify_fund(
            fund_name="NICHOLAS FUND INC",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.source != "nport_holdings"

    def test_em_equity_falls_through(self):
        """Boston Partners Emerging Markets had Chinese ADRs with US ISIN
        in N-PORT → my prior gate flagged as US-dominant Large Blend.
        Now Layer 0 abstains; Layer 2 picks up 'Emerging Markets' from
        the fund name."""
        h = _ha(equity_pct=98, cash_pct=2, geography_us_pct=85,
                geography_em_pct=15)
        result = classify_fund(
            fund_name="Boston Partners Emerging Markets Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.source != "nport_holdings"

    def test_global_equity_falls_through(self):
        h = _ha(
            equity_pct=95, cash_pct=5,
            geography_us_pct=55, geography_europe_pct=25,
            geography_asia_developed_pct=10, geography_em_pct=10,
        )
        result = classify_fund(
            fund_name="Boston Partners Global Equity Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.source != "nport_holdings"


class TestRegressionGuards:
    def test_target_date_2055_does_not_become_government_bond(self):
        """The original Round-1 bug: regex on '2055' produced Government
        Bond. Layer 0 with 88% equity now correctly abstains; Layer 2
        catches 'Target Retirement' if regex permits."""
        h = _ha(
            equity_pct=88, fixed_income_pct=10, cash_pct=2,
            fi_corporate_pct=8,
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
        # Must not be a bond label (the original misfire).
        assert result.strategy_label is None or "Bond" not in result.strategy_label

    def test_corp_false_positive_eliminated(self):
        """100% EC/CORP equity sleeve must NOT trigger any holdings:sector_*
        pattern (CORP issuerCat is not GICS — Round-1 bug)."""
        h = _ha(equity_pct=100, geography_us_pct=100)
        result = classify_fund(
            fund_name="VALUE FUND",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        # Equity falls through — no holdings pattern of any kind.
        assert result.source != "nport_holdings"

    def test_equity_with_cash_buffer_not_balanced(self):
        """CALAMOS Global Total Return type: 65% equity + 35% cash/STIV
        with NO real bonds. Old gate flagged as Balanced; new gate
        rejects (real_fi == 0) and equity falls through."""
        h = _ha(
            equity_pct=65, fixed_income_pct=35,
            fi_government_pct=0, fi_municipal_pct=0,
            fi_corporate_pct=0, fi_mbs_pct=0,
            geography_us_pct=85, geography_europe_pct=15,
        )
        result = classify_fund(
            fund_name="Generic Total Return Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        # Not Balanced, not equity-classified by Layer 0.
        assert result.strategy_label != "Balanced"
        assert result.source != "nport_holdings"


class TestCoherenceAndCoverageGates:
    def test_three_dominant_buckets_abstains(self):
        """Trust-CIK aggregating equity+FI+cash sleeves all >30% must
        be rejected by the coherence gate before classification."""
        h = _ha(
            equity_pct=33, fixed_income_pct=33, cash_pct=34,
            fi_government_pct=30,
            geography_us_pct=100,
        )
        result = classify_fund(
            fund_name="T. Rowe Price Extended Equity Market Index Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=h,
        )
        assert result.source != "nport_holdings"

    def test_low_coverage_falls_through(self):
        h = _ha(
            n_holdings=5, total_nav_covered_pct=40,
            fixed_income_pct=95, fi_government_pct=80,
            geography_us_pct=100,
            coverage_quality="low",
        )
        result = classify_fund(
            fund_name="Generic Bond Fund",
            fund_type="Mutual Fund",
            tiingo_description=(
                "Invests primarily in long-term US Treasury securities."
            ),
            holdings_analysis=h,
        )
        # Layer 0 skipped due to low coverage; Layer 1 fires on description.
        assert result.source == "tiingo_description"

    def test_no_holdings_falls_through(self):
        result = classify_fund(
            fund_name="Vanguard 500 Index Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
            holdings_analysis=None,
        )
        assert result.source in ("name_regex", "fallback")

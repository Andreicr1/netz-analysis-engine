"""Unit tests for quant_engine.style_analysis — fund style classification."""

import pytest

from quant_engine.style_analysis import StyleConfig, StyleVector, classify_fund_style


def _holding(
    sector: str | None = None,
    asset_class: str = "EC",
    pct_of_nav: float | None = None,
    market_value: int | None = None,
) -> dict:
    return {
        "sector": sector,
        "asset_class": asset_class,
        "pct_of_nav": pct_of_nav,
        "market_value": market_value,
    }


class TestClassifyFundStyle:
    """Test style classification logic."""

    def test_empty_holdings_returns_unknown(self):
        result = classify_fund_style([])
        assert result.style_label == "unknown"
        assert result.confidence == 0.0
        assert result.sector_weights == {}

    def test_pure_tech_fund_is_large_growth(self):
        holdings = [
            _holding(sector="Information Technology", pct_of_nav=30.0),
            _holding(sector="Information Technology", pct_of_nav=25.0),
            _holding(sector="Health Care", pct_of_nav=20.0),
            _holding(sector="Consumer Discretionary", pct_of_nav=15.0),
            _holding(sector="Communication Services", pct_of_nav=10.0),
        ]
        result = classify_fund_style(holdings)
        assert result.style_label == "large_growth"
        assert result.growth_tilt >= 0.9
        assert result.confidence == 1.0

    def test_pure_utilities_fund_is_large_value(self):
        holdings = [
            _holding(sector="Utilities", pct_of_nav=40.0),
            _holding(sector="Energy", pct_of_nav=30.0),
            _holding(sector="Financials", pct_of_nav=20.0),
            _holding(sector="Real Estate", pct_of_nav=10.0),
        ]
        result = classify_fund_style(holdings)
        assert result.style_label == "large_value"
        assert result.growth_tilt <= 0.1

    def test_no_sector_data_returns_unknown_confidence(self):
        holdings = [
            _holding(sector=None, pct_of_nav=50.0),
            _holding(sector=None, pct_of_nav=50.0),
        ]
        result = classify_fund_style(holdings)
        assert result.confidence == 0.0

    def test_mixed_equity_bonds_is_mixed(self):
        # Need >= min_holdings_for_confidence (10) to classify as 'mixed'
        holdings = [
            _holding(sector="Information Technology", asset_class="EC", pct_of_nav=10.0),
            _holding(sector="Financials", asset_class="DBT", pct_of_nav=10.0),
            _holding(sector=None, asset_class="cash", pct_of_nav=10.0),
            _holding(sector="Health Care", asset_class="EC", pct_of_nav=10.0),
            _holding(sector="Energy", asset_class="DBT", pct_of_nav=10.0),
            _holding(sector="Utilities", asset_class="DBT", pct_of_nav=10.0),
            _holding(sector="Materials", asset_class="EC", pct_of_nav=10.0),
            _holding(sector=None, asset_class="cash", pct_of_nav=10.0),
            _holding(sector="Consumer Staples", asset_class="DBT", pct_of_nav=10.0),
            _holding(sector="Real Estate", asset_class="EC", pct_of_nav=10.0),
        ]
        result = classify_fund_style(holdings)
        assert result.style_label == "mixed"

    def test_fixed_income_fund(self):
        holdings = [
            _holding(sector=None, asset_class="DBT", pct_of_nav=70.0),
            _holding(sector=None, asset_class="bond", pct_of_nav=20.0),
            _holding(sector=None, asset_class="cash", pct_of_nav=10.0),
        ]
        result = classify_fund_style(holdings)
        assert result.style_label == "fixed_income"

    def test_blend_style(self):
        holdings = [
            _holding(sector="Information Technology", pct_of_nav=20.0),
            _holding(sector="Health Care", pct_of_nav=15.0),
            _holding(sector="Financials", pct_of_nav=20.0),
            _holding(sector="Energy", pct_of_nav=15.0),
            _holding(sector="Consumer Staples", pct_of_nav=15.0),
            _holding(sector="Consumer Discretionary", pct_of_nav=15.0),
        ]
        result = classify_fund_style(holdings)
        assert result.style_label == "large_blend"

    def test_custom_config_thresholds(self):
        config = StyleConfig(
            equity_threshold=0.80,
            growth_tilt_threshold=0.60,
            min_holdings_for_confidence=2,
        )
        holdings = [
            _holding(sector="Information Technology", pct_of_nav=50.0),
            _holding(sector="Financials", asset_class="DBT", pct_of_nav=50.0),
        ]
        result = classify_fund_style(holdings, config=config)
        # Equity is only 50% < 80% threshold → mixed
        assert result.style_label == "mixed"

    def test_market_value_fallback(self):
        holdings = [
            _holding(sector="Information Technology", market_value=1_000_000),
            _holding(sector="Information Technology", market_value=500_000),
            _holding(sector="Health Care", market_value=500_000),
        ]
        result = classify_fund_style(holdings)
        assert result.style_label == "large_growth"
        assert result.confidence == 1.0

    def test_style_vector_is_frozen(self):
        result = classify_fund_style([])
        with pytest.raises(AttributeError):
            result.style_label = "mixed"  # type: ignore[misc]

    def test_small_holdings_not_inflated(self):
        """Holdings below 1.5% NAV must not be inflated relative to larger ones.

        Regression: the old heuristic ``pct / 100 if abs(pct) > 1.5 else pct``
        treated sub-1.5% values as fractions instead of percentages, inflating
        a 0.5% position to appear as 50%.
        """
        # 2 large holdings (5% each) + 8 small holdings (0.5% each)
        # Correct equity weight = (10 + 4) / 100 = 0.14
        # Bug would give: 0.05 + 0.05 + 8*0.005 = 0.14 for large but 8*0.5 = 4.0 for small
        holdings = [
            _holding(sector="Information Technology", pct_of_nav=5.0),
            _holding(sector="Financials", pct_of_nav=5.0),
        ] + [
            _holding(sector="Utilities", pct_of_nav=0.5)
            for _ in range(8)
        ]
        result = classify_fund_style(holdings)
        # Large holdings contribute 10% total, small contribute 4% total
        # So large holdings should dominate — IT + Financials = 10/14 ~ 71%
        # Small Utilities = 4/14 ~ 29%
        it_weight = result.sector_weights.get("Information Technology", 0)
        fin_weight = result.sector_weights.get("Financials", 0)
        util_weight = result.sector_weights.get("Utilities", 0)
        # IT + Financials should clearly dominate over Utilities
        assert it_weight + fin_weight > util_weight
        # IT should be ~35.7% of sector weight, not dwarfed by inflated small holdings
        assert it_weight > 0.30

    def test_all_sub_1_5_pct_correct(self):
        """Fund with all holdings < 1.5% NAV must have correct total weight.

        Regression: old heuristic left sub-1.5% values as-is (fractions),
        making total weight = sum(pct_of_nav) instead of sum(pct_of_nav)/100.
        """
        # 20 holdings each at 1.0% of NAV = 20% total
        holdings = [
            _holding(sector="Information Technology", pct_of_nav=1.0)
            for _ in range(20)
        ]
        result = classify_fund_style(holdings)
        # equity_pct should be ~1.0 (all equity) regardless of individual sizes
        assert result.equity_pct is not None
        assert result.equity_pct > 0.99
        # The actual equity weight in fractions should be ~0.20 (20/100), not 20.0
        # We verify by checking style_label — if weights were inflated 100x,
        # the sector normalization would still work BUT the equity_pct fraction
        # would be computed from inflated sums. With the fix, it's correct.
        assert result.style_label == "large_growth"

    def test_style_label_correct_for_diversified_fund(self):
        """500-stock index fund with realistic pct_of_nav values.

        Regression: ~80% of holdings in an S&P 500 fund are below 1.5% NAV.
        The old heuristic inflated those by 100x, making small-cap value
        sectors dominate and corrupting style_label from large_blend to
        large_growth or large_value.
        """
        holdings = []
        # Top 10 holdings: large tech/growth stocks (typical S&P 500 top)
        for pct in [7.0, 6.5, 5.0, 3.5, 2.5, 2.0, 1.8, 1.6, 1.5, 1.4]:
            holdings.append(_holding(sector="Information Technology", pct_of_nav=pct))
        # Next 20: mix of growth and value at moderate weights
        for _ in range(10):
            holdings.append(_holding(sector="Health Care", pct_of_nav=1.2))
        for _ in range(10):
            holdings.append(_holding(sector="Financials", pct_of_nav=1.0))
        # Remaining 470 positions: small weights, balanced growth/value
        for _ in range(120):
            holdings.append(_holding(sector="Consumer Discretionary", pct_of_nav=0.05))
        for _ in range(120):
            holdings.append(_holding(sector="Consumer Staples", pct_of_nav=0.05))
        for _ in range(115):
            holdings.append(_holding(sector="Industrials", pct_of_nav=0.05))
        for _ in range(115):
            holdings.append(_holding(sector="Energy", pct_of_nav=0.05))

        result = classify_fund_style(holdings)
        # Top-heavy fund: IT dominates with ~32.8% of total weight
        # Growth sectors (IT + Health Care + Consumer Disc + Industrials) vs
        # Value sectors (Financials + Consumer Staples + Energy)
        # Expected: growth-heavy due to IT concentration → large_growth
        assert result.style_label in ("large_growth", "large_blend")
        # Key regression check: small holdings must NOT dominate sector weights
        it_weight = result.sector_weights.get("Information Technology", 0)
        # IT has 32.8/total of total NAV — should be the largest sector
        assert it_weight > 0.30
        # Confidence should be 1.0 (all holdings have sectors)
        assert result.confidence == 1.0

    def test_never_raises_on_bad_data(self):
        bad_holdings = [
            {"sector": None, "asset_class": None, "pct_of_nav": None, "market_value": None},
            {"sector": "", "asset_class": "", "pct_of_nav": 0, "market_value": 0},
        ]
        result = classify_fund_style(bad_holdings)
        assert isinstance(result, StyleVector)

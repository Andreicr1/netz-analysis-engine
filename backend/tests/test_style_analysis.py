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

    def test_never_raises_on_bad_data(self):
        bad_holdings = [
            {"sector": None, "asset_class": None, "pct_of_nav": None, "market_value": None},
            {"sector": "", "asset_class": "", "pct_of_nav": 0, "market_value": 0},
        ]
        result = classify_fund_style(bad_holdings)
        assert isinstance(result, StyleVector)

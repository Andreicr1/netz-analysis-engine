"""Regression tests for the cascade strategy classifier.

Each ``TestNameBugFixes`` case pins a previously-observed misclassification
so the legacy bug never reappears. ``TestTiingoDescriptionLayer`` and
``TestCascadePriority`` cover the new Layer 1 (Tiingo description) and the
priority rules between Layers 1 and 2.
"""

from __future__ import annotations

from app.domains.wealth.services.strategy_classifier import classify_fund

# ───────────────────────────────────────────────────────────────────
# Legacy name-regex bugs — each test pins a confirmed misclassification.
# ───────────────────────────────────────────────────────────────────

class TestNameBugFixes:
    def test_goldman_is_not_precious_metals(self) -> None:
        """``Goldman`` must not trigger the ``gold`` Precious Metals pattern."""
        result = classify_fund(
            fund_name="GOLDMAN SACHS TRUST - LARGE CAP GROWTH FUND",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Large Growth"
        assert result.source == "name_regex"

    def test_ishares_mortgage_real_estate(self) -> None:
        """Real Estate must beat Fixed Income for "Mortgage Real Estate" ETFs."""
        result = classify_fund(
            fund_name="iShares Mortgage Real Estate ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"

    def test_columbia_research_enhanced_real_estate(self) -> None:
        """Real Estate must beat Municipal Bond for Real Estate ETFs."""
        result = classify_fund(
            fund_name="Columbia Research Enhanced Real Estate ETF",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"

    def test_proshares_short_real_estate(self) -> None:
        """Short/Inverse ETF: keep Real Estate as asset class, tag direction in lineage."""
        result = classify_fund(
            fund_name="ProShares Short Real Estate",
            fund_type="ETF",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"
        assert "short" in (result.matched_pattern or "")

    def test_pgim_real_estate_income(self) -> None:
        """Real Estate must beat the generic ``income`` → Bond fallback."""
        result = classify_fund(
            fund_name="PGIM Real Estate Income Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Real Estate"

    def test_credit_allocation_is_balanced(self) -> None:
        """Name with ``allocation`` is a balanced fund regardless of other words."""
        result = classify_fund(
            fund_name="Credit Allocation Fund",
            fund_type="Mutual Fund",
            tiingo_description=None,
        )
        assert result.strategy_label == "Balanced"

    def test_aqr_convertible_without_hedge_type(self) -> None:
        """``Convertible`` alone is not arb — needs ``hedge`` in fund_type."""
        result = classify_fund(
            fund_name="AQR INNOVATION FUND - SERIES 31 CONVERTIBLE OPPORTUNITIES",
            fund_type="Mutual Fund",  # NOT a hedge fund
            tiingo_description=None,
        )
        assert result.strategy_label != "Convertible Arbitrage"


# ───────────────────────────────────────────────────────────────────
# Layer 1 — Tiingo description
# ───────────────────────────────────────────────────────────────────

class TestTiingoDescriptionLayer:
    def test_balanced_60_40_from_description(self) -> None:
        """Explicit asset composition in prose is a strong Balanced signal."""
        result = classify_fund(
            fund_name="Voya Balanced Income",
            fund_type="Mutual Fund",
            tiingo_description=(
                "invests approximately 60% of its assets in debt instruments "
                "and approximately 40% of its assets in equity securities"
            ),
        )
        assert result.strategy_label == "Balanced"
        assert result.source == "tiingo_description"

    def test_precious_metals_from_description(self) -> None:
        """Description mentioning gold mining / precious metals wins over name."""
        result = classify_fund(
            fund_name="World Something Fund",
            fund_type="Mutual Fund",
            tiingo_description=(
                "invests primarily in gold mining companies and precious metals producers"
            ),
        )
        assert result.strategy_label == "Precious Metals"
        assert result.source == "tiingo_description"

    def test_real_estate_from_description(self) -> None:
        """Description mentioning real estate securities classifies regardless of name."""
        result = classify_fund(
            fund_name="Generic Equity Fund",
            fund_type="Mutual Fund",
            tiingo_description=(
                "invests in publicly traded real estate securities using price-to-NAV "
                "and cash flow multiple ratios"
            ),
        )
        assert result.strategy_label == "Real Estate"
        assert result.source == "tiingo_description"

    def test_description_overrides_name(self) -> None:
        """Even when the name is ambiguous, a clear description wins."""
        result = classify_fund(
            fund_name="Cohen & Steers Realty Shares",
            fund_type="Mutual Fund",
            tiingo_description=(
                "bottom-up, relative value investment process when selecting "
                "publicly traded real estate securities"
            ),
        )
        assert result.strategy_label == "Real Estate"
        assert result.source == "tiingo_description"


# ───────────────────────────────────────────────────────────────────
# Cascade priority — description vs name
# ───────────────────────────────────────────────────────────────────

class TestCascadePriority:
    def test_description_beats_name(self) -> None:
        """If Tiingo description is available and classifies, it wins."""
        result = classify_fund(
            fund_name="Generic Growth Fund",
            fund_type="ETF",
            tiingo_description=(
                "invests primarily in gold mining companies and related equities"
            ),
        )
        assert result.source == "tiingo_description"
        assert result.strategy_label == "Precious Metals"

    def test_fallback_to_name_when_description_weak(self) -> None:
        """Descriptions below the min-length threshold are ignored."""
        result = classify_fund(
            fund_name="Vanguard Large-Cap Growth ETF",
            fund_type="ETF",
            tiingo_description="short",  # Too short to trust
        )
        assert result.source == "name_regex"
        assert result.strategy_label == "Large Growth"

    def test_fallback_when_nothing_matches(self) -> None:
        """Unclassifiable fund → source=fallback, label=None."""
        result = classify_fund(
            fund_name="XYZ Opaque Vehicle",
            fund_type=None,
            tiingo_description=None,
        )
        assert result.source == "fallback"
        assert result.strategy_label is None

"""Tests for Alternatives scoring dispatch in scoring_service.py.

Covers:
1. All 6 profile weight dicts sum to 1.0
2. REIT profile: income_generation + diversification dominate
3. Commodity profile: inflation_hedge dominates
4. Gold profile: crisis_alpha + diversification dominate
5. Hedge fund profile: alpha_generation dominates
6. CTA profile: crisis_alpha dominates (0.40 weight)
7. Generic alt profile: balanced weights
8. Dispatch in compute_fund_score routes to alternatives
9. Missing alt_metrics falls back to equity
10. resolve_alt_profile_weights with config override
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from quant_engine.scoring_service import (
    _ALT_PROFILE_WEIGHTS,
    _DEFAULT_ALT_COMMODITY_WEIGHTS,
    _DEFAULT_ALT_CTA_WEIGHTS,
    _DEFAULT_ALT_GENERIC_WEIGHTS,
    _DEFAULT_ALT_GOLD_WEIGHTS,
    _DEFAULT_ALT_HEDGE_WEIGHTS,
    _DEFAULT_ALT_REIT_WEIGHTS,
    compute_fund_score,
    resolve_alt_profile_weights,
)


def _make_equity_metrics(
    return_1y: float | None = 0.10,
    sharpe_1y: float | None = 1.2,
    max_drawdown_1y: float | None = -0.08,
    information_ratio_1y: float | None = 0.6,
) -> MagicMock:
    m = MagicMock()
    m.return_1y = return_1y
    m.sharpe_1y = sharpe_1y
    m.max_drawdown_1y = max_drawdown_1y
    m.information_ratio_1y = information_ratio_1y
    return m


def _make_alt_metrics(
    equity_correlation_252d: float | None = 0.2,
    downside_capture_1y: float | None = 0.5,
    upside_capture_1y: float | None = 0.7,
    crisis_alpha_score: float | None = 0.08,
    calmar_ratio_3y: float | None = 1.2,
    sortino_1y: float | None = 1.5,
    inflation_beta: float | None = 1.8,
    yield_proxy_12m: float | None = 0.06,
    tracking_error_1y: float | None = 0.02,
) -> MagicMock:
    m = MagicMock()
    m.equity_correlation_252d = equity_correlation_252d
    m.downside_capture_1y = downside_capture_1y
    m.upside_capture_1y = upside_capture_1y
    m.crisis_alpha_score = crisis_alpha_score
    m.calmar_ratio_3y = calmar_ratio_3y
    m.sortino_1y = sortino_1y
    m.inflation_beta = inflation_beta
    m.yield_proxy_12m = yield_proxy_12m
    m.tracking_error_1y = tracking_error_1y
    return m


class TestProfileWeightsSumToOne:
    """Every profile weight dict must sum to 1.0."""

    @pytest.mark.parametrize("profile,weights", [
        ("reit", _DEFAULT_ALT_REIT_WEIGHTS),
        ("commodity", _DEFAULT_ALT_COMMODITY_WEIGHTS),
        ("gold", _DEFAULT_ALT_GOLD_WEIGHTS),
        ("hedge", _DEFAULT_ALT_HEDGE_WEIGHTS),
        ("cta", _DEFAULT_ALT_CTA_WEIGHTS),
        ("generic_alt", _DEFAULT_ALT_GENERIC_WEIGHTS),
    ])
    def test_weights_sum(self, profile: str, weights: dict[str, float]) -> None:
        total = sum(weights.values())
        assert abs(total - 1.0) < 0.001, f"{profile} weights sum to {total}, should be 1.0"

    def test_all_profiles_registered(self) -> None:
        assert set(_ALT_PROFILE_WEIGHTS.keys()) == {
            "reit", "commodity", "gold", "hedge", "cta", "generic_alt",
        }


class TestREITProfile:
    """REIT profile: income_generation (0.25) + diversification_value (0.25) dominate."""

    def test_reit_scores_income_fund_high(self) -> None:
        risk = _make_equity_metrics()
        alt = _make_alt_metrics(
            yield_proxy_12m=0.08,          # High yield (REIT)
            equity_correlation_252d=0.3,    # Moderate diversification
            downside_capture_1y=0.6,        # Good protection
            inflation_beta=2.0,             # Good inflation hedge
        )
        score, components = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="reit",
            expense_ratio_pct=0.005,
        )
        assert "income_generation" in components
        assert "diversification_value" in components
        assert score > 50, f"Good REIT should score > 50, got {score}"


class TestCommodityProfile:
    """Commodity profile: inflation_hedge (0.30) dominates."""

    def test_commodity_scores_inflation_hedge_high(self) -> None:
        risk = _make_equity_metrics()
        alt = _make_alt_metrics(
            inflation_beta=3.0,             # Strong inflation hedge
            equity_correlation_252d=0.1,    # Low equity correlation
            crisis_alpha_score=0.15,        # Positive crisis alpha
            calmar_ratio_3y=1.0,            # Decent Calmar
        )
        score, components = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="commodity",
            expense_ratio_pct=0.005,
        )
        assert "inflation_hedge" in components
        assert components["inflation_hedge"] > 70, "Strong inflation hedge should score > 70"
        assert score > 55, f"Good commodity fund should score > 55, got {score}"


class TestGoldProfile:
    """Gold profile: crisis_alpha (0.30) + diversification_value (0.30) dominate."""

    def test_gold_scores_crisis_hedge_high(self) -> None:
        risk = _make_equity_metrics()
        alt = _make_alt_metrics(
            crisis_alpha_score=0.20,        # Strong crisis alpha
            equity_correlation_252d=0.05,   # Near-zero equity correlation
            inflation_beta=1.5,             # Moderate inflation hedge
            tracking_error_1y=0.01,         # Low tracking error vs GLD
        )
        score, components = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="gold",
            expense_ratio_pct=0.004,
        )
        assert "crisis_alpha" in components
        assert "tracking_efficiency" in components
        assert score > 60, f"Good gold fund should score > 60, got {score}"


class TestHedgeFundProfile:
    """Hedge fund profile: alpha_generation (0.30) dominates."""

    def test_hedge_fund_scores_alpha_high(self) -> None:
        risk = _make_equity_metrics()
        alt = _make_alt_metrics(
            sortino_1y=2.5,                 # Strong risk-adjusted returns
            downside_capture_1y=0.3,        # Excellent downside protection
            equity_correlation_252d=0.3,    # Low-moderate correlation
            crisis_alpha_score=0.10,        # Positive crisis alpha
        )
        score, components = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="hedge",
            expense_ratio_pct=0.020,  # 2% management fee typical for HFs
        )
        assert "alpha_generation" in components
        assert "downside_protection" in components
        assert components["alpha_generation"] > 70, "Strong Sortino should produce high alpha_generation"
        assert score > 50, f"Good hedge fund should score > 50, got {score}"


class TestCTAProfile:
    """CTA profile: crisis_alpha (0.40) dominates."""

    def test_cta_scores_crisis_alpha_high(self) -> None:
        risk = _make_equity_metrics()
        alt = _make_alt_metrics(
            crisis_alpha_score=0.25,        # Excellent crisis performance
            equity_correlation_252d=-0.1,   # Negative correlation (ideal for CTA)
            calmar_ratio_3y=1.5,            # Good risk-adjusted return
        )
        score, components = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="cta",
            expense_ratio_pct=0.015,
        )
        assert "crisis_alpha" in components
        assert _DEFAULT_ALT_CTA_WEIGHTS["crisis_alpha"] == 0.40
        assert score > 55, f"Good CTA should score > 55, got {score}"


class TestGenericAltProfile:
    """Generic alt profile: balanced diversification_value (0.30) + downside_protection (0.25)."""

    def test_generic_scores_balanced(self) -> None:
        risk = _make_equity_metrics()
        alt = _make_alt_metrics()
        score, components = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="generic_alt",
        )
        assert isinstance(score, float)
        assert "diversification_value" in components
        assert "downside_protection" in components
        assert "crisis_alpha" in components


class TestAlternativesDispatch:
    """Test compute_fund_score dispatches to alternatives path."""

    def test_dispatch_produces_alt_components(self) -> None:
        risk = _make_equity_metrics()
        alt = _make_alt_metrics()
        score, components = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt,
        )
        assert "diversification_value" in components
        assert "return_consistency" not in components, "Should NOT use equity components"
        assert "yield_consistency" not in components, "Should NOT use FI components"
        assert "yield_vs_risk_free" not in components, "Should NOT use cash components"

    def test_fallback_to_equity_if_no_alt_metrics(self) -> None:
        risk = _make_equity_metrics()
        score, components = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=None,
        )
        assert "return_consistency" in components, "Should fall back to equity"
        assert "diversification_value" not in components

    def test_default_profile_is_generic(self) -> None:
        risk = _make_equity_metrics()
        alt = _make_alt_metrics()
        # No alt_profile specified => generic_alt
        score_default, _ = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt,
        )
        score_explicit, _ = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="generic_alt",
        )
        assert score_default == score_explicit


class TestResolveAltProfileWeights:
    def test_known_profile(self) -> None:
        weights = resolve_alt_profile_weights("reit")
        assert weights == _DEFAULT_ALT_REIT_WEIGHTS

    def test_unknown_profile_falls_back_to_generic(self) -> None:
        weights = resolve_alt_profile_weights("nonexistent_profile")
        assert weights == _DEFAULT_ALT_GENERIC_WEIGHTS

    def test_config_override(self) -> None:
        custom = {"scoring_weights": {"crisis_alpha": 1.0}}
        weights = resolve_alt_profile_weights("reit", config=custom)
        assert weights == {"crisis_alpha": 1.0}


class TestAlternativesVsEquityScoring:
    """The credibility test: alt fund with diversification should score better
    on the alternatives model than on the equity model."""

    def test_alt_fund_scores_higher_on_alt_model(self) -> None:
        risk = _make_equity_metrics(
            return_1y=0.06,     # Modest return (typical for alternatives)
            sharpe_1y=0.7,      # Decent but not equity-level
            max_drawdown_1y=-0.08,
            information_ratio_1y=0.2,
        )
        alt = _make_alt_metrics(
            equity_correlation_252d=0.1,    # Great diversification
            downside_capture_1y=0.3,        # Excellent downside protection
            crisis_alpha_score=0.15,        # Positive crisis alpha
            calmar_ratio_3y=1.5,            # Strong risk-adjusted return
            sortino_1y=1.8,                 # Good Sortino
            inflation_beta=2.0,             # Good inflation hedge
        )

        equity_score, _ = compute_fund_score(
            risk, asset_class="equity", expense_ratio_pct=0.010,
        )
        alt_score, _ = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="hedge",
            expense_ratio_pct=0.010,
        )

        assert alt_score > equity_score, (
            f"Alt model should score higher than equity model for a skilled alternatives fund. "
            f"Alt={alt_score}, Equity={equity_score}"
        )

    def test_missing_data_penalty_applied(self) -> None:
        """Alt fund with all None metrics gets penalized."""
        risk = _make_equity_metrics()
        alt = _make_alt_metrics(
            equity_correlation_252d=None,
            downside_capture_1y=None,
            upside_capture_1y=None,
            crisis_alpha_score=None,
            calmar_ratio_3y=None,
            sortino_1y=None,
            inflation_beta=None,
            yield_proxy_12m=None,
            tracking_error_1y=None,
        )
        score, components = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt,
        )
        # Most components should get the 45-5=40 penalty
        assert score < 50, f"All-None alt fund should score < 50, got {score}"

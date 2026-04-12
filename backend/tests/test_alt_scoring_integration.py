"""E2E integration tests for Alternatives scoring pipeline (Sprint 3).

Tests the full chain: worker Pass 1.78 → _score_metrics → profile resolution → scoring.
Validates that alternatives funds are scored using the correct model/profile, not equity.

Covers:
1. Worker pass computes alt metrics and stores correct scoring_model
2. _score_metrics dispatches to alternatives with profile resolution
3. REIT fund: profile-specific scoring vs equity model
4. Commodity fund: inflation_hedge component recognized
5. CTA fund: crisis_alpha component dominates (0.40 weight)
6. ELITE validation: all 4 scoring_models present
7. Block-to-profile resolution
8. Strategy-label-to-profile resolution (global worker path)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from quant_engine.scoring_service import (
    _DEFAULT_ALT_CTA_WEIGHTS,
    _DEFAULT_ALT_REIT_WEIGHTS,
    compute_fund_score,
)

# ── Helpers ──────────────────────────────────────────────────────────


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


# ── Worker Pass Integration (via _score_metrics) ────────────────────


class TestWorkerScoreMetricsIntegration:
    """Test _score_metrics with alternatives dispatch (mirrors worker behavior)."""

    def test_alt_fund_scored_as_alternatives(self) -> None:
        """_score_metrics produces scoring_model=alternatives + alt components."""
        from app.domains.wealth.workers.risk_calc import _score_metrics

        metrics: dict = {
            "return_1y": 0.06,
            "sharpe_1y": 0.7,
            "max_drawdown_1y": -0.08,
            "information_ratio_1y": 0.2,
            "blended_momentum_score": 50.0,
            "scoring_model": "alternatives",
            # Alt analytics columns
            "equity_correlation_252d": 0.15,
            "downside_capture_1y": 0.4,
            "upside_capture_1y": 0.7,
            "crisis_alpha_score": 0.12,
            "calmar_ratio_3y": 1.3,
            "sortino_1y": 1.8,
            "inflation_beta": 2.1,
            "yield_proxy_12m": 0.05,
            "tracking_error_1y": 0.015,
        }
        _score_metrics(
            metrics,
            asset_class="alternatives",
            block_id="alt_real_estate",
        )
        assert "manager_score" in metrics
        assert metrics["manager_score"] > 0
        assert "score_components" in metrics
        comps = metrics["score_components"]
        # Should have alternatives components, not equity
        assert "diversification_value" in comps or "income_generation" in comps
        assert "return_consistency" not in comps
        # Profile stored for frontend
        assert comps.get("_alt_profile") == "reit"

    def test_alt_fund_via_strategy_label(self) -> None:
        """Global worker path: resolve profile from strategy_label."""
        from app.domains.wealth.workers.risk_calc import _score_metrics

        metrics: dict = {
            "return_1y": 0.08,
            "sharpe_1y": 0.9,
            "max_drawdown_1y": -0.10,
            "information_ratio_1y": 0.3,
            "blended_momentum_score": 50.0,
            "scoring_model": "alternatives",
            "equity_correlation_252d": -0.05,
            "downside_capture_1y": 0.3,
            "upside_capture_1y": 0.6,
            "crisis_alpha_score": 0.20,
            "calmar_ratio_3y": 1.5,
            "sortino_1y": 2.0,
            "inflation_beta": 0.5,
            "yield_proxy_12m": None,
            "tracking_error_1y": None,
        }
        _score_metrics(
            metrics,
            asset_class="alternatives",
            strategy_label="Managed Futures",
        )
        comps = metrics["score_components"]
        assert comps.get("_alt_profile") == "cta"
        assert "crisis_alpha" in comps
        assert metrics["manager_score"] > 0

    def test_equity_fund_unchanged(self) -> None:
        """Equity funds should not be affected by the new alt path."""
        from app.domains.wealth.workers.risk_calc import _score_metrics

        metrics: dict = {
            "return_1y": 0.15,
            "sharpe_1y": 1.5,
            "max_drawdown_1y": -0.12,
            "information_ratio_1y": 0.8,
            "blended_momentum_score": 60.0,
        }
        _score_metrics(metrics, asset_class="equity")
        assert "score_components" in metrics
        comps = metrics["score_components"]
        assert "return_consistency" in comps
        assert "diversification_value" not in comps
        assert "_alt_profile" not in comps


# ── Profile Resolution ───────────────────────────────────────────────


class TestAltProfileResolution:
    """Test block_id → profile and strategy_label → profile resolution."""

    def test_block_to_profile_mapping(self) -> None:
        from app.domains.wealth.workers.risk_calc import _resolve_alt_profile

        assert _resolve_alt_profile("alt_real_estate") == "reit"
        assert _resolve_alt_profile("alt_commodities") == "commodity"
        assert _resolve_alt_profile("alt_gold") == "gold"
        assert _resolve_alt_profile("alt_hedge_fund") == "hedge"
        assert _resolve_alt_profile("alt_managed_futures") == "cta"
        assert _resolve_alt_profile(None) == "generic_alt"
        assert _resolve_alt_profile("na_equity_large") == "generic_alt"

    def test_strategy_label_to_profile(self) -> None:
        from app.domains.wealth.workers.risk_calc import _resolve_alt_profile_from_strategy

        assert _resolve_alt_profile_from_strategy("Real Estate") == "reit"
        assert _resolve_alt_profile_from_strategy("Commodities Broad Basket") == "commodity"
        assert _resolve_alt_profile_from_strategy("Precious Metals") == "gold"
        assert _resolve_alt_profile_from_strategy("Long/Short Equity") == "hedge"
        assert _resolve_alt_profile_from_strategy("Managed Futures") == "cta"
        assert _resolve_alt_profile_from_strategy(None) == "generic_alt"
        assert _resolve_alt_profile_from_strategy("Unknown Strategy") == "generic_alt"


# ── REIT E2E: Alt model vs Equity model ─────────────────────────────


class TestREITFundE2E:
    """REIT fund should score better on alternatives model than equity model
    when it has good diversification + income but modest equity-style metrics."""

    def test_reit_alt_vs_equity(self) -> None:
        risk = _make_equity_metrics(
            return_1y=0.05,          # Modest equity return
            sharpe_1y=0.6,           # Low Sharpe (REIT vol is high)
            max_drawdown_1y=-0.15,   # Moderate drawdown
            information_ratio_1y=0.1,
        )
        alt = _make_alt_metrics(
            yield_proxy_12m=0.08,         # High yield (REIT strength)
            equity_correlation_252d=0.3,  # Moderate diversification
            downside_capture_1y=0.6,      # Good protection
            inflation_beta=2.5,           # Strong inflation hedge
            crisis_alpha_score=0.05,
            calmar_ratio_3y=0.8,
            sortino_1y=0.7,
        )

        equity_score, eq_comps = compute_fund_score(
            risk, asset_class="equity", expense_ratio_pct=0.008,
        )
        alt_score, alt_comps = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="reit",
            expense_ratio_pct=0.008,
        )

        assert alt_score > equity_score, (
            f"REIT with strong income/diversification should score higher on alt model. "
            f"Alt={alt_score}, Equity={equity_score}"
        )
        assert "income_generation" in alt_comps
        assert "inflation_hedge" in alt_comps
        # REIT profile weights
        for k in _DEFAULT_ALT_REIT_WEIGHTS:
            assert k in alt_comps, f"REIT profile should include {k}"


# ── Commodity E2E: inflation_hedge component ─────────────────────────


class TestCommodityFundE2E:
    """Commodity fund: inflation_hedge is the dominant component (0.30 weight)."""

    def test_commodity_inflation_hedge_dominates(self) -> None:
        risk = _make_equity_metrics(return_1y=0.03, sharpe_1y=0.4)
        alt = _make_alt_metrics(
            inflation_beta=3.5,            # Very strong inflation hedge
            equity_correlation_252d=0.05,  # Near-zero correlation
            crisis_alpha_score=0.10,       # Positive crisis alpha
            calmar_ratio_3y=0.7,
            downside_capture_1y=0.5,
        )

        score, comps = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="commodity",
            expense_ratio_pct=0.005,
        )

        assert "inflation_hedge" in comps
        # With beta=3.5, inflation_hedge should score very high
        assert comps["inflation_hedge"] > 70, (
            f"inflation_beta=3.5 should produce inflation_hedge > 70, got {comps['inflation_hedge']}"
        )
        assert score > 50


# ── CTA E2E: crisis_alpha dominates ──────────────────────────────────


class TestCTAFundE2E:
    """CTA fund: crisis_alpha has 0.40 weight — the highest single weight in any profile."""

    def test_cta_crisis_alpha_dominance(self) -> None:
        risk = _make_equity_metrics(return_1y=0.07, sharpe_1y=0.8)
        alt = _make_alt_metrics(
            crisis_alpha_score=0.25,        # Outstanding crisis performance
            equity_correlation_252d=-0.15,  # Negative correlation (ideal CTA)
            calmar_ratio_3y=1.8,            # Strong risk-adjusted
            inflation_beta=0.5,             # Weak inflation hedge (irrelevant for CTA)
        )

        score, comps = compute_fund_score(
            risk, asset_class="alternatives", alt_metrics=alt, alt_profile="cta",
            expense_ratio_pct=0.015,
        )

        assert "crisis_alpha" in comps
        assert _DEFAULT_ALT_CTA_WEIGHTS["crisis_alpha"] == 0.40
        # Only crisis_alpha, diversification, risk_adjusted_return, fee_efficiency
        assert "income_generation" not in comps, "CTA should not show income_generation"
        assert "inflation_hedge" not in comps, "CTA should not show inflation_hedge"
        assert score > 55, f"Strong CTA should score > 55, got {score}"


# ── ELITE Validation ─────────────────────────────────────────────────


class TestELITECrossAssetValidation:
    """Validate that ELITE ranking can handle all 4 asset classes fairly."""

    def test_four_scoring_models_produce_valid_scores(self) -> None:
        """Each scoring model should produce a valid 0-100 score."""
        risk = _make_equity_metrics()
        alt = _make_alt_metrics()

        # Mock FI metrics
        fi = MagicMock()
        fi.empirical_duration = 5.2
        fi.credit_beta = 0.8
        fi.yield_proxy_12m = 0.04
        fi.duration_adj_drawdown_1y = -1.5

        # Mock Cash metrics
        cash = MagicMock()
        cash.seven_day_net_yield = 5.25
        cash.fed_funds_rate_at_calc = 5.33
        cash.nav_per_share_mmf = 1.0000
        cash.pct_weekly_liquid = 55.0
        cash.weighted_avg_maturity_days = 25

        scores = {}

        s, _ = compute_fund_score(risk, asset_class="equity")
        scores["equity"] = s

        s, _ = compute_fund_score(risk, asset_class="fixed_income", fi_metrics=fi)
        scores["fixed_income"] = s

        s, _ = compute_fund_score(risk, asset_class="cash", cash_metrics=cash)
        scores["cash"] = s

        s, _ = compute_fund_score(risk, asset_class="alternatives", alt_metrics=alt, alt_profile="hedge")
        scores["alternatives"] = s

        for model, score in scores.items():
            assert 0 <= score <= 100, f"{model} score {score} out of range"
            assert score > 0, f"{model} score should be > 0 with valid data"

    def test_elite_fairness_no_model_penalized(self) -> None:
        """A 'good' fund in each class should score reasonably (> 40)."""
        # Good equity fund
        risk_eq = _make_equity_metrics(return_1y=0.15, sharpe_1y=1.5, max_drawdown_1y=-0.08)
        s_eq, _ = compute_fund_score(risk_eq, asset_class="equity")

        # Good alt fund
        risk_alt = _make_equity_metrics(return_1y=0.08, sharpe_1y=0.9)
        alt = _make_alt_metrics(
            equity_correlation_252d=0.1, crisis_alpha_score=0.15,
            calmar_ratio_3y=1.5, sortino_1y=2.0, downside_capture_1y=0.3,
        )
        s_alt, _ = compute_fund_score(risk_alt, asset_class="alternatives", alt_metrics=alt, alt_profile="hedge")

        # Good cash fund
        cash = MagicMock()
        cash.seven_day_net_yield = 5.50
        cash.fed_funds_rate_at_calc = 5.33
        cash.nav_per_share_mmf = 1.0000
        cash.pct_weekly_liquid = 70.0
        cash.weighted_avg_maturity_days = 15
        risk_cash = _make_equity_metrics()
        s_cash, _ = compute_fund_score(risk_cash, asset_class="cash", cash_metrics=cash)

        for label, score in [("equity", s_eq), ("alternatives", s_alt), ("cash", s_cash)]:
            assert score > 40, f"Good {label} fund should score > 40, got {score}"

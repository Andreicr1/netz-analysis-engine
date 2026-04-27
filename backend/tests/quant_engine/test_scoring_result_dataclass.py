"""Regression tests for S07-F05 (silent dispatch) + S07-F07 (degraded surface).

PR-Q59: ScoringResult dataclass + degraded surface.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from quant_engine.scoring_service import (
    ScoringResult,
    compute_fund_score,
)


@dataclass
class _RiskMetrics:
    return_1y: float | None = 0.10
    sharpe_1y: float | None = 1.2
    sharpe_cf: float | None = None
    max_drawdown_1y: float | None = -0.08
    information_ratio_1y: float | None = 0.6


@dataclass
class _CashMetrics:
    seven_day_net_yield: float | None = 5.30
    fed_funds_rate_at_calc: float | None = 5.33
    nav_per_share_mmf: float | None = 1.0000
    pct_weekly_liquid: float | None = 85.0
    weighted_avg_maturity_days: float | None = 15


@dataclass
class _FIMetrics:
    empirical_duration: float | None = 6.0
    credit_beta: float | None = 1.0
    yield_proxy_12m: float | None = 0.05
    duration_adj_drawdown_1y: float | None = -0.005


@dataclass
class _AltMetrics:
    equity_correlation_252d: float | None = 0.2
    downside_capture_1y: float | None = 0.5
    upside_capture_1y: float | None = 0.7
    crisis_alpha_score: float | None = 0.08
    calmar_ratio_3y: float | None = 1.2
    max_drawdown_3y: float | None = -0.10
    sortino_1y: float | None = 1.5
    inflation_beta: float | None = 1.8
    yield_proxy_12m: float | None = 0.06
    tracking_error_1y: float | None = 0.02


def _equity_metrics_full() -> _RiskMetrics:
    return _RiskMetrics()


def _equity_metrics_partial() -> _RiskMetrics:
    return _RiskMetrics(
        return_1y=None,
        sharpe_1y=1.2,
        sharpe_cf=None,
        max_drawdown_1y=-0.08,
        information_ratio_1y=None,
    )


# ── F05: dispatch silent fallback ──────────────────────────────────────


def test_cash_asset_class_with_metrics_returns_cash_score() -> None:
    """asset_class=cash + cash_metrics present → cash scoring path."""
    metrics = _equity_metrics_full()
    cash_metrics = _CashMetrics()
    result = compute_fund_score(
        metrics, cash_metrics=cash_metrics, asset_class="cash",
        expense_ratio_pct=0.001,
    )
    assert isinstance(result, ScoringResult)
    assert "yield_vs_risk_free" in result.components
    assert "return_consistency" not in result.components


def test_cash_asset_class_without_metrics_marks_degraded() -> None:
    """asset_class=cash + cash_metrics=None → degraded flag set, reason cites class mismatch."""
    metrics = _equity_metrics_full()
    result = compute_fund_score(metrics, cash_metrics=None, asset_class="cash")
    assert isinstance(result, ScoringResult)
    assert result.degraded is True
    assert any("asset_class_metrics_missing:cash" in r for r in result.degraded_reasons)


def test_fixed_income_asset_class_without_metrics_marks_degraded() -> None:
    metrics = _equity_metrics_full()
    result = compute_fund_score(metrics, fi_metrics=None, asset_class="fixed_income")
    assert result.degraded is True
    assert any("asset_class_metrics_missing:fixed_income" in r for r in result.degraded_reasons)


def test_alternatives_asset_class_without_metrics_marks_degraded() -> None:
    metrics = _equity_metrics_full()
    result = compute_fund_score(metrics, alt_metrics=None, asset_class="alternatives")
    assert result.degraded is True
    assert any("asset_class_metrics_missing:alternatives" in r for r in result.degraded_reasons)


def test_equity_asset_class_with_full_metrics_not_degraded() -> None:
    """Default path: equity asset class + full metrics → not degraded."""
    metrics = _equity_metrics_full()
    result = compute_fund_score(
        metrics, flows_momentum_score=60.0, expense_ratio_pct=0.005,
        asset_class="equity",
    )
    assert result.degraded is False
    assert result.degraded_reasons == []


def test_class_mismatch_still_produces_equity_components() -> None:
    """When asset_class mismatch triggers fallback, equity components are present."""
    metrics = _equity_metrics_full()
    result = compute_fund_score(metrics, cash_metrics=None, asset_class="cash")
    assert "return_consistency" in result.components
    assert "yield_vs_risk_free" not in result.components


# ── F07: missing-data observability ────────────────────────────────────


def test_partial_equity_metrics_marks_degraded_with_synthesized_components() -> None:
    """Equity scoring with several fields None → degraded with synthesized reasons."""
    metrics = _equity_metrics_partial()
    result = compute_fund_score(metrics, asset_class="equity")
    assert result.degraded is True
    synthesized = [r for r in result.degraded_reasons if r.startswith("synthesized_component:")]
    # return_1y=None, information_ratio_1y=None, flows_momentum=None (default), fee_efficiency=None (default)
    assert len(synthesized) >= 3


def test_score_still_produced_even_when_degraded() -> None:
    """Even with full-fallback scoring, score is in [0, 100] (not None or NaN)."""
    metrics = _equity_metrics_partial()
    result = compute_fund_score(metrics, asset_class="equity")
    assert 0.0 <= result.score <= 100.0


def test_fi_scoring_tracks_synthesized_components() -> None:
    """FI scoring with missing yield marks it as synthesized."""
    fi = _FIMetrics(yield_proxy_12m=None)
    result = compute_fund_score(
        _equity_metrics_full(), asset_class="fixed_income", fi_metrics=fi,
    )
    assert result.degraded is True
    assert "synthesized_component:yield_consistency" in result.degraded_reasons


def test_cash_scoring_tracks_synthesized_components() -> None:
    """Cash scoring with missing nav marks it as synthesized."""
    cash = _CashMetrics(nav_per_share_mmf=None)
    result = compute_fund_score(
        _equity_metrics_full(), asset_class="cash", cash_metrics=cash,
    )
    assert result.degraded is True
    assert "synthesized_component:nav_stability" in result.degraded_reasons


def test_alt_scoring_tracks_synthesized_components() -> None:
    """Alt scoring with all None metrics marks components as synthesized."""
    alt = _AltMetrics(
        equity_correlation_252d=None,
        downside_capture_1y=None,
        upside_capture_1y=None,
        crisis_alpha_score=None,
        calmar_ratio_3y=None,
        max_drawdown_3y=None,
        sortino_1y=None,
        inflation_beta=None,
        yield_proxy_12m=None,
        tracking_error_1y=None,
    )
    result = compute_fund_score(
        _equity_metrics_full(), asset_class="alternatives", alt_metrics=alt,
    )
    assert result.degraded is True
    synthesized = [r for r in result.degraded_reasons if r.startswith("synthesized_component:")]
    assert len(synthesized) >= 3


# ── Backward compatibility ─────────────────────────────────────────────


def test_components_dict_still_populated_for_dashboards() -> None:
    """The components dict — used by every UI consumer — must still be populated."""
    metrics = _equity_metrics_full()
    result = compute_fund_score(metrics, asset_class="equity")
    assert isinstance(result.components, dict)
    assert "return_consistency" in result.components
    assert "risk_adjusted_return" in result.components


def test_score_equivalence_for_full_inputs() -> None:
    """For fully-populated equity input, score must match pinned regression value."""
    metrics = _equity_metrics_full()
    result = compute_fund_score(
        metrics, flows_momentum_score=60.0, expense_ratio_pct=0.005,
        asset_class="equity",
    )
    assert result.score == pytest.approx(62.05, abs=0.5)


def test_scoring_result_is_frozen() -> None:
    """ScoringResult dataclass is immutable."""
    result = compute_fund_score(_equity_metrics_full(), asset_class="equity")
    with pytest.raises(AttributeError):
        result.score = 99.0  # type: ignore[misc]

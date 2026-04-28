"""Codex catch #4 — degraded based on weighted components only (PR-Q74).

A synthesized component with weight 0 in config must NOT set degraded=True.
Only weighted (weight > 0) synthesized components count toward degraded
status, preventing false-positive telemetry in risk_calc._score_metrics.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_engine.scoring_service import compute_fund_score


@dataclass
class _RiskMetrics:
    return_1y: float | None = 0.10
    sharpe_1y: float | None = 1.2
    sharpe_cf: float | None = None
    max_drawdown_1y: float | None = -0.08
    information_ratio_1y: float | None = 0.6


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


def test_synthesized_zero_weight_component_does_not_set_degraded():
    """If a synthesized component has weight 0 in config, degraded=False.

    insider_sentiment is opt-in (default weight 0). When insider_sentiment_score
    is None it is synthesized, but since its weight is 0 in default config it
    should NOT trigger degraded.
    """
    metrics = _RiskMetrics()
    # Default config has insider_sentiment weight = 0.0 (opt-in).
    # All other components are fully observed → no weighted synthesized.
    result = compute_fund_score(
        metrics,
        flows_momentum_score=55.0,
        expense_ratio_pct=0.005,  # 0.5% ER
        insider_sentiment_score=None,  # Would be synthesized if weighted
        asset_class="equity",
    )
    assert result.degraded is False, (
        f"Expected degraded=False when only zero-weight component is synthesized. "
        f"Got degraded_reasons={result.degraded_reasons}"
    )
    assert result.degraded_reasons == []


def test_synthesized_weighted_component_sets_degraded():
    """Synthesized component WITH weight > 0 → degraded=True (existing behavior)."""
    metrics = _RiskMetrics(sharpe_1y=None)  # risk_adjusted_return synthesized
    result = compute_fund_score(
        metrics,
        flows_momentum_score=55.0,
        expense_ratio_pct=0.005,
        asset_class="equity",
    )
    # Default config has risk_adjusted_return weight = 0.25
    assert result.degraded is True
    assert "synthesized_component:risk_adjusted_return" in result.degraded_reasons


def test_alternatives_path_filter_already_applied():
    """_compute_alternatives_score path: filter already applied (Q59) — verify still works.

    tracking_efficiency has 0 weight in hedge profile. When tracking_error_1y is
    None (synthesized), degraded should NOT be set for that component.
    """
    alt = _AltMetrics(tracking_error_1y=None)
    # hedge profile: tracking_efficiency weight = 0
    result = compute_fund_score(
        _RiskMetrics(),
        asset_class="alternatives",
        alt_metrics=alt,
        alt_profile="hedge",
        expense_ratio_pct=0.015,
    )
    # tracking_efficiency is synthesized but has 0 weight in hedge profile
    assert "synthesized_component:tracking_efficiency" not in result.degraded_reasons

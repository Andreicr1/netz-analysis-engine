"""Regression tests for S07-F06 — cash opacity penalty consistency."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from quant_engine.scoring_service import _compute_cash_score


@dataclass
class _StubCashMetrics:
    """Stub satisfying CashMetrics protocol with controlled availability."""

    seven_day_net_yield: float | None = 0.05
    fed_funds_rate_at_calc: float | None = 0.0525
    nav_per_share_mmf: float | None = 1.0
    pct_weekly_liquid: float | None = 60.0
    weighted_avg_maturity_days: float | None = 30.0


def test_missing_component_with_peer_median_applies_opacity_penalty() -> None:
    """Cash fund missing yield_vs_risk_free should fall back to peer_median - 5,
    not peer_median itself."""
    cash = _StubCashMetrics(seven_day_net_yield=None, fed_funds_rate_at_calc=None)
    pm = {"yield_vs_risk_free": 50.0}
    result = _compute_cash_score(cash, None, 0.005, pm)
    assert result.components["yield_vs_risk_free"] == pytest.approx(45.0)


def test_missing_component_without_peer_median_returns_45() -> None:
    """No peer median → neutral midpoint 45 (unchanged behavior)."""
    cash = _StubCashMetrics(seven_day_net_yield=None, fed_funds_rate_at_calc=None)
    result = _compute_cash_score(cash, None, 0.005, None)
    assert result.components["yield_vs_risk_free"] == pytest.approx(45.0)


def test_missing_component_floors_at_zero() -> None:
    """Peer median below 5 → fallback floors at 0, not negative."""
    cash = _StubCashMetrics(seven_day_net_yield=None, fed_funds_rate_at_calc=None)
    pm = {"yield_vs_risk_free": 3.0}
    result = _compute_cash_score(cash, None, 0.005, pm)
    assert result.components["yield_vs_risk_free"] == pytest.approx(0.0)


def test_synthesized_component_tracked_in_degraded_reasons() -> None:
    """Q59 introduced synthesized tracking; cash fallback must append to it."""
    cash = _StubCashMetrics(
        seven_day_net_yield=None,
        fed_funds_rate_at_calc=None,
        nav_per_share_mmf=None,
    )
    result = _compute_cash_score(cash, None, 0.005, {"yield_vs_risk_free": 50.0, "nav_stability": 50.0})
    assert result.degraded is True
    assert any("yield_vs_risk_free" in r for r in result.degraded_reasons)
    assert any("nav_stability" in r for r in result.degraded_reasons)


def test_full_cash_metrics_no_synthesis() -> None:
    """All components present → no degraded flag."""
    cash = _StubCashMetrics()
    result = _compute_cash_score(cash, None, 0.005, None)
    assert result.degraded is False


def test_opacity_consistency_with_equity_fallback() -> None:
    """A cash fund with all components missing should not score systematically
    higher than an equity fund with all components missing (same peer median)."""
    cash = _StubCashMetrics(
        seven_day_net_yield=None,
        fed_funds_rate_at_calc=None,
        nav_per_share_mmf=None,
        pct_weekly_liquid=None,
        weighted_avg_maturity_days=None,
    )
    pm = {
        "yield_vs_risk_free": 60.0,
        "nav_stability": 60.0,
        "liquidity_quality": 60.0,
        "maturity_discipline": 60.0,
    }
    result = _compute_cash_score(cash, None, 0.005, pm)
    assert result.components["yield_vs_risk_free"] == pytest.approx(55.0)
    assert result.components["nav_stability"] == pytest.approx(55.0)
    assert result.components["liquidity_quality"] == pytest.approx(55.0)
    assert result.components["maturity_discipline"] == pytest.approx(55.0)

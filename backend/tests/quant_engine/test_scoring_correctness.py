"""PR-Q18 — scoring_service.py correctness regression tests.

Each test targets a specific fix (BUG-S1 through S12). Tests MUST fail
without the corresponding fix and pass with it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import pytest

from quant_engine.scoring_service import (
    _clamp_component_score,
    _compute_alternatives_score,
    _compute_cash_score,
    _compute_fee_efficiency,
    _compute_fi_score,
    _normalize,
    _peaked_score,
    _validate_weights,
    compute_fund_score,
    resolve_alt_profile_weights,
    resolve_scoring_weights,
)

# ── Minimal stubs satisfying the Protocol contracts ──────────────────


@dataclass
class _StubRiskMetrics:
    return_1y: float | None = 0.10
    sharpe_1y: float | None = 1.0
    sharpe_cf: float | None = None
    max_drawdown_1y: float | None = -0.05
    information_ratio_1y: float | None = 0.5


@dataclass
class _StubFIMetrics:
    empirical_duration: float | None = 5.0
    credit_beta: float | None = 1.0
    yield_proxy_12m: float | None = 0.04
    duration_adj_drawdown_1y: float | None = -1.0


@dataclass
class _StubCashMetrics:
    seven_day_net_yield: float | None = 0.05
    fed_funds_rate_at_calc: float | None = 0.0525
    nav_per_share_mmf: float | None = 1.0
    pct_weekly_liquid: float | None = 60.0
    weighted_avg_maturity_days: float | None = 30.0


@dataclass
class _StubAltMetrics:
    equity_correlation_252d: float | None = 0.3
    downside_capture_1y: float | None = 0.5
    upside_capture_1y: float | None = 1.2
    crisis_alpha_score: float | None = 0.02
    calmar_ratio_3y: float | None = 0.8
    max_drawdown_3y: float | None = -0.15
    sortino_1y: float | None = 2.0
    inflation_beta: float | None = -4.0
    yield_proxy_12m: float | None = 0.06
    tracking_error_1y: float | None = 0.02


# ── Fix 1 (BUG-S3) — NaN passes _normalize and returns 100 ─────────


def test_BUG_S3_nan_normalize_returns_missing_data_score() -> None:
    """NaN value must return 45.0 (missing-data), not 100.0."""
    result = _normalize(float("nan"), -0.20, 0.40)
    assert result == 45.0, f"NaN should return 45.0, got {result}"

    result_inf = _normalize(float("inf"), -0.20, 0.40)
    assert result_inf == 45.0, f"Inf should return 45.0, got {result_inf}"

    result_neg_inf = _normalize(float("-inf"), -0.20, 0.40)
    assert result_neg_inf == 45.0, f"-Inf should return 45.0, got {result_neg_inf}"


# ── Fix 2 (BUG-S5) — Missing component silently injected as 50 ──────


def test_BUG_S5_missing_weighted_component_raises() -> None:
    """Weights referencing components not computed must raise ValueError."""
    m = _StubRiskMetrics()
    # Config with a bogus component that no code path ever populates.
    bad_config: dict[str, Any] = {
        "scoring_weights": {
            "return_consistency": 0.20,
            "risk_adjusted_return": 0.20,
            "drawdown_control": 0.15,
            "information_ratio": 0.15,
            "flows_momentum": 0.10,
            "fee_efficiency": 0.10,
            "nonexistent_component": 0.10,
        },
    }
    with pytest.raises(ValueError, match="weights reference components not provided"):
        compute_fund_score(m, config=bad_config)


# ── Fix 3 (BUG-S8) — config.get("scoring_weights", config) fallback ──


def test_BUG_S8_non_nested_config_returns_defaults() -> None:
    """Passing a non-nested config (no 'scoring_weights' key) must return defaults."""
    non_nested = {"use_robust_sharpe": True, "duration_center": 5.0}
    weights = resolve_scoring_weights(non_nested)

    # Should return defaults, NOT the whole config dict
    assert "use_robust_sharpe" not in weights
    assert "duration_center" not in weights
    assert "return_consistency" in weights
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-3)


def test_BUG_S8_alt_non_nested_config_returns_defaults() -> None:
    """resolve_alt_profile_weights with non-nested config must not use config as weights."""
    non_nested = {"use_robust_sharpe": True, "duration_center": 5.0}
    weights = resolve_alt_profile_weights("hedge", non_nested)

    assert "use_robust_sharpe" not in weights
    assert "crisis_alpha" in weights
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-3)


# ── Fix 4 (BUG-S1) — Hardcoded weights misaligned with scoring.yaml ──


def test_BUG_S1_default_weights_match_production_config() -> None:
    """Default weights must match calibration/config/scoring.yaml values."""
    weights = resolve_scoring_weights(None)  # no config → hardcoded defaults

    assert weights["risk_adjusted_return"] == 0.25, (
        f"Expected 0.25 (production), got {weights['risk_adjusted_return']}"
    )
    assert weights["flows_momentum"] == 0.10, (
        f"Expected 0.10 (production), got {weights['flows_momentum']}"
    )
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-3)


# ── Fix 5 (BUG-S12) — NaN expense_ratio produces worst fee score ────


def test_BUG_S12_nan_expense_ratio_falls_through_to_peer() -> None:
    """NaN expense_ratio must not produce 0 (worst); should fall through to peer/45."""
    # to_decimal_fraction already returns None for NaN, but double-check
    # that _compute_fee_efficiency handles it correctly.
    result = _compute_fee_efficiency(float("nan"))
    assert result == 45.0, f"NaN expense should fall to 45.0, got {result}"

    result_with_peer = _compute_fee_efficiency(float("nan"), {"fee_efficiency": 60.0})
    assert result_with_peer == pytest.approx(55.0), (
        f"NaN with peer should fall to peer-5, got {result_with_peer}"
    )


# ── Fix 6 (BUG-S2) — Weights not validated for sum/sign/finiteness ──


def test_BUG_S2_negative_weight_raises() -> None:
    """Negative weight must raise ValueError."""
    with pytest.raises(ValueError, match="negative"):
        _validate_weights({"a": -0.5, "b": 1.5}, "test")


def test_BUG_S2_non_finite_weight_raises() -> None:
    """NaN weight must raise ValueError."""
    with pytest.raises(ValueError, match="non-finite"):
        _validate_weights({"a": float("nan"), "b": 0.5}, "test")


def test_BUG_S2_sum_not_one_raises() -> None:
    """Weights summing to 2.0 must raise ValueError."""
    with pytest.raises(ValueError, match="weights sum to"):
        _validate_weights({"a": 1.0, "b": 1.0}, "test")


def test_BUG_S2_config_with_bad_weights_falls_to_defaults() -> None:
    """resolve_scoring_weights with invalid config weights must fall back to defaults."""
    config: dict[str, Any] = {
        "scoring_weights": {
            "return_consistency": 0.50,
            "risk_adjusted_return": 0.50,
            "drawdown_control": 0.50,
        },
    }
    # Bad weights sum to 1.5 — validation raises, caught by except → defaults returned
    weights = resolve_scoring_weights(config)
    assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-3)
    assert weights["return_consistency"] == 0.20  # default, not 0.50


# ── Fix 7 (BUG-S4) — spread_capture peaked-at-target ────────────────


def test_BUG_S4_spread_capture_peaked_at_one() -> None:
    """credit_beta = 1.0 should score 100 (peak). beta = 2.0 should score 0."""
    # _peaked_score: peak at target=1.0, half_range=1.0
    assert _peaked_score(1.0, target=1.0, half_range=1.0) == 100.0
    assert _peaked_score(0.0, target=1.0, half_range=1.0) == 0.0
    assert _peaked_score(2.0, target=1.0, half_range=1.0) == 0.0
    assert _peaked_score(0.5, target=1.0, half_range=1.0) == pytest.approx(50.0)
    assert _peaked_score(1.5, target=1.0, half_range=1.0) == pytest.approx(50.0)

    # Verify in context: FI scoring with credit_beta = 1.0 should yield 100
    fi = _StubFIMetrics(credit_beta=1.0)
    _, components = _compute_fi_score(fi, None, 0.005, None)
    assert components["spread_capture"] == 100.0

    # High credit_beta (2.5) should score low
    fi_high = _StubFIMetrics(credit_beta=2.5)
    _, components_high = _compute_fi_score(fi_high, None, 0.005, None)
    assert components_high["spread_capture"] < 50.0


# ── Fix 8 (BUG-S6) — External component scores not bounded ──────────


def test_BUG_S6_flows_momentum_clamped_to_100() -> None:
    """flows_momentum_score=500 must be clamped to 100, not passed through."""
    m = _StubRiskMetrics()
    score, components = compute_fund_score(m, flows_momentum_score=500.0)
    assert components["flows_momentum"] == 100.0, (
        f"Expected clamped to 100, got {components['flows_momentum']}"
    )


def test_BUG_S6_non_finite_score_raises() -> None:
    """Non-finite external component score must raise ValueError."""
    with pytest.raises(ValueError, match="non-finite"):
        _clamp_component_score(float("nan"), "test")


# ── Fix 9 (BUG-S7) — ffr <= 0 fallback masks negative-rate regimes ──


def test_BUG_S7_zero_rate_continuous_score() -> None:
    """ffr=0.0 with yld=0.01 must produce a continuous score, not collapsed fallback."""
    cash = _StubCashMetrics(seven_day_net_yield=0.01, fed_funds_rate_at_calc=0.0)
    _, components = _compute_cash_score(cash, None, 0.005, None)
    score = components["yield_vs_risk_free"]
    # Spread = 1.0 pp → normalized on [-5, 5] → (1+5)/10 * 100 = 60
    assert 55.0 < score < 65.0, f"Expected ~60 for 1pp spread, got {score}"


def test_BUG_S7_negative_rate_preserves_spread_sign() -> None:
    """ffr=-0.005 with yld=+0.001 must score above 50 (positive spread)."""
    cash = _StubCashMetrics(seven_day_net_yield=0.001, fed_funds_rate_at_calc=-0.005)
    _, components = _compute_cash_score(cash, None, 0.005, None)
    score = components["yield_vs_risk_free"]
    # Spread = (0.001 - (-0.005)) * 100 = 0.6 pp → above midpoint
    assert score > 50.0, f"Expected > 50 for positive spread over negative rate, got {score}"


# ── Fix 10 (BUG-S9) — 45 vs 40 missing-data inconsistency ──────────


def test_BUG_S9_fi_missing_data_consistent_with_equity() -> None:
    """FI missing-data fallback must be 45.0, not 40.0 (45 - 5)."""
    fi = _StubFIMetrics(empirical_duration=None)
    _, components = _compute_fi_score(fi, None, 0.005, None)
    assert components["duration_management"] == 45.0, (
        f"Expected 45.0 for missing FI data, got {components['duration_management']}"
    )


def test_BUG_S9_cash_missing_data_consistent() -> None:
    """Cash missing-data fallback must be 45.0, not 40.0."""
    cash = _StubCashMetrics(nav_per_share_mmf=None)
    _, components = _compute_cash_score(cash, None, 0.005, None)
    assert components["nav_stability"] == 45.0, (
        f"Expected 45.0 for missing cash data, got {components['nav_stability']}"
    )


def test_BUG_S9_alt_missing_data_consistent() -> None:
    """Alt missing-data fallback must be 45.0, not 40.0."""
    alt = _StubAltMetrics(equity_correlation_252d=None)
    _, components = _compute_alternatives_score(alt, "hedge", None, 0.005, None)
    assert components.get("diversification_value", 45.0) == 45.0


# ── Fix 11 (BUG-S11) — flows_momentum default 50 vs 45 ──────────────


def test_BUG_S11_flows_momentum_omitted_defaults_to_45() -> None:
    """Omitted flows_momentum_score must default to 45.0 (missing-data), not 50."""
    m = _StubRiskMetrics()
    _, components = compute_fund_score(m)
    assert components["flows_momentum"] == 45.0, (
        f"Expected 45.0 for omitted flows_momentum, got {components['flows_momentum']}"
    )


# ── Fix 12 (BUG-S10) — Decompose calmar duplication ─────────────────


def test_BUG_S10_drawdown_control_uses_max_drawdown_not_calmar() -> None:
    """drawdown_control must use max_drawdown_3y, not calmar_ratio_3y."""
    # Two funds with same calmar but different max_drawdown_3y.
    # commodity profile has drawdown_control weight.
    alt_low_dd = _StubAltMetrics(calmar_ratio_3y=0.8, max_drawdown_3y=-0.05)
    alt_high_dd = _StubAltMetrics(calmar_ratio_3y=0.8, max_drawdown_3y=-0.40)

    _, comps_low = _compute_alternatives_score(alt_low_dd, "commodity", None, 0.005, None)
    _, comps_high = _compute_alternatives_score(alt_high_dd, "commodity", None, 0.005, None)

    # Different max_drawdown → different drawdown_control (despite same calmar)
    assert comps_low["drawdown_control"] > comps_high["drawdown_control"], (
        f"Lower drawdown ({-0.05}) should score higher than {-0.40}, "
        f"got {comps_low['drawdown_control']} vs {comps_high['drawdown_control']}"
    )


def test_BUG_S10_missing_max_drawdown_falls_to_45() -> None:
    """Missing max_drawdown_3y must produce 45.0, not inherit calmar score."""
    alt = _StubAltMetrics(calmar_ratio_3y=1.2, max_drawdown_3y=None)
    _, comps = _compute_alternatives_score(alt, "commodity", None, 0.005, None)
    assert comps["drawdown_control"] == 45.0

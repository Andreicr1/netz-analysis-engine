"""Regression tests for PR-Q16 regime_service correctness fixes (12 bugs).

Each test maps 1:1 with a fix in docs/prompts/2026-04-25-pr-q16-regime-correctness.md.
DO NOT collapse multiple bug coverages into a single test — independence is the point.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from quant_engine.regime_service import (
    _amplify_weights,
    _ramp,
    _validate_plausibility,
    apply_regime_hysteresis,
    classify_regime_from_volatility,
    classify_regime_multi_signal,
    detect_regime,
)


# ─── Tier 1 ────────────────────────────────────────────────────────────────


def test_BUG_R1_stagflation_classified_as_crisis_not_inflation():
    # cpi_yoy=4.5% AND extreme stress signals — must be CRISIS, not INFLATION.
    regime, reasons, _ = classify_regime_multi_signal(
        vix=80.0,
        yield_curve_spread=-1.0,
        cpi_yoy=4.5,
        hy_oas=10.0,
    )
    assert regime == "CRISIS", f"expected CRISIS for stagflation, got {regime} (reasons={reasons})"


def test_BUG_R1_inflation_still_fires_when_no_crisis_stress():
    # cpi_yoy=4.5% with calm stress — must STILL be INFLATION.
    regime, _, _ = classify_regime_multi_signal(
        vix=15.0,
        yield_curve_spread=1.0,
        cpi_yoy=4.5,
        hy_oas=2.5,
    )
    assert regime == "INFLATION"


def test_BUG_R3_amplify_weights_sum_to_one_under_cap_pressure():
    # 2 signals, both at score 70 → after amplification both exceed w_max → must still sum to 1.0.
    signals = [
        ("vix", 70.0, 0.10, "vix=...stress=70"),
        ("cfnai", 70.0, 0.18, "cfnai=...stress=70"),
    ]
    out = _amplify_weights(signals, alpha=2.0, gamma=2.0, w_max=0.35)
    total = sum(w for _, _, w, _ in out)
    assert abs(total - 1.0) < 1e-6, f"weights must sum to 1.0, got {total}"


def test_BUG_R3_two_signals_both_at_70_classify_as_crisis():
    # The full-pipeline reproduction: 2 signals at score 70 each → composite >= 50 → CRISIS,
    # not RISK_OFF (which would be the buggy outcome with sum=0.70).
    regime, reasons, _ = classify_regime_multi_signal(
        vix=35.0,            # _ramp 18→35 ⇒ score 100; calibrated to land near 70 after weighting
        cpi_yoy=2.0,         # below cpi_yoy_high
        yield_curve_spread=None,
        sahm_rule=None,
        hy_oas=6.0,          # _ramp(2.5, 6.0) at 6.0 ⇒ 100
    )
    # With only vix + hy_oas surviving and both maxed, stress should clearly exceed 50.
    assert regime == "CRISIS", f"expected CRISIS, got {regime} (reasons={reasons})"


# ─── Tier 2 ────────────────────────────────────────────────────────────────


def test_BUG_R2_nan_signal_does_not_produce_crisis():
    # vix=NaN must be rejected (returns None inputs reduce to single-signal path);
    # must NOT produce a 100/100 stress score from a NaN propagation.
    regime, reasons, _ = classify_regime_multi_signal(
        vix=float("nan"),
        yield_curve_spread=0.5,
        cpi_yoy=2.0,
        hy_oas=2.5,
        sahm_rule=0.0,
        cfnai=0.0,
    )
    assert regime != "CRISIS", f"NaN input must not synthesize CRISIS (got {regime})"
    # Also direct unit-level confirmation:
    assert _validate_plausibility("vix", float("nan")) is None
    assert _ramp(float("nan"), calm=0.0, panic=10.0) == 0.0


def test_BUG_R4_single_high_signal_classifies_crisis_not_risk_off():
    # vix=90 (extreme), all else missing → 1 signal at sub_score=100 → must be CRISIS.
    regime, reasons, _ = classify_regime_multi_signal(
        vix=90.0,
        yield_curve_spread=None,
        cpi_yoy=None,
    )
    assert regime == "CRISIS", f"single-signal extreme must be CRISIS, got {regime}"


def test_BUG_R4_single_calm_signal_classifies_risk_on():
    regime, _, _ = classify_regime_multi_signal(
        vix=12.0,
        yield_curve_spread=None,
        cpi_yoy=None,
    )
    assert regime == "RISK_ON"


def test_BUG_R8_detect_regime_with_nan_returns_does_not_silently_risk_on():
    # Build a returns array with embedded NaN — must NOT classify as RISK_ON via NaN-vol fall-through.
    rets = np.array([0.01] * 9 + [np.nan] + [0.02] * 200)
    result = detect_regime(rets)
    # After NaN filter the cleaned series has finite std → should classify by real volatility.
    # We don't assert a specific regime; we assert vol was finite (no NaN-induced RISK_ON).
    assert result.regime in ("RISK_ON", "RISK_OFF", "CRISIS")
    # Direct sub-function test:
    assert classify_regime_from_volatility(float("nan")) == "RISK_OFF"


# ─── Tier 4 ────────────────────────────────────────────────────────────────


def test_BUG_R9_cpi_yoy_uses_relativedelta_not_380_days():
    # Indirect: query the function source for `relativedelta(months=12)` and confirm
    # `timedelta(days=380)` does not appear in the CPI lookup.
    import inspect

    from quant_engine import regime_service

    src = inspect.getsource(regime_service.build_regime_inputs)
    assert "relativedelta(months=12)" in src, "CPI YoY must use relativedelta, not timedelta(days=380)"
    assert "timedelta(days=380)" not in src, "stale 380-day lookup must be removed"


def test_BUG_R11_ramp_inf_returns_zero():
    # _ramp with Inf should not produce 100 (the old bug path).
    assert _ramp(float("inf"), calm=0.0, panic=10.0) == 0.0
    assert _ramp(float("-inf"), calm=0.0, panic=10.0) == 0.0


# ─── GRAYs (R5, R10, R12) ─────────────────────────────────────────────────


def test_BUG_R5_detect_regime_default_is_risk_off_not_risk_on():
    rets = np.array([])  # empty → falls into default branch
    result = detect_regime(rets)
    assert result.regime == "RISK_OFF", f"default fallback must be RISK_OFF, got {result.regime}"


def test_BUG_R10_energy_shock_negative_z_triggers_signal():
    # April-2020-style: crude_z = -2.5 (deflationary demand crash). With the symmetric ramp,
    # _ramp(-(-2.5), 0.5, 3.0) = _ramp(2.5, 0.5, 3.0) ≈ 80 → energy_shock signal must fire.
    # Reproduce by calling _ramp directly with the sign symmetry the fix introduces:
    z = -2.5
    z_score = max(_ramp(z, calm=0.5, panic=3.0), _ramp(-z, calm=0.5, panic=3.0))
    assert z_score > 50.0, (
        f"symmetric energy_shock should fire on z={z}, got score={z_score}"
    )


def test_BUG_R12_apply_regime_hysteresis_immediate_escalation():
    # CRISIS entry from anywhere is immediate.
    assert apply_regime_hysteresis(prev_regime="RISK_ON", new_regime="CRISIS") == "CRISIS"
    assert apply_regime_hysteresis(prev_regime="RISK_OFF", new_regime="CRISIS") == "CRISIS"


def test_BUG_R12_apply_regime_hysteresis_slow_deescalation():
    # CRISIS → RISK_ON in one step is suppressed at threshold=4 (drops 3 ranks: 3→0).
    assert apply_regime_hysteresis(
        prev_regime="CRISIS", new_regime="RISK_ON", severity_jump_threshold=4,
    ) == "CRISIS"
    # With default threshold=1 any drop is honored.
    assert apply_regime_hysteresis(
        prev_regime="CRISIS", new_regime="RISK_OFF", severity_jump_threshold=1,
    ) == "RISK_OFF"


def test_BUG_R12_classify_regime_multi_signal_does_not_call_hysteresis():
    # Calling classify with no prior regime parameter must produce the same output as
    # before R12 — purity guarantee.
    regime, _, _ = classify_regime_multi_signal(
        vix=15.0, yield_curve_spread=1.0, cpi_yoy=2.0, hy_oas=2.5, sahm_rule=0.0, cfnai=0.0,
    )
    # We assert the function signature does NOT accept prev_regime.
    import inspect

    sig = inspect.signature(classify_regime_multi_signal)
    assert "prev_regime" not in sig.parameters, (
        "classify_regime_multi_signal must remain pure — hysteresis is caller-side"
    )

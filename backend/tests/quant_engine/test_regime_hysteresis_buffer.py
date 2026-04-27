"""Regression tests for S06-F09 (Tier 1): regime hysteresis stress-score buffer.

Pre-fix: RISK_OFF → RISK_ON de-escalated immediately because severity drop
(2-0=2) always met default severity_jump_threshold=1.  Score oscillating
24.9 → 25.1 → 24.9 around the RISK_OFF threshold flapped daily.

Post-fix: de-escalation requires stress score to drop below the entry
threshold by at least de_escalation_buffer (default 5 points).
"""

from quant_engine.regime_service import apply_regime_hysteresis

_THRESHOLDS = {"risk_off_entry": 25.0, "inflation_entry": 30.0, "crisis_entry": 50.0}


# ── Regression tests for S06-F09 (Tier 1) ──────────────────────────────────


def test_risk_off_to_risk_on_blocked_when_score_within_buffer():
    """Pre-fix: RISK_OFF → RISK_ON immediately on threshold crossing.
    Post-fix: requires stress score below (threshold - buffer)."""
    result = apply_regime_hysteresis(
        prev_regime="RISK_OFF",
        new_regime="RISK_ON",
        new_stress_score=24.0,  # threshold=25, buffer=5, requires <20
        regime_thresholds=_THRESHOLDS,
        de_escalation_buffer=5.0,
    )
    assert result == "RISK_OFF", f"Expected RISK_OFF (sticky), got {result}"


def test_risk_off_to_risk_on_allowed_when_score_below_buffer():
    """Score sufficiently below threshold → de-escalation honored."""
    result = apply_regime_hysteresis(
        prev_regime="RISK_OFF",
        new_regime="RISK_ON",
        new_stress_score=15.0,  # well below 25-5=20 buffer
        regime_thresholds=_THRESHOLDS,
        de_escalation_buffer=5.0,
    )
    assert result == "RISK_ON"


def test_oscillating_score_does_not_flap():
    """Sequential daily noise around threshold must not produce regime flips."""
    # Day 1: RISK_OFF → RISK_OFF (no change requested)
    r1 = apply_regime_hysteresis(
        "RISK_OFF", "RISK_OFF", new_stress_score=25.5, regime_thresholds=_THRESHOLDS, de_escalation_buffer=5.0,
    )
    # Day 2: classifier says RISK_ON because score dropped to 24.9 (just below threshold)
    r2 = apply_regime_hysteresis(
        r1, "RISK_ON", new_stress_score=24.9, regime_thresholds=_THRESHOLDS, de_escalation_buffer=5.0,
    )
    assert r2 == "RISK_OFF", "Should hold RISK_OFF — within buffer"
    # Day 3: score back to 25.1 — would re-enter RISK_OFF anyway
    r3 = apply_regime_hysteresis(
        r2, "RISK_OFF", new_stress_score=25.1, regime_thresholds=_THRESHOLDS, de_escalation_buffer=5.0,
    )
    assert r3 == "RISK_OFF"
    # No flapping observed across 3 days


def test_escalation_immediate_no_buffer():
    """RISK_ON → RISK_OFF must be immediate (no buffer for escalation)."""
    result = apply_regime_hysteresis(
        prev_regime="RISK_ON",
        new_regime="RISK_OFF",
        new_stress_score=25.5,  # just above threshold
        regime_thresholds=_THRESHOLDS,
        de_escalation_buffer=5.0,
    )
    assert result == "RISK_OFF", "Escalation must be immediate"


def test_legacy_behavior_when_score_not_provided():
    """If new_stress_score is None, falls back to severity-only check
    (preserves backward compat for callers that don't pass score)."""
    result = apply_regime_hysteresis(
        prev_regime="RISK_OFF",
        new_regime="RISK_ON",
        severity_jump_threshold=1,
    )
    assert result == "RISK_ON"


def test_inflation_to_risk_on_with_buffer():
    """Boundary: INFLATION (severity 1) → RISK_ON (severity 0). Drop=1.
    With severity_jump_threshold=1, severity check passes; buffer applies."""
    # Score below inflation_entry but within buffer
    result = apply_regime_hysteresis(
        prev_regime="INFLATION",
        new_regime="RISK_ON",
        new_stress_score=27.0,  # threshold=30, buffer=5, requires <25
        regime_thresholds=_THRESHOLDS,
        de_escalation_buffer=5.0,
    )
    assert result == "INFLATION", "Should hold within buffer"

    # Score sufficiently below
    result = apply_regime_hysteresis(
        prev_regime="INFLATION",
        new_regime="RISK_ON",
        new_stress_score=20.0,
        regime_thresholds=_THRESHOLDS,
        de_escalation_buffer=5.0,
    )
    assert result == "RISK_ON"


def test_crisis_to_risk_off_severity_check_first():
    """CRISIS (severity 3) → RISK_OFF (severity 2): drop=1. With
    severity_jump_threshold=1, severity check passes. Then buffer applies."""
    # Score below crisis but within buffer of crisis_entry
    result = apply_regime_hysteresis(
        prev_regime="CRISIS",
        new_regime="RISK_OFF",
        new_stress_score=47.0,  # crisis_entry=50, buffer=5, requires <45
        regime_thresholds=_THRESHOLDS,
        de_escalation_buffer=5.0,
    )
    assert result == "CRISIS"


def test_same_regime_returns_input():
    """No transition requested → return prev_regime."""
    result = apply_regime_hysteresis(
        prev_regime="RISK_ON",
        new_regime="RISK_ON",
        new_stress_score=10.0,
        regime_thresholds={"risk_off_entry": 25.0},
        de_escalation_buffer=5.0,
    )
    assert result == "RISK_ON"

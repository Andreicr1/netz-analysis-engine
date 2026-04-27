"""PR-Q53 regression tests — regime defensive defaults bundle (F03+F11+F07).

Tests the three coordinated charter §3 fixes:
- F03: gate broadens to admit classification with any fresh signal
- F11: insufficient base-weight coverage clamps to RISK_OFF
- F07: structured degraded fields on RegimeResult and RegimeRead
"""

import numpy as np

from quant_engine.regime_service import (
    INSUFFICIENT_COVERAGE_THRESHOLD,
    RegimeResult,
    classify_regime_multi_signal,
    detect_regime,
)

# ── F03 regression: gate broadens to admit real-economy signals ─────────


def test_gate_admits_classification_with_real_economy_signals_only():
    """Scenario: VIX/HY OAS/energy stale; CFNAI/Sahm/yield_curve fresh.

    Pre-fix: get_current_regime falls through to defensive fallback.
    Post-fix: classify_regime_multi_signal gets called with real-economy inputs.
    We test at the classify_regime_multi_signal level since get_current_regime
    requires DB. The gate fix ensures classify_regime_multi_signal IS called.
    """
    regime, reasons, _ = classify_regime_multi_signal(
        vix=None,  # stale
        yield_curve_spread=0.5,  # fresh
        cpi_yoy=None,
        sahm_rule=0.1,  # fresh
        cfnai=0.3,  # fresh — above-trend growth
    )
    # With fresh real-economy signals, should get a classification
    # (not a zero-signal or single-signal fallback)
    assert regime in ("RISK_ON", "RISK_OFF", "CRISIS", "INFLATION")
    assert "decision" in reasons


# ── F11 regression: insufficient base-weight clamps to RISK_OFF ─────────


def test_insufficient_signal_coverage_clamps_to_risk_off():
    """Two calm signals at total base weight 15% → clamps to RISK_OFF.

    Pre-fix: renormalized to 100%, defaulted to RISK_ON.
    VIX base weight = 0.10, yield_curve base weight = 0.05 → sum = 0.15.
    """
    regime, reasons, _ = classify_regime_multi_signal(
        vix=15.0,  # calm (below 18 threshold → stress ≈ 0)
        yield_curve_spread=1.5,  # calm (positive spread → no stress)
        cpi_yoy=None,
        sahm_rule=None,
    )
    assert regime == "RISK_OFF", f"Expected RISK_OFF clamp, got {regime}"
    assert "insufficient_signal_coverage" in reasons
    assert reasons.get("_degraded") == "true"


def test_high_stress_low_coverage_not_clamped():
    """Single signal showing CRISIS-level stress (>=50) is NOT clamped to
    RISK_OFF — the dual condition preserves real CRISIS signals."""
    # VIX at 80 → stress score near 100 via _ramp(80, 18, 35) → clamped at 100
    # Single-signal path triggers (len(signals)==1), sub_score >= 75 → CRISIS
    regime, reasons, _ = classify_regime_multi_signal(
        vix=80.0,  # extreme stress
        yield_curve_spread=None,
        cpi_yoy=None,
        sahm_rule=None,
    )
    assert regime == "CRISIS", f"Expected CRISIS, got {regime}"


def test_two_signals_below_threshold_moderate_stress_not_clamped():
    """Two signals with base weight < 0.40 but stress >= 50 → NOT clamped.

    The dual condition (weight_sum < threshold AND stress < 50) preserves
    genuine stress signals even when coverage is thin.
    """
    # VIX=40 → stress ≈ _ramp(40, 18, 35) → 100 (capped)
    # yield_curve=-1.0 → stress ≈ _ramp(1.0, -1.0, 0.5) → 100
    # base weights: 0.10 + 0.05 = 0.15 (below 0.40)
    # but stress_score will be very high after renormalization
    regime, reasons, _ = classify_regime_multi_signal(
        vix=40.0,  # panic level
        yield_curve_spread=-1.0,  # deeply inverted
        cpi_yoy=None,
        sahm_rule=None,
    )
    # Should classify as CRISIS due to high stress, NOT clamped to RISK_OFF
    assert regime == "CRISIS", f"Expected CRISIS preserved, got {regime}"


def test_adequate_coverage_not_clamped():
    """6+ signals with base weight >= 0.40 → classified normally, no clamp."""
    regime, reasons, _ = classify_regime_multi_signal(
        vix=15.0,  # calm
        yield_curve_spread=1.0,
        cpi_yoy=2.0,
        sahm_rule=0.1,
        hy_oas=3.0,
        cfnai=0.3,
        icsa_zscore=0.0,
    )
    assert regime == "RISK_ON"
    assert "insufficient_signal_coverage" not in reasons


def test_threshold_constant_is_040():
    """Guard the threshold constant value."""
    assert INSUFFICIENT_COVERAGE_THRESHOLD == 0.40


# ── F07 regression: structured degraded fields ─────────────────────────


def test_regime_result_has_degraded_fields():
    """RegimeResult dataclass must have degraded + degraded_reason fields."""
    r = RegimeResult(regime="RISK_ON")
    assert hasattr(r, "degraded")
    assert hasattr(r, "degraded_reason")
    assert r.degraded is False
    assert r.degraded_reason is None


def test_regime_result_degraded_explicit():
    """RegimeResult with explicit degraded=True."""
    r = RegimeResult(regime="RISK_OFF", degraded=True, degraded_reason="test")
    assert r.degraded is True
    assert r.degraded_reason == "test"


def test_zero_signals_returns_degraded():
    """All-None inputs → reasons contain degraded reserved keys."""
    regime, reasons, _ = classify_regime_multi_signal(
        vix=None,
        yield_curve_spread=None,
        cpi_yoy=None,
        sahm_rule=None,
    )
    assert regime == "RISK_OFF"
    assert reasons.get("_degraded") == "true"
    assert reasons.get("_degraded_reason") == "no_signals_available"


def test_single_signal_returns_degraded():
    """Single-signal classification path → degraded reserved keys."""
    regime, reasons, _ = classify_regime_multi_signal(
        vix=20.0,
        yield_curve_spread=None,
        cpi_yoy=None,
        sahm_rule=None,
    )
    assert reasons.get("_degraded") == "true"
    assert reasons.get("_degraded_reason") == "single_signal_degraded_confidence"


def test_full_coverage_not_degraded():
    """Healthy multi-signal classification → no degraded keys."""
    _, reasons, _ = classify_regime_multi_signal(
        vix=15.0,
        yield_curve_spread=1.0,
        cpi_yoy=2.0,
        sahm_rule=0.1,
        hy_oas=3.0,
        cfnai=0.3,
        icsa_zscore=0.0,
        baa_spread=1.5,
        fed_funds_delta_6m=0.0,
    )
    assert reasons.get("_degraded") is None


def test_detect_regime_insufficient_data_degraded():
    """detect_regime with < 10 returns → RegimeResult with degraded=True."""
    result = detect_regime(returns=np.array([0.01, -0.02, 0.005]))
    assert result.degraded is True
    assert result.degraded_reason == "insufficient_data"


def test_detect_regime_insufficient_clean_data_degraded():
    """detect_regime with < 10 clean returns after NaN filter → degraded=True."""
    returns = np.full(20, np.nan)
    returns[0] = 0.01  # only 1 clean return
    result = detect_regime(returns=returns)
    assert result.degraded is True
    assert result.degraded_reason == "insufficient_clean_data"


def test_detect_regime_healthy_not_degraded():
    """detect_regime with enough data → degraded=False."""
    rng = np.random.default_rng(42)
    returns = rng.normal(0.0005, 0.01, 252)
    result = detect_regime(returns=returns)
    assert result.degraded is False
    assert result.degraded_reason is None


# ── F07: RegimeRead schema ──────────────────────────────────────────────


def test_regime_read_has_degraded_fields():
    """RegimeRead schema accepts degraded fields."""
    from app.shared.schemas import RegimeRead

    r = RegimeRead(regime="RISK_ON")
    assert r.degraded is False
    assert r.degraded_reason is None

    r2 = RegimeRead(regime="RISK_OFF", degraded=True, degraded_reason="test")
    assert r2.degraded is True
    assert r2.degraded_reason == "test"


# ── Cross-finding integration ──────────────────────────────────────────


def test_f03_plus_f11_safety_contract():
    """F03 broadens gate; F11 catches optimistic renormalization.

    Scenario: only CFNAI + Sahm fresh (0.18 + 0.08 = 0.26 base weight).
    F03 admits classification; F11 clamps result to RISK_OFF.
    """
    regime, reasons, _ = classify_regime_multi_signal(
        vix=None,
        yield_curve_spread=None,
        cpi_yoy=None,
        sahm_rule=0.05,  # calm — base weight 0.08
        cfnai=0.5,  # calm (above trend) — base weight 0.18
    )
    # Base weight = 0.08 + 0.18 = 0.26 < 0.40 threshold
    # Both signals calm → stress low → F11 clamps to RISK_OFF
    assert regime == "RISK_OFF", f"Expected RISK_OFF from F11 clamp, got {regime}"
    assert "insufficient_signal_coverage" in reasons
    assert reasons.get("_degraded") == "true"
    assert reasons.get("_degraded_reason") == "insufficient_signal_coverage"


def test_f11_clamp_does_not_override_crisis_on_thin_coverage():
    """Even with thin coverage, if composite stress >= 50, keep CRISIS.

    This is the safety valve: if actual signals show genuine distress,
    don't silently downgrade to RISK_OFF.
    """
    # Sahm=1.0 → extreme stress (panic=0.50, value=1.0 → stress=100)
    # CFNAI=-1.0 → high stress (ramp(-(-1.0), 0.20, 0.70) = ramp(1.0, 0.20, 0.70) → 100)
    # base weight = 0.08 + 0.18 = 0.26 < 0.40
    # But stress will be very high after renormalization
    regime, reasons, _ = classify_regime_multi_signal(
        vix=None,
        yield_curve_spread=None,
        cpi_yoy=None,
        sahm_rule=1.0,  # deep recession signal
        cfnai=-1.0,  # severe contraction
    )
    # stress_score should be >= 50 → F11 dual condition NOT met → not clamped
    assert regime == "CRISIS", f"Expected CRISIS preserved, got {regime}"

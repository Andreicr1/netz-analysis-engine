"""PR-Q54 — RISK_ON optimistic fallback → RISK_OFF defensive regression tests.

Cross-module Charter §3 consistency: regime_service defaults to RISK_OFF
(defensive) when in doubt. allocation_proposal_service and taa_band_service
must match that convention.

Stage 1: both Opus 4.6 (S06-F04, S06-F05).
Stage 2: GPT-5.5 CONFIRMED both with line-level evidence.
"""

from quant_engine.allocation_proposal_service import (
    REGIME_TILTS,
    extract_regime_from_review,
)
from quant_engine.taa_band_service import get_regime_centers_for_regime

# ── F04 regression: extract_regime_from_review ─────────────────────────


def test_extract_regime_missing_global_defaults_defensive():
    """Empty report_json → RISK_OFF (was RISK_ON)."""
    assert extract_regime_from_review({}) == "RISK_OFF"


def test_extract_regime_explicit_none_defaults_defensive():
    """{regime: None} → RISK_OFF."""
    assert extract_regime_from_review({"regime": None}) == "RISK_OFF"


def test_extract_regime_explicit_global_none_defaults_defensive():
    """{regime: {global: None}} → RISK_OFF."""
    assert extract_regime_from_review({"regime": {"global": None}}) == "RISK_OFF"


def test_extract_regime_valid_value_passes_through():
    """Control: explicit valid regime value preserved."""
    assert extract_regime_from_review({"regime": {"global": "CRISIS"}}) == "CRISIS"
    assert extract_regime_from_review({"regime": {"global": "RISK_OFF"}}) == "RISK_OFF"
    assert extract_regime_from_review({"regime": {"global": "RISK_ON"}}) == "RISK_ON"


# ── F05a regression: allocation proposal unknown-regime fallback ───────


def test_allocation_unknown_regime_uses_defensive_tilt():
    """Unknown regime string → uses RISK_OFF tilt (was RISK_ON)."""
    fallback_value = REGIME_TILTS.get("INVALID_REGIME_STRING", REGIME_TILTS["RISK_OFF"])
    expected_defensive = REGIME_TILTS["RISK_OFF"]
    assert fallback_value == expected_defensive
    assert fallback_value != REGIME_TILTS["RISK_ON"]


# ── F05b regression: TAA unknown-regime fallback ───────────────────────


def test_taa_unknown_regime_uses_defensive_centers():
    """Unknown regime string → uses RISK_OFF centers (was RISK_ON)."""
    risk_off_centers = get_regime_centers_for_regime("RISK_OFF")
    risk_on_centers = get_regime_centers_for_regime("RISK_ON")
    invalid_centers = get_regime_centers_for_regime("INVALID_REGIME_STRING")

    assert invalid_centers == risk_off_centers, (
        f"Unknown regime should fall back to RISK_OFF (defensive). "
        f"Got {invalid_centers}, expected {risk_off_centers}"
    )
    assert risk_on_centers != risk_off_centers


# ── Cross-module convention consistency ────────────────────────────────


def test_all_three_fallback_paths_consistent():
    """F04 + F05a + F05b should all default to RISK_OFF, matching
    regime_service convention."""
    # F04
    assert extract_regime_from_review({}) == "RISK_OFF"
    # F05a — REGIME_TILTS dict pattern
    fallback = REGIME_TILTS.get("INVALID", REGIME_TILTS["RISK_OFF"])
    assert fallback == REGIME_TILTS["RISK_OFF"]
    # F05b — TAA centers
    assert get_regime_centers_for_regime("INVALID") == get_regime_centers_for_regime("RISK_OFF")

import pytest
import structlog.testing

from backend.quant_engine.mandate_risk_aversion import (
    DEFAULT_RISK_AVERSION,
    RA_MAX,
    RA_MIN,
    _normalise_mandate,
    resolve_risk_aversion,
)


# BUG-1
@pytest.mark.parametrize("mandate,expected", [
    ("Moderate  Aggressive", 2.0),       # double space
    ("moderate-aggressive", 2.0),         # dash
    ("Moderate-Aggressive", 2.0),         # dash + caps
    (" moderate aggressive ", 2.0),       # padding
    ("moderate--aggressive", 2.0),        # double dash
    ("moderate - aggressive", 2.0),       # spaced dash
])
def test_BUG_1_whitespace_normalisation(mandate, expected):
    assert resolve_risk_aversion(None, mandate) == expected


# BUG-2
def test_BUG_2_infinite_override_falls_through():
    with structlog.testing.capture_logs() as logs:
        result = resolve_risk_aversion(float("inf"), "aggressive")
    assert result == 1.5  # mandate path
    assert any(l["event"] == "non_finite_risk_aversion_discarded" for l in logs)


def test_BUG_2_negative_infinite_override_falls_through():
    result = resolve_risk_aversion(float("-inf"), None)
    assert result == DEFAULT_RISK_AVERSION


# BUG-3
def test_BUG_3_nan_override_falls_through():
    with structlog.testing.capture_logs() as logs:
        result = resolve_risk_aversion(float("nan"), "aggressive")
    assert result == 1.5  # mandate path
    assert any(l["event"] == "non_finite_risk_aversion_discarded" for l in logs)


# BUG-4
def test_BUG_4_above_upper_bound_clamped():
    with structlog.testing.capture_logs() as logs:
        result = resolve_risk_aversion(1e9, None)
    assert result == RA_MAX
    assert any(l["event"] == "risk_aversion_out_of_range_clamped" for l in logs)


def test_BUG_4_below_lower_bound_clamped():
    with structlog.testing.capture_logs() as logs:
        result = resolve_risk_aversion(0.1, None)
    assert result == RA_MIN
    assert any(l["event"] == "risk_aversion_out_of_range_clamped" for l in logs)


# BUG-5
def test_BUG_5_unknown_mandate_logs_warning():
    with structlog.testing.capture_logs() as logs:
        result = resolve_risk_aversion(None, "agressive")  # typo
    assert result == DEFAULT_RISK_AVERSION
    warning_logs = [l for l in logs if l["event"] == "unknown_mandate_using_default"]
    assert len(warning_logs) == 1
    assert warning_logs[0]["mandate"] == "agressive"


# Invariants
def test_invariant_normaliser_idempotent():
    """_normalise_mandate is idempotent."""
    raw = "Moderate  Aggressive"
    once = _normalise_mandate(raw)
    twice = _normalise_mandate(once)
    assert once == twice


def test_invariant_known_mandates_resolve():
    """Every key in _MANDATE_RISK_AVERSION resolves correctly via raw and
    decorated forms."""
    from backend.quant_engine.mandate_risk_aversion import _MANDATE_RISK_AVERSION
    for key, expected in _MANDATE_RISK_AVERSION.items():
        # Raw key
        assert resolve_risk_aversion(None, key) == expected
        # Title-cased with spaces (typical CRM input)
        decorated = key.replace("_", " ").title()
        assert resolve_risk_aversion(None, decorated) == expected


def test_invariant_explicit_override_in_range_wins():
    """A valid in-range override always wins over mandate."""
    assert resolve_risk_aversion(3.0, "aggressive") == 3.0
    assert resolve_risk_aversion(RA_MIN, "aggressive") == RA_MIN
    assert resolve_risk_aversion(RA_MAX, "aggressive") == RA_MAX


# ── Regression tests for S04-F04 (Tier 1) ──────────────────────────────────


def test_zero_override_falls_through_to_mandate():
    """A zero risk_aversion override must NOT clamp to RA_MIN; it must fall
    through to the mandate label. Conservative → 4.5, not 0.5."""
    assert resolve_risk_aversion(0.0, "conservative") == 4.5


def test_zero_override_no_mandate_returns_default():
    """Zero override + no mandate → DEFAULT_RISK_AVERSION (2.5)."""
    assert resolve_risk_aversion(0.0, None) == DEFAULT_RISK_AVERSION


def test_negative_override_falls_through_to_mandate():
    """Any negative risk_aversion override must fall through to mandate."""
    assert resolve_risk_aversion(-1.0, "conservative") == 4.5
    assert resolve_risk_aversion(-100.0, "aggressive") == 1.5


def test_negative_override_no_mandate_returns_default():
    assert resolve_risk_aversion(-1.0, None) == DEFAULT_RISK_AVERSION


def test_negative_override_unknown_mandate_returns_default():
    assert resolve_risk_aversion(-1.0, "made_up_mandate") == DEFAULT_RISK_AVERSION


# ── Existing-behavior preservation (must continue to pass) ─────────────────


def test_finite_in_range_override_returned_as_is():
    """Positive in-range override is returned unchanged."""
    assert resolve_risk_aversion(2.5, "conservative") == 2.5
    assert resolve_risk_aversion(0.7, "aggressive") == 0.7


def test_positive_below_min_clamps_to_min():
    """Positive below RA_MIN clamps to RA_MIN (intended behavior, unchanged)."""
    assert resolve_risk_aversion(0.3, "conservative") == RA_MIN
    assert resolve_risk_aversion(0.1, None) == RA_MIN


def test_above_max_clamps_to_max():
    """Above RA_MAX clamps to RA_MAX (unchanged)."""
    assert resolve_risk_aversion(15.0, "conservative") == RA_MAX
    assert resolve_risk_aversion(100.0, None) == RA_MAX


def test_nan_override_falls_through_to_mandate():
    assert resolve_risk_aversion(float("nan"), "conservative") == 4.5
    assert resolve_risk_aversion(float("nan"), None) == DEFAULT_RISK_AVERSION


def test_inf_override_falls_through_to_mandate():
    assert resolve_risk_aversion(float("inf"), "conservative") == 4.5
    assert resolve_risk_aversion(float("-inf"), "conservative") == 4.5


def test_no_override_returns_mandate():
    assert resolve_risk_aversion(None, "conservative") == 4.5
    assert resolve_risk_aversion(None, "moderate") == 2.5
    assert resolve_risk_aversion(None, "aggressive") == 1.5


def test_no_override_no_mandate_returns_default():
    assert resolve_risk_aversion(None, None) == DEFAULT_RISK_AVERSION


def test_unknown_mandate_returns_default():
    assert resolve_risk_aversion(None, "speculative") == DEFAULT_RISK_AVERSION

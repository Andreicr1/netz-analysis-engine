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

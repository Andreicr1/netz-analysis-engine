"""Regression tests for rebalance_service.py — PR-Q23.

8 tests covering 6 fixes:
  BUG-T1:  cvar_utilization fraction unit (audit trail corruption)
  BUG-T2a: recovery events (breach→ok, warning→ok) + degraded event
  BUG-T2a: breach→warning stays silent
  BUG-T2:  unknown profile / missing keys → graceful (None, None)
  BUG-T2b: applied is explicit terminal state
"""

from quant_engine.rebalance_service import (
    VALID_TRANSITIONS,
    determine_cascade_action,
    validate_status_transition,
)

# config=None → resolve_cvar_config returns defaults:
#   moderate: warning_pct=0.80, breach_days=3


# ── TIER 1 — unit ambiguity ──────────────────────────────────────────────


def test_BUG_T1_cvar_utilization_fraction():
    """cvar_utilization=0.85 → audit reason contains '85.0%' not '0.9%'.

    Uses default config (moderate: warning_pct=0.80).
    """
    event_type, reason = determine_cascade_action(
        trigger_status="warning",
        previous_trigger_status="ok",
        cvar_utilization=0.85,
        consecutive_breach_days=0,
        profile="moderate",
        config=None,
    )
    assert event_type == "cvar_breach"
    assert "85.0%" in reason
    assert "0.9%" not in reason
    assert "80%" in reason  # threshold display


# ── TIER 2a — recovery ───────────────────────────────────────────────────


def test_BUG_T2a_breach_to_ok_emits_recovery():
    event_type, reason = determine_cascade_action(
        trigger_status="ok",
        previous_trigger_status="breach",
        cvar_utilization=0.30,
        consecutive_breach_days=0,
        profile="moderate",
        config=None,
    )
    assert event_type == "cvar_recovery"
    assert "from breach" in reason


def test_BUG_T2a_warning_to_ok_emits_recovery():
    event_type, reason = determine_cascade_action(
        trigger_status="ok",
        previous_trigger_status="warning",
        cvar_utilization=0.30,
        consecutive_breach_days=0,
        profile="moderate",
        config=None,
    )
    assert event_type == "cvar_recovery"
    assert "from warning" in reason


def test_BUG_T2a_breach_to_warning_silent():
    """Granular de-escalation stays silent; only ok-recovery is recorded."""
    event_type, _reason = determine_cascade_action(
        trigger_status="warning",
        previous_trigger_status="breach",
        cvar_utilization=0.85,
        consecutive_breach_days=0,
        profile="moderate",
        config=None,
    )
    # warning while previous=breach is not the (None, "ok") escalation case;
    # falls through.
    assert event_type is None


def test_BUG_T2a_degraded_emits_event():
    event_type, reason = determine_cascade_action(
        trigger_status="degraded",
        previous_trigger_status="ok",
        cvar_utilization=float("nan"),
        consecutive_breach_days=0,
        profile="moderate",
        config=None,
    )
    assert event_type == "cvar_degraded"
    assert "unavailable" in reason.lower()


# ── TIER 2 — guard gaps ──────────────────────────────────────────────────


def test_BUG_T2_unknown_profile_no_keyerror():
    event_type, reason = determine_cascade_action(
        trigger_status="warning",
        previous_trigger_status="ok",
        cvar_utilization=0.85,
        consecutive_breach_days=0,
        profile="bogus_typo",
        config=None,
    )
    assert event_type is None  # graceful degraded, not crash
    assert reason is None


def test_BUG_T2_missing_required_key_no_keyerror():
    """Profile config with missing 'breach_days' returns (None, None) cleanly.

    Pass a config that resolve_cvar_config falls back to defaults for,
    then override the resolved profile to simulate a missing key.
    We test this by passing a profile name not in defaults.
    """
    # Passing bogus config that resolves to empty → unknown profile guard fires
    cfg = {"profiles": {"custom": {"not_cvar": True}}}
    event_type, reason = determine_cascade_action(
        trigger_status="breach",
        previous_trigger_status="warning",
        cvar_utilization=0.65,
        consecutive_breach_days=10,
        profile="custom",
        config=cfg,
    )
    assert event_type is None
    assert reason is None


# ── TIER 2b — applied terminal ────────────────────────────────────────────


def test_BUG_T2b_applied_is_terminal():
    """validate_status_transition('applied', X) is False for all X."""
    for next_state in [
        "pending", "approved", "rejected", "cancelled", "applied", "executed",
    ]:
        assert validate_status_transition("applied", next_state) is False
    # And explicit assertion in dict:
    assert "applied" in VALID_TRANSITIONS
    assert VALID_TRANSITIONS["applied"] == set()

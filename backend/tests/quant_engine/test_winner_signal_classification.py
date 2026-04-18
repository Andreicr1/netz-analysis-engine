"""PR-A19.1 Section C — WinnerSignal classification unit tests."""
from __future__ import annotations

from app.domains.wealth.schemas.sanitized import (
    WinnerSignal,
    build_operator_message,
    compute_winner_signal,
)


def test_phase_1_within_limit_is_optimal() -> None:
    sig = compute_winner_signal(
        winning_phase="phase_1_ru_max_return",
        cvar_within_limit=True,
        cvar_limit=0.075,
        min_achievable_cvar=0.05,
    )
    assert sig is WinnerSignal.OPTIMAL
    assert build_operator_message(
        signal=sig, cvar_limit=0.075,
        min_achievable_cvar=0.05, expected_return=0.08,
    ) is None


def test_phase_3_above_limit_is_cvar_infeasible() -> None:
    sig = compute_winner_signal(
        winning_phase="phase_3_min_cvar",
        cvar_within_limit=False,
        cvar_limit=0.05,
        min_achievable_cvar=0.0736,
    )
    assert sig is WinnerSignal.CVAR_INFEASIBLE_MIN_VAR
    msg = build_operator_message(
        signal=sig, cvar_limit=0.05,
        min_achievable_cvar=0.0736, expected_return=0.03,
    )
    assert msg is not None
    assert msg["severity"] == "warning"
    assert msg["action_hint"] == "raise_cvar_or_expand_universe"
    assert "7.36%" in msg["body"] or "7.4" in msg["body"]
    assert "5.0%" in msg["body"]


def test_phase_2_winner_is_robustness_fallback() -> None:
    sig = compute_winner_signal(
        winning_phase="phase_2_ru_robust",
        cvar_within_limit=True,
        cvar_limit=0.075,
        min_achievable_cvar=0.05,
    )
    assert sig is WinnerSignal.ROBUSTNESS_FALLBACK


def test_none_winner_is_pre_solve_failure() -> None:
    sig = compute_winner_signal(
        winning_phase=None,
        cvar_within_limit=False,
        cvar_limit=None,
        min_achievable_cvar=None,
    )
    assert sig is WinnerSignal.PRE_SOLVE_FAILURE


def test_phase_3_within_limit_is_degraded_other() -> None:
    # Phase 3 wins but CVaR target met — atypical, fall through to
    # the catch-all rather than claiming OPTIMAL.
    sig = compute_winner_signal(
        winning_phase="phase_3_min_cvar",
        cvar_within_limit=True,
        cvar_limit=0.10,
        min_achievable_cvar=0.05,
    )
    assert sig is WinnerSignal.DEGRADED_OTHER


def test_phase_1_outside_limit_is_degraded_other() -> None:
    sig = compute_winner_signal(
        winning_phase="phase_1_ru_max_return",
        cvar_within_limit=False,
        cvar_limit=0.05,
        min_achievable_cvar=0.04,
    )
    assert sig is WinnerSignal.DEGRADED_OTHER


def test_operator_message_for_robustness_fallback() -> None:
    msg = build_operator_message(
        signal=WinnerSignal.ROBUSTNESS_FALLBACK,
        cvar_limit=0.075, min_achievable_cvar=0.05, expected_return=0.06,
    )
    assert msg is not None
    assert msg["severity"] == "info"


def test_operator_message_for_pre_solve_failure() -> None:
    msg = build_operator_message(
        signal=WinnerSignal.PRE_SOLVE_FAILURE,
        cvar_limit=None, min_achievable_cvar=None, expected_return=None,
    )
    assert msg is not None
    assert msg["severity"] == "error"


def test_cvar_infeasible_requires_both_limits() -> None:
    # Missing min_achievable_cvar falls through to DEGRADED_OTHER.
    sig = compute_winner_signal(
        winning_phase="phase_3_min_cvar",
        cvar_within_limit=False,
        cvar_limit=0.05,
        min_achievable_cvar=None,
    )
    assert sig is WinnerSignal.DEGRADED_OTHER

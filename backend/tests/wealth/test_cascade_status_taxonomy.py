"""PR-Q140 — cascade status taxonomy tests.

Covers the 5 acceptance criteria:

1. Phase 3 above limit → run.status = "mandate_infeasible"
2. Upstream heuristic → run.status = "degraded"
3. Phase 1 optimal → run.status = "succeeded"
4. CVaR degraded_reason propagates to ValidationStatus
5. State machine blocks approval on mandate_infeasible
"""

from __future__ import annotations

from typing import Any

from app.domains.wealth.workers.construction_run_executor import (
    _build_cascade_telemetry,
)
from vertical_engines.wealth.model_portfolio.state_machine import (
    ACTION_APPROVE,
    ACTION_REBUILD_DRAFT,
    ACTION_REJECT,
    ACTION_VALIDATE,
    ApprovalPolicy,
    ValidationStatus,
    compute_allowed_actions,
)
from vertical_engines.wealth.model_portfolio.validation_gate import (
    ValidationDbContext,
    validate_construction,
)

# ── Helpers ──────────────────────────────────────────────────────


def _phase_3_above_limit_block() -> dict[str, Any]:
    """Canonical Conservative-like block: Phase 1 infeasible, Phase 3 above limit."""
    return {
        "phase_attempts": [
            {
                "phase": "phase_1_ru_max_return", "status": "infeasible",
                "solver": None, "objective_value": None, "wall_ms": 312,
                "infeasibility_reason": "PRIMAL_INFEASIBLE",
                "cvar_at_solution": None, "cvar_at_solution_cf": None,
                "cvar_limit_effective": 0.05, "cvar_within_limit": None,
            },
            {
                "phase": "phase_2_ru_robust", "status": "skipped", "solver": None,
                "objective_value": None, "wall_ms": 0,
                "infeasibility_reason": None,
            },
            {
                "phase": "phase_3_min_cvar", "status": "succeeded",
                "solver": "CLARABEL", "objective_value": 0.0635,
                "wall_ms": 89, "infeasibility_reason": None,
                "cvar_at_solution": 0.0635, "cvar_at_solution_cf": 0.071,
                "cvar_limit_effective": 0.05, "cvar_within_limit": False,
            },
        ],
        "winning_phase": "phase_3_min_cvar",
        "min_achievable_cvar": 0.0635,
        "achievable_return_band": {
            "lower": 0.0998, "upper": 0.0998,
            "lower_at_cvar": 0.0635, "upper_at_cvar": 0.0635,
        },
    }


def _phase_1_winner_block() -> dict[str, Any]:
    """Phase 1 succeeds — golden path."""
    return {
        "phase_attempts": [
            {
                "phase": "phase_1_ru_max_return", "status": "succeeded",
                "solver": "CLARABEL", "objective_value": 0.1085, "wall_ms": 287,
                "infeasibility_reason": None,
                "cvar_at_solution": 0.047, "cvar_at_solution_cf": 0.053,
                "cvar_limit_effective": 0.05, "cvar_within_limit": True,
            },
            {
                "phase": "phase_2_ru_robust", "status": "skipped", "solver": None,
                "objective_value": None, "wall_ms": 0,
                "infeasibility_reason": None,
            },
            {
                "phase": "phase_3_min_cvar", "status": "succeeded",
                "solver": "CLARABEL", "objective_value": 0.0352, "wall_ms": 91,
                "infeasibility_reason": None,
                "cvar_at_solution": 0.0352, "cvar_at_solution_cf": 0.040,
                "cvar_limit_effective": 0.05, "cvar_within_limit": True,
            },
        ],
        "winning_phase": "phase_1_ru_max_return",
        "min_achievable_cvar": 0.0352,
        "achievable_return_band": {
            "lower": 0.0975, "upper": 0.1085,
            "lower_at_cvar": 0.0352, "upper_at_cvar": 0.047,
        },
    }


def _base_payload() -> dict[str, Any]:
    """A known-good construction run payload that passes all 16 checks."""
    return {
        "as_of_date": "2026-04-29",
        "weights_proposed": {
            "11111111-1111-1111-1111-111111111111": 0.20,
            "22222222-2222-2222-2222-222222222222": 0.20,
            "33333333-3333-3333-3333-333333333333": 0.20,
            "44444444-4444-4444-4444-444444444444": 0.20,
            "55555555-5555-5555-5555-555555555555": 0.20,
        },
        "calibration_snapshot": {
            "cvar_limit": 0.05,
            "max_single_fund_weight": 0.25,
            "turnover_cap": 0.30,
            "bl_enabled": False,
            "garch_enabled": False,
        },
        "ex_ante_metrics": {
            "cvar_95": -0.04,
            "expected_return": 0.08,
            "turnover": 0.10,
        },
        "funds": [
            {"instrument_id": "11111111-1111-1111-1111-111111111111",
             "block_id": "na_equity_large", "weight": 0.20},
            {"instrument_id": "22222222-2222-2222-2222-222222222222",
             "block_id": "na_equity_large", "weight": 0.20},
            {"instrument_id": "33333333-3333-3333-3333-333333333333",
             "block_id": "fi_treasury", "weight": 0.20},
            {"instrument_id": "44444444-4444-4444-4444-444444444444",
             "block_id": "fi_treasury", "weight": 0.20},
            {"instrument_id": "55555555-5555-5555-5555-555555555555",
             "block_id": "intl_equity_dm", "weight": 0.20},
        ],
        "stress_results": [
            {"scenario": "gfc_2008", "nav_impact_pct": -0.15},
            {"scenario": "covid_2020", "nav_impact_pct": -0.10},
        ],
        "optimizer_trace": {},
        "statistical_inputs": {},
        "factor_exposure": {"average_r_squared": 0.65},
    }


def _base_db_context() -> ValidationDbContext:
    ids = frozenset({
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
        "33333333-3333-3333-3333-333333333333",
        "44444444-4444-4444-4444-444444444444",
        "55555555-5555-5555-5555-555555555555",
    })
    return ValidationDbContext(
        approved_instrument_ids=ids,
        block_constraints={
            "na_equity_large": (0.0, 0.50),
            "fi_treasury": (0.0, 0.50),
            "intl_equity_dm": (0.0, 0.50),
        },
        nav_latest_date={
            "11111111-1111-1111-1111-111111111111": "2026-04-28",
            "22222222-2222-2222-2222-222222222222": "2026-04-28",
            "33333333-3333-3333-3333-333333333333": "2026-04-28",
            "44444444-4444-4444-4444-444444444444": "2026-04-28",
            "55555555-5555-5555-5555-555555555555": "2026-04-28",
        },
    )


# ── Test 1: Phase 3 above limit → mandate_infeasible ────────────


def test_phase_3_above_limit_yields_mandate_infeasible() -> None:
    """C-01: Phase 3 winner with cvar_above_limit must produce
    run.status = 'mandate_infeasible', not 'degraded'."""
    telemetry, status = _build_cascade_telemetry(
        cascade_block=_phase_3_above_limit_block(),
        optimizer_trace={"status": "degraded"},
        cvar_limit=0.05,
    )
    assert status == "mandate_infeasible"
    assert telemetry["cascade_summary"] == "phase_3_min_cvar_above_limit"
    # Operator signal still present for frontend rendering.
    sig = telemetry["operator_signal"]
    assert sig is not None
    assert sig["kind"] == "cvar_limit_below_universe_floor"


# ── Test 2: Upstream heuristic → degraded ────────────────────────


def test_upstream_heuristic_yields_degraded() -> None:
    """C-01: Covariance fallback / technical degradation must stay 'degraded'."""
    cascade_block: dict[str, Any] = {
        "phase_attempts": [],
        "winning_phase": "upstream_heuristic",
    }
    telemetry, status = _build_cascade_telemetry(
        cascade_block=cascade_block,
        optimizer_trace={"status": "fallback:insufficient_fund_data"},
        cvar_limit=0.05,
    )
    assert status == "degraded"
    assert telemetry["cascade_summary"] == "upstream_heuristic"
    sig = telemetry["operator_signal"]
    assert sig is not None
    assert sig["kind"] == "upstream_data_missing"


# ── Test 3: Phase 1 optimal → succeeded ─────────────────────────


def test_phase_1_optimal_yields_succeeded() -> None:
    """Golden path: Phase 1 wins → run.status = 'succeeded'."""
    telemetry, status = _build_cascade_telemetry(
        cascade_block=_phase_1_winner_block(),
        optimizer_trace={"status": "optimal"},
        cvar_limit=0.05,
    )
    assert status == "succeeded"
    assert telemetry["cascade_summary"] == "phase_1_succeeded"
    assert telemetry["operator_signal"] is None


# ── Test 4: CVaR degraded_reason propagates to validation ────────


def test_cvar_service_degraded_reason_propagates_to_validation() -> None:
    """C-11: NaN CVaR with degraded_reason from cvar_service must appear
    on the ValidationCheck and in the ValidationResult's severity_breakdown."""
    payload = _base_payload()
    # Simulate NaN CVaR from cvar_service with degraded_reason.
    payload["ex_ante_metrics"]["cvar_95"] = float("nan")
    payload["ex_ante_metrics"]["cvar_degraded_reason"] = "insufficient_obs_12"

    result = validate_construction(payload, db_context=_base_db_context())

    # Find the CVaR check.
    cvar_check = next(c for c in result.checks if c.id == "cvar_within_limit")
    assert not cvar_check.passed
    assert cvar_check.degraded_reason == "insufficient_obs_12"
    assert "NaN" in cvar_check.explanation

    # severity_breakdown must include the CVaR check under "block".
    assert "block" in result.severity_breakdown
    assert "cvar_within_limit" in result.severity_breakdown["block"]


# ── Test 5: State machine blocks approval on mandate_infeasible ──


def test_state_machine_blocks_approval_on_mandate_infeasible() -> None:
    """C-01: Portfolio with run.status = 'mandate_infeasible' must NOT
    have the approve action, regardless of validation.passed."""
    # Even with validation.passed=True (all 16 gate checks passed),
    # mandate_infeasible should block approval.
    validation = ValidationStatus(
        has_run=True,
        passed=True,
        run_status="mandate_infeasible",
    )
    actions = compute_allowed_actions("constructed", validation=validation)
    assert ACTION_APPROVE not in actions
    # validate, reject, rebuild_draft should still be available.
    assert ACTION_VALIDATE in actions
    assert ACTION_REJECT in actions
    assert ACTION_REBUILD_DRAFT in actions

    # Also verify soft-block policy cannot override mandate_infeasible.
    policy = ApprovalPolicy(require_construction_for_approve=False)
    actions_soft = compute_allowed_actions(
        "constructed", validation=validation, policy=policy,
    )
    assert ACTION_APPROVE not in actions_soft


# ── Bonus: ensure existing 'degraded' run_status does NOT block ──


def test_state_machine_allows_approval_on_degraded_run_status() -> None:
    """Backward compat: a technically degraded run with passing validation
    should still allow approval (existing behavior preserved)."""
    validation = ValidationStatus(
        has_run=True,
        passed=True,
        run_status="degraded",
    )
    actions = compute_allowed_actions("constructed", validation=validation)
    assert ACTION_APPROVE in actions


def test_state_machine_allows_approval_on_none_run_status() -> None:
    """Backward compat: legacy ValidationStatus without run_status
    (defaulting to None) should behave identically to pre-Q140."""
    validation = ValidationStatus(has_run=True, passed=True)
    actions = compute_allowed_actions("constructed", validation=validation)
    assert ACTION_APPROVE in actions

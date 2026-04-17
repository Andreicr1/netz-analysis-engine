"""PR-A11/A12 — executor-side cascade telemetry builder tests.

These exercise ``_build_cascade_telemetry`` (pure function) without a DB
so they run offline. End-to-end persistence is validated by the F.1
live-DB smoke in the prompt.

PR-A12 reshaped the cascade into 3 RU phases; tests updated in lockstep.
Covers:

- Phase 3 winner ABOVE limit → degraded + cvar_limit_below_universe_floor
- Phase 1 winner → succeeded + null operator_signal
- Upstream heuristic (compute_fund_level_inputs failed) → degraded
- Constraint polytope empty → failed
- SSE vocabulary sanitization regression guard
"""

from __future__ import annotations

import json

from app.domains.wealth.workers.construction_run_executor import (
    _build_cascade_telemetry,
)


def _phase_3_above_limit_block() -> dict:
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


def test_phase_3_above_limit_yields_degraded_and_floor_signal() -> None:
    telemetry, status = _build_cascade_telemetry(
        cascade_block=_phase_3_above_limit_block(),
        optimizer_trace={"status": "degraded"},
        cvar_limit=0.05,
    )
    assert status == "degraded"
    assert telemetry["cascade_summary"] == "phase_3_min_cvar_above_limit"
    assert telemetry["min_achievable_cvar"] == 0.0635
    band = telemetry["achievable_return_band"]
    assert band["lower"] == band["upper"] == 0.0998
    sig = telemetry["operator_signal"]
    assert sig is not None
    assert sig["kind"] == "cvar_limit_below_universe_floor"
    assert sig["binding"] == "tail_risk_floor"
    assert sig["min_achievable_cvar"] == 0.0635
    assert sig["user_cvar_limit"] == 0.05
    # All 3 phases present
    phases = [a["phase"] for a in telemetry["phase_attempts"]]
    assert phases == [
        "phase_1_ru_max_return",
        "phase_2_ru_robust",
        "phase_3_min_cvar",
    ]


def test_phase_1_winner_yields_clean_telemetry() -> None:
    cascade_block = {
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
    telemetry, status = _build_cascade_telemetry(
        cascade_block=cascade_block,
        optimizer_trace={"status": "optimal"},
        cvar_limit=0.05,
    )
    assert status == "succeeded"
    assert telemetry["cascade_summary"] == "phase_1_succeeded"
    assert telemetry["operator_signal"] is None
    assert telemetry["min_achievable_cvar"] == 0.0352


def test_upstream_heuristic_yields_degraded_and_data_signal() -> None:
    cascade_block = {
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
    assert sig["binding"] == "returns_quality"


def test_constraint_polytope_empty_yields_failed_status() -> None:
    telemetry, status = _build_cascade_telemetry(
        cascade_block={
            "phase_attempts": [
                {
                    "phase": "phase_3_min_cvar", "status": "solver_failed",
                    "solver": "CLARABEL", "objective_value": None, "wall_ms": 10,
                    "infeasibility_reason": "infeasible",
                    "cvar_limit_effective": 0.05,
                },
            ],
            "winning_phase": None,
        },
        optimizer_trace={"status": "constraint_polytope_empty"},
        cvar_limit=0.05,
    )
    assert status == "failed"
    assert telemetry["cascade_summary"] == "constraint_polytope_empty"
    assert telemetry["operator_signal"]["kind"] == "constraint_polytope_empty"


def test_empty_block_returns_legacy_sentinel() -> None:
    # Mocked _run_construction_async paths that don't emit a ``cascade``
    # key must not flip the run status — caller falls back to the legacy
    # solver-string check when status=="unknown".
    telemetry, status = _build_cascade_telemetry(
        cascade_block={},
        optimizer_trace={"solver": "heuristic_fallback"},
        cvar_limit=None,
    )
    assert telemetry == {}
    assert status == "unknown"


def test_sse_payload_is_sanitized() -> None:
    """The SSE-bound subset must not leak solver names, internal phase keys,
    or math jargon. Regression guard for the PR-A12 vocabulary allowlist."""
    telemetry, _ = _build_cascade_telemetry(
        cascade_block=_phase_3_above_limit_block(),
        optimizer_trace={"status": "degraded"},
        cvar_limit=0.05,
    )
    sse_payload = {
        "cascade_summary": telemetry["cascade_summary"],
        "operator_signal": telemetry["operator_signal"],
        "min_achievable_cvar": telemetry["min_achievable_cvar"],
        "achievable_return_band": telemetry["achievable_return_band"],
    }
    payload_json = json.dumps(sse_payload)
    forbidden = [
        "CLARABEL", "SCS", "phase_attempts", "cvar_coeff",
        "Rockafellar-Uryasev", "Cornish-Fisher", "zeta", "u_i",
        "min_variance_fallback", "heuristic_fallback",
    ]
    for tok in forbidden:
        assert tok not in payload_json, f"forbidden token {tok!r} leaked"

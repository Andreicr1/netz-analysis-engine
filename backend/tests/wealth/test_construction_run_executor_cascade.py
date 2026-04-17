"""PR-A11 — executor-side cascade telemetry builder tests.

These exercise ``_build_cascade_telemetry`` (pure function) without a DB
so they can run offline. End-to-end persistence is validated by the F.1
live-DB smoke in the prompt.

Covers:
- E.4 Phase 3 fallback → degraded + risk_budget operator_signal
- E.5 Phase 2 winner → succeeded + null operator_signal
- E.6 Sanitization: SSE-bound payload contains only the public subset
"""

from __future__ import annotations

import json

from app.domains.wealth.workers.construction_run_executor import (
    _build_cascade_telemetry,
)


def _phase_3_fallback_block() -> dict:
    return {
        "phase_attempts": [
            {
                "phase": "primary", "status": "succeeded", "solver": "CLARABEL",
                "objective_value": 0.131991, "wall_ms": 4321,
                "infeasibility_reason": None,
                "cvar_at_solution": -0.15, "cvar_limit_effective": -0.05,
                "cvar_within_limit": False,
            },
            {
                "phase": "robust", "status": "skipped", "solver": None,
                "objective_value": None, "wall_ms": 0,
                "infeasibility_reason": None,
            },
            {
                "phase": "variance_capped", "status": "infeasible",
                "solver": "CLARABEL", "objective_value": None, "wall_ms": 217,
                "infeasibility_reason": "infeasible",
                "max_var": 0.000071, "max_vol_target": 0.0084,
                "cvar_coeff": 2.85, "cf_normal_ratio": 1.3,
                "phase2_limit": -0.05,
            },
            {
                "phase": "min_variance", "status": "succeeded",
                "solver": "CLARABEL", "objective_value": 0.000868,
                "wall_ms": 89, "infeasibility_reason": None,
                "min_achievable_variance": 0.000868,
                "min_achievable_vol": 0.02946,
            },
        ],
        "winning_phase": "min_variance",
    }


def test_phase_3_fallback_yields_degraded_and_risk_budget_signal() -> None:
    telemetry, status = _build_cascade_telemetry(
        cascade_block=_phase_3_fallback_block(),
        optimizer_trace={"status": "optimal:min_variance_fallback"},
        cvar_limit=-0.05,
    )
    assert status == "degraded"
    assert telemetry["cascade_summary"] == "phase_3_fallback"
    assert telemetry["phase2_max_var"] == 0.000071
    assert telemetry["min_achievable_variance"] == 0.000868
    assert telemetry["feasibility_gap_pct"] is not None
    assert telemetry["feasibility_gap_pct"] > 80
    sig = telemetry["operator_signal"]
    assert sig is not None
    assert sig["kind"] == "constraint_binding"
    assert sig["binding"] == "risk_budget"
    assert sig["message_key"] == "cvar_limit_below_universe_floor"
    # Phase keys normalized to public names + at least 4 attempts
    phases = [a["phase"] for a in telemetry["phase_attempts"]]
    assert "phase_1" in phases
    assert "phase_2_variance_capped" in phases
    assert "phase_3_min_variance" in phases
    assert len(telemetry["phase_attempts"]) >= 4


def test_phase_2_winner_yields_clean_telemetry() -> None:
    cascade_block = {
        "phase_attempts": [
            {
                "phase": "primary", "status": "succeeded", "solver": "CLARABEL",
                "objective_value": 0.1, "wall_ms": 100,
                "infeasibility_reason": None,
                "cvar_at_solution": -0.10, "cvar_limit_effective": -0.08,
                "cvar_within_limit": False,
            },
            {"phase": "robust", "status": "skipped", "solver": None,
             "objective_value": None, "wall_ms": 0, "infeasibility_reason": None},
            {
                "phase": "variance_capped", "status": "succeeded",
                "solver": "CLARABEL", "objective_value": 0.09,
                "wall_ms": 150, "infeasibility_reason": None,
                "max_var": 0.002, "max_vol_target": 0.045,
                "cvar_coeff": 2.85, "cf_normal_ratio": 1.3,
                "phase2_limit": -0.08,
            },
        ],
        "winning_phase": "variance_capped",
    }
    telemetry, status = _build_cascade_telemetry(
        cascade_block=cascade_block,
        optimizer_trace={"status": "optimal:cvar_constrained"},
        cvar_limit=-0.08,
    )
    assert status == "succeeded"
    assert telemetry["cascade_summary"] == "phase_2_succeeded"
    assert telemetry["operator_signal"] is None
    assert telemetry["feasibility_gap_pct"] is None


def test_heuristic_fallback_yields_degraded_and_solver_signal() -> None:
    cascade_block = {
        "phase_attempts": [],
        "winning_phase": "heuristic",
    }
    telemetry, status = _build_cascade_telemetry(
        cascade_block=cascade_block,
        optimizer_trace={"status": "fallback:insufficient_fund_data"},
        cvar_limit=-0.05,
    )
    assert status == "degraded"
    assert telemetry["cascade_summary"] == "heuristic_fallback"
    sig = telemetry["operator_signal"]
    assert sig is not None
    assert sig["binding"] == "solver"
    assert sig["message_key"] == "convex_phases_exhausted"


def test_cascade_exhausted_yields_failed_status() -> None:
    # At least one recorded attempt (in failed state) distinguishes a
    # genuine cascade exhaustion from the legacy/empty sentinel path.
    telemetry, status = _build_cascade_telemetry(
        cascade_block={
            "phase_attempts": [
                {"phase": "primary", "status": "solver_failed", "solver": None,
                 "objective_value": None, "wall_ms": 10,
                 "infeasibility_reason": "Both CLARABEL and SCS failed"},
            ],
            "winning_phase": None,
        },
        optimizer_trace={"status": "solver_failed"},
        cvar_limit=None,
    )
    assert status == "failed"
    assert telemetry["cascade_summary"] == "cascade_exhausted"
    assert telemetry["operator_signal"]["kind"] == "cascade_failure"


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
    """The SSE-bound subset ({cascade_summary, operator_signal,
    feasibility_gap_pct}) must not leak solver names, internal phase keys,
    or math jargon. Regression guard for the vocabulary allowlist."""
    telemetry, _ = _build_cascade_telemetry(
        cascade_block=_phase_3_fallback_block(),
        optimizer_trace={"status": "optimal:min_variance_fallback"},
        cvar_limit=-0.05,
    )
    sse_payload = {
        "cascade_summary": telemetry["cascade_summary"],
        "operator_signal": telemetry["operator_signal"],
        "feasibility_gap_pct": telemetry["feasibility_gap_pct"],
    }
    payload_json = json.dumps(sse_payload)
    assert "CLARABEL" not in payload_json
    assert "SCS" not in payload_json
    assert "phase_attempts" not in payload_json
    assert "phase_2_variance_capped" not in payload_json
    assert "min_variance_fallback" not in payload_json
    assert "cvar_coeff" not in payload_json
    assert "κ" not in payload_json

"""PR-A14 — universe coverage gate + secondary operator signal tests.

Exercises ``_build_cascade_telemetry`` with coverage-bearing cascade blocks
to lock the three new behaviours:

- Coverage block is surfaced on ``cascade_telemetry.coverage``
- Secondary ``operator_signal`` fires when pct_covered < 0.85
- Primary signal kind swaps to ``universe_coverage_insufficient`` on the
  hard-fail path (coverage < 0.20) routed via ``upstream_heuristic``

Renormalisation itself was shipped in PR-A7 and is covered by the live-DB
smoke — A14 is observability-only.
"""

from __future__ import annotations

from app.domains.wealth.workers.construction_run_executor import (
    _build_cascade_telemetry,
)


def _phase_1_succeeded_block(coverage: dict | None) -> dict:
    return {
        "phase_attempts": [
            {
                "phase": "phase_1_ru_max_return", "status": "succeeded",
                "solver": "CLARABEL", "objective_value": 0.11, "wall_ms": 220,
                "infeasibility_reason": None,
                "cvar_at_solution": 0.04, "cvar_at_solution_cf": 0.05,
                "cvar_limit_effective": 0.05, "cvar_within_limit": True,
            },
            {
                "phase": "phase_2_ru_robust", "status": "skipped", "solver": None,
                "objective_value": None, "wall_ms": 0,
                "infeasibility_reason": None,
            },
            {
                "phase": "phase_3_min_cvar", "status": "succeeded",
                "solver": "CLARABEL", "objective_value": 0.03, "wall_ms": 70,
                "infeasibility_reason": None,
                "cvar_at_solution": 0.03, "cvar_at_solution_cf": 0.035,
                "cvar_limit_effective": 0.05, "cvar_within_limit": True,
            },
        ],
        "winning_phase": "phase_1_ru_max_return",
        "min_achievable_cvar": 0.03,
        "achievable_return_band": {
            "lower": 0.09, "upper": 0.11,
            "lower_at_cvar": 0.03, "upper_at_cvar": 0.04,
        },
        "coverage": coverage,
    }


def _full_coverage_payload() -> dict:
    return {
        "pct_covered": 1.0,
        "n_total_blocks": 11,
        "n_covered_blocks": 11,
        "covered_blocks": [f"blk_{i}" for i in range(11)],
        "missing_blocks": [],
        "renormalization_scale": 1.0,
        "hard_fail": False,
    }


def _partial_coverage_payload(pct: float, missing: int) -> dict:
    return {
        "pct_covered": pct,
        "n_total_blocks": 11,
        "n_covered_blocks": 11 - missing,
        "covered_blocks": [f"blk_{i}" for i in range(11 - missing)],
        "missing_blocks": [f"blk_{i}" for i in range(11 - missing, 11)],
        "renormalization_scale": round(1.0 / pct, 4) if pct > 0 else None,
        "hard_fail": pct < 0.20,
    }


def test_full_coverage_no_secondary_signal() -> None:
    telemetry, status = _build_cascade_telemetry(
        cascade_block=_phase_1_succeeded_block(_full_coverage_payload()),
        optimizer_trace={"status": "optimal"},
        cvar_limit=0.05,
    )
    assert status == "succeeded"
    assert telemetry["coverage"]["pct_covered"] == 1.0
    assert telemetry["coverage"]["missing_blocks"] == []
    # Primary preserved as None (implicit feasible) — no secondary attached.
    assert telemetry["operator_signal"] is None


def test_coverage_below_85_triggers_secondary() -> None:
    telemetry, status = _build_cascade_telemetry(
        cascade_block=_phase_1_succeeded_block(
            _partial_coverage_payload(0.61, missing=5),
        ),
        optimizer_trace={"status": "optimal"},
        cvar_limit=0.05,
    )
    assert status == "succeeded"
    sig = telemetry["operator_signal"]
    assert sig is not None, "primary must be synthesised so secondary surfaces"
    assert sig["kind"] == "feasible"
    assert sig["secondary"] is not None
    assert sig["secondary"]["kind"] == "universe_coverage_insufficient"
    assert sig["secondary"]["pct_covered"] == 0.61
    assert sig["secondary"]["missing_blocks_count"] == 5
    assert sig["secondary"]["message_key"] == "expand_universe_recommended"


def test_coverage_above_85_no_secondary() -> None:
    telemetry, _ = _build_cascade_telemetry(
        cascade_block=_phase_1_succeeded_block(
            _partial_coverage_payload(0.90, missing=1),
        ),
        optimizer_trace={"status": "optimal"},
        cvar_limit=0.05,
    )
    # 0.90 >= 0.85 → primary stays None (no secondary attached).
    assert telemetry["operator_signal"] is None
    assert telemetry["coverage"]["pct_covered"] == 0.90


def test_coverage_at_exactly_85_no_secondary() -> None:
    telemetry, _ = _build_cascade_telemetry(
        cascade_block=_phase_1_succeeded_block(
            _partial_coverage_payload(0.85, missing=2),
        ),
        optimizer_trace={"status": "optimal"},
        cvar_limit=0.05,
    )
    # Boundary — 0.85 is NOT below 0.85 (strict inequality), so no secondary.
    assert telemetry["operator_signal"] is None


def test_secondary_coexists_with_primary_below_floor() -> None:
    """Phase 3 above-limit primary + coverage < 0.85 → both signals present."""
    cascade_block = {
        "phase_attempts": [
            {
                "phase": "phase_1_ru_max_return", "status": "infeasible",
                "solver": None, "objective_value": None, "wall_ms": 100,
                "infeasibility_reason": "PRIMAL_INFEASIBLE",
            },
            {
                "phase": "phase_2_ru_robust", "status": "skipped", "solver": None,
                "objective_value": None, "wall_ms": 0,
                "infeasibility_reason": None,
            },
            {
                "phase": "phase_3_min_cvar", "status": "succeeded",
                "solver": "CLARABEL", "objective_value": 0.06, "wall_ms": 80,
                "infeasibility_reason": None,
                "cvar_at_solution": 0.06, "cvar_at_solution_cf": 0.07,
                "cvar_limit_effective": 0.05, "cvar_within_limit": False,
            },
        ],
        "winning_phase": "phase_3_min_cvar",
        "min_achievable_cvar": 0.06,
        "achievable_return_band": {
            "lower": 0.08, "upper": 0.08,
            "lower_at_cvar": 0.06, "upper_at_cvar": 0.06,
        },
        "coverage": _partial_coverage_payload(0.61, missing=5),
    }
    telemetry, status = _build_cascade_telemetry(
        cascade_block=cascade_block,
        optimizer_trace={"status": "degraded"},
        cvar_limit=0.05,
    )
    assert status == "degraded"
    sig = telemetry["operator_signal"]
    assert sig["kind"] == "cvar_limit_below_universe_floor"
    assert sig["secondary"] is not None
    assert sig["secondary"]["kind"] == "universe_coverage_insufficient"


def test_hard_fail_swaps_primary_kind_on_upstream_heuristic() -> None:
    cascade_block = {
        "phase_attempts": [],
        "winning_phase": "upstream_heuristic",
        "coverage": _partial_coverage_payload(0.15, missing=9),
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
    assert sig["kind"] == "universe_coverage_insufficient"
    assert sig["pct_covered"] == 0.15
    assert sig["missing_blocks_count"] == 9
    # Hard-fail uses primary slot — secondary must NOT duplicate.
    assert sig.get("secondary") is None


def test_upstream_heuristic_without_hard_fail_keeps_data_missing_kind() -> None:
    cascade_block = {
        "phase_attempts": [],
        "winning_phase": "upstream_heuristic",
        # Coverage fine (full) but upstream failed for a different reason.
        "coverage": _full_coverage_payload(),
    }
    telemetry, _ = _build_cascade_telemetry(
        cascade_block=cascade_block,
        optimizer_trace={"status": "fallback:insufficient_fund_data"},
        cvar_limit=0.05,
    )
    sig = telemetry["operator_signal"]
    assert sig["kind"] == "upstream_data_missing"
    # No secondary because pct_covered == 1.0 is above the 0.85 threshold.
    assert sig.get("secondary") is None


def test_coverage_absent_is_legacy_compatible() -> None:
    """Cascade blocks that predate A14 (no ``coverage`` key) must not crash
    and must not invent a secondary signal."""
    cascade_block = {
        "phase_attempts": [
            {
                "phase": "phase_1_ru_max_return", "status": "succeeded",
                "solver": "CLARABEL", "objective_value": 0.10, "wall_ms": 200,
                "infeasibility_reason": None,
                "cvar_at_solution": 0.04, "cvar_at_solution_cf": 0.05,
                "cvar_limit_effective": 0.05, "cvar_within_limit": True,
            },
        ],
        "winning_phase": "phase_1_ru_max_return",
    }
    telemetry, status = _build_cascade_telemetry(
        cascade_block=cascade_block,
        optimizer_trace={"status": "optimal"},
        cvar_limit=0.05,
    )
    assert status == "succeeded"
    assert telemetry["operator_signal"] is None
    assert telemetry["coverage"] is None

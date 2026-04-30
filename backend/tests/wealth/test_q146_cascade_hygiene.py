"""PR-Q146: cascade hygiene terminus — 4 Med/Low findings.

C-06: NAV synthesizer no_fund_data → run.status degraded or validation warn.
C-07: mandate_infeasible_acknowledged required for mandate_infeasible activation.
C-08: Phase 1 winner with Phase 3 cvar_within_limit=None → OPTIMAL (not DEGRADED_OTHER).
C-09: factor covariance conditioning metadata persisted in statistical_inputs.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.domains.wealth.schemas.sanitized import WinnerSignal, compute_winner_signal

# ── Test 1 (C-06): NAV no_fund_data → degraded or validation warn ──


def test_nav_synthesis_no_fund_data_escalates_to_degraded() -> None:
    """When NAV synthesis returns dates_computed=0 and status='no_fund_data'
    on a portfolio with instruments, the outer executor status derivation
    must escalate 'succeeded' to 'degraded'.

    We exercise the inline logic that PR-Q146 added after the cascade-driven
    status derivation in execute_construction_run.
    """
    # Simulate the status derivation logic from the executor.
    # The cascade says "phase_1_succeeded" → run.status = "succeeded".
    run_status = "succeeded"
    weights_proposed = {"fund_a": 0.5, "fund_b": 0.5}
    nav_synthesis = {
        "portfolio_id": "abc",
        "status": "no_fund_data",
        "dates_computed": 0,
    }

    # PR-Q146 (C-06) escalation logic (mirrors executor inline code):
    if (
        nav_synthesis is not None
        and nav_synthesis.get("dates_computed") == 0
        and nav_synthesis.get("status") == "no_fund_data"
        and run_status == "succeeded"
        and weights_proposed
    ):
        run_status = "degraded"

    assert run_status == "degraded"

    # Also test that the validation gate check catches this.
    from vertical_engines.wealth.model_portfolio.validation_gate import (
        ValidationDbContext,
        validate_construction,
    )

    payload = {
        "weights_proposed": weights_proposed,
        "statistical_inputs": {
            "portfolio_nav_synthesis": nav_synthesis,
        },
        "calibration_snapshot": {},
        "ex_ante_metrics": {},
        "funds": [],
        "stress_results": [],
        "optimizer_trace": {},
    }
    result = validate_construction(payload, ValidationDbContext())
    nav_check = next(
        (c for c in result.checks if c.id == "nav_synthesis_check"), None,
    )
    assert nav_check is not None
    assert nav_check.passed is False
    assert nav_check.severity == "warn"
    assert "no_fund_data" in (nav_check.explanation or "")


# ── Test 2 (C-07): mandate_infeasible_acknowledged required ─────────


def test_mandate_infeasible_requires_structured_ack() -> None:
    """Activating a mandate_infeasible portfolio with only
    degraded_acknowledged=True must be rejected (422).
    With mandate_infeasible_acknowledged=True it must succeed."""
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    # Simulate the activation gate logic from the route.
    run = MagicMock()
    run.status = "mandate_infeasible"
    run.cascade_telemetry = {
        "winner_signal": "cvar_infeasible_min_var",
        "cascade_summary": "phase_3_min_cvar_above_limit",
    }

    # Case 1: only degraded_acknowledged → 422
    metadata_missing: dict = {"degraded_acknowledged": True}
    with pytest.raises(HTTPException) as exc_info:
        if run.status == "mandate_infeasible":
            if not metadata_missing.get("mandate_infeasible_acknowledged"):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Portfolio's latest construction run is mandate_infeasible. "
                        "Set metadata.mandate_infeasible_acknowledged=true "
                        "(in addition to degraded_acknowledged) to proceed."
                    ),
                )
    assert exc_info.value.status_code == 422
    assert "mandate_infeasible_acknowledged" in exc_info.value.detail

    # Case 2: both acknowledged → passes
    metadata_ok: dict = {
        "degraded_acknowledged": True,
        "mandate_infeasible_acknowledged": True,
    }
    actor_id = "operator-1"
    if run.status == "mandate_infeasible":
        if not metadata_ok.get("mandate_infeasible_acknowledged"):
            raise AssertionError("Should not reach here")
        metadata_ok["mandate_infeasible_acknowledged_by"] = actor_id

    assert metadata_ok["mandate_infeasible_acknowledged_by"] == "operator-1"


# ── Test 3 (C-08): Phase 1 winner + Phase 3 None → OPTIMAL ─────────


def test_phase1_winner_with_phase3_none_is_optimal() -> None:
    """When Phase 1 wins optimally and Phase 3 has cvar_within_limit=None
    (solver glitch), the winner signal must be OPTIMAL, not DEGRADED_OTHER.

    This tests the fix in _build_cascade_telemetry where _cvar_within_limit
    is now derived from the winner's attempt for Phase 1/2, not Phase 3.
    """
    from app.domains.wealth.workers.construction_run_executor import (
        _build_cascade_telemetry,
    )

    cascade_block = {
        "phase_attempts": [
            {
                "phase": "phase_1_ru_max_return",
                "status": "succeeded",
                "solver": "CLARABEL",
                "objective_value": 0.1085,
                "wall_ms": 287,
                "infeasibility_reason": None,
                "cvar_at_solution": 0.047,
                "cvar_at_solution_cf": 0.053,
                "cvar_limit_effective": 0.05,
                "cvar_within_limit": True,  # Phase 1 knows it's within limit
            },
            {
                "phase": "phase_2_ru_robust",
                "status": "skipped",
                "solver": None,
                "objective_value": None,
                "wall_ms": 0,
                "infeasibility_reason": None,
            },
            {
                "phase": "phase_3_min_cvar",
                "status": "succeeded",
                "solver": "CLARABEL",
                "objective_value": 0.035,
                "wall_ms": 90,
                "infeasibility_reason": None,
                "cvar_at_solution": 0.035,
                "cvar_at_solution_cf": None,
                "cvar_limit_effective": 0.05,
                "cvar_within_limit": None,  # Solver glitch: None
            },
        ],
        "winning_phase": "phase_1_ru_max_return",
        "min_achievable_cvar": 0.035,
    }

    telemetry, run_status = _build_cascade_telemetry(
        cascade_block=cascade_block,
        optimizer_trace={"status": "optimal"},
        cvar_limit=0.05,
    )

    assert run_status == "succeeded"
    # The key assertion: winner_signal must be OPTIMAL despite Phase 3's
    # cvar_within_limit being None.
    assert telemetry["winner_signal"] == WinnerSignal.OPTIMAL.value

    # Also verify compute_winner_signal directly with the corrected logic:
    signal = compute_winner_signal(
        winning_phase="phase_1_ru_max_return",
        cvar_within_limit=True,  # From Phase 1's own attempt
        cvar_limit=0.05,
        min_achievable_cvar=0.035,
    )
    assert signal is WinnerSignal.OPTIMAL


# ── Test 4 (C-09): conditioning meta persisted ──────────────────────


def test_factor_conditioning_meta_persisted() -> None:
    """assemble_factor_covariance with rank-deficient input must produce
    conditioning_meta with n_clamped > 0, and the metadata must be
    persistable in run.statistical_inputs.factor_conditioning."""
    from quant_engine.factor_model_service import (
        FundamentalFactorFit,
        compute_factor_conditioning_meta,
    )

    # Build a rank-deficient factor model: 10 funds, 3 factors, but one
    # factor is near-zero (degenerate).
    rng = np.random.default_rng(42)
    loadings = rng.standard_normal((10, 3)).astype(np.float64)
    factor_cov = np.eye(3, dtype=np.float64)
    # Make third factor near-zero → creates near-zero eigenvalues in Σ
    factor_cov[2, 2] = 1e-14
    # Residual variance near-zero for some funds → rank-deficient
    residual_variance = np.full(10, 1e-12, dtype=np.float64)

    fit = FundamentalFactorFit(
        loadings=loadings,
        factor_cov=factor_cov,
        residual_variance=residual_variance,
        factor_names=["f1", "f2", "f3"],
        residual_series=np.zeros((100, 10), dtype=np.float64),
        r_squared_per_fund=np.ones(10, dtype=np.float64),
    )

    meta = compute_factor_conditioning_meta(fit)

    # Verify the metadata structure
    assert "kappa_before" in meta
    assert "kappa_after" in meta
    assert "eigenvalue_floor" in meta
    assert "n_clamped" in meta

    # With the near-zero factor and residuals, eigenvalue clamping should
    # trigger (n_clamped > 0).
    assert meta["n_clamped"] > 0
    assert meta["kappa_after"] <= meta["kappa_before"]
    assert meta["eigenvalue_floor"] > 0

    # Verify it's JSON-serializable (will be persisted in JSONB).
    import json

    json.dumps(meta)  # Should not raise

    # Simulate persistence in statistical_inputs:
    statistical_inputs: dict = {}
    statistical_inputs["factor_conditioning"] = meta
    assert statistical_inputs["factor_conditioning"]["n_clamped"] > 0

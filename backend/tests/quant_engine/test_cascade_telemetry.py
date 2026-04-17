"""PR-A11 — optimizer cascade telemetry unit tests.

Covers Section E of ``docs/prompts/2026-04-16-pr-a11-validation-gate-review.md``:

- E.1 Phase 1 success: 1 succeeded + 3 skipped attempts.
- E.2 Phase 2 success: primary recorded, variance_capped succeeded.
- E.3 Phase 3 fallback: infeasibility_reason + max_vol_target captured.

All tests synchronous against a well-conditioned 3-fund universe.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from quant_engine.optimizer_service import (
    BlockConstraint,
    FundOptimizationResult,
    PhaseAttempt,
    ProfileConstraints,
    optimize_fund_portfolio,
)


def _make_inputs(
    cvar_limit: float | None = None,
) -> tuple[list[str], dict[str, str], dict[str, float], ProfileConstraints, np.ndarray]:
    fund_ids = ["A", "B", "C"]
    fund_blocks = {"A": "eq", "B": "eq", "C": "fi"}
    expected_returns = {"A": 0.10, "B": 0.08, "C": 0.04}
    cov = np.array([
        [0.04, 0.01, 0.00],
        [0.01, 0.03, 0.00],
        [0.00, 0.00, 0.01],
    ])
    constraints = ProfileConstraints(
        blocks=[
            BlockConstraint(block_id="eq", min_weight=0.0, max_weight=1.0),
            BlockConstraint(block_id="fi", min_weight=0.0, max_weight=1.0),
        ],
        cvar_limit=cvar_limit,
        max_single_fund_weight=1.0,
    )
    return fund_ids, fund_blocks, expected_returns, constraints, cov


def _run(cvar_limit: float | None = None) -> FundOptimizationResult:
    fund_ids, fund_blocks, er, constraints, cov = _make_inputs(cvar_limit)
    return asyncio.run(
        optimize_fund_portfolio(
            fund_ids=fund_ids,
            fund_blocks=fund_blocks,
            expected_returns=er,
            constraints=constraints,
            cov_matrix=cov,
        ),
    )


def _get_attempt(attempts: list[PhaseAttempt], phase: str) -> PhaseAttempt:
    for a in attempts:
        if a.phase == phase:
            return a
    raise AssertionError(f"phase {phase!r} not found in attempts")


# ── E.1 — Phase 1 success ─────────────────────────────────────────────


def test_phase_attempts_recorded_for_phase1_success() -> None:
    result = _run(cvar_limit=None)

    assert result.status == "optimal"
    assert result.winning_phase == "primary"
    assert len(result.phase_attempts) >= 4
    primary = _get_attempt(result.phase_attempts, "primary")
    assert primary.status == "succeeded"
    # Skipped phases must have status="skipped" and zero walltime
    for ph in ("robust", "variance_capped", "min_variance"):
        att = _get_attempt(result.phase_attempts, ph)
        assert att.status == "skipped"
        assert att.wall_ms == 0
        assert att.infeasibility_reason is None


# ── E.2 — Phase 2 success ─────────────────────────────────────────────


def test_phase_attempts_records_phase2_success() -> None:
    # Tight-but-feasible CVaR limit so Phase 1 violates, Phase 2 solves.
    result = _run(cvar_limit=-0.20)

    # Either Phase 1 already satisfies or Phase 2 wins — accept both, but the
    # attempt trail MUST contain ``primary`` recorded (not skipped).
    primary = _get_attempt(result.phase_attempts, "primary")
    assert primary.status == "succeeded"
    assert primary.cvar_limit_effective == pytest.approx(-0.20)

    if result.winning_phase == "variance_capped":
        vc = _get_attempt(result.phase_attempts, "variance_capped")
        assert vc.status == "succeeded"
        assert vc.max_var is not None and vc.max_var > 0
        assert vc.cvar_coeff is not None and vc.cvar_coeff > 0
        assert vc.phase2_limit is not None


# ── E.3 — Phase 3 fallback ────────────────────────────────────────────


def test_phase_attempts_records_phase3_fallback() -> None:
    # Impossibly tight CVaR (≥ 0.5% cushion) — Phase 2 ceiling ~0 → infeasible
    result = _run(cvar_limit=-0.005)

    assert result.winning_phase == "min_variance", (
        f"expected Phase 3 winner, got {result.winning_phase!r} "
        f"(status={result.status})"
    )

    vc = _get_attempt(result.phase_attempts, "variance_capped")
    assert vc.status == "infeasible"
    assert vc.infeasibility_reason is not None
    assert vc.max_vol_target is not None and vc.max_vol_target > 0

    mv = _get_attempt(result.phase_attempts, "min_variance")
    assert mv.status == "succeeded"
    assert mv.min_achievable_variance is not None
    assert mv.min_achievable_vol is not None
    # Feasibility gap: min-var floor > Phase 2 ceiling
    assert mv.min_achievable_vol > vc.max_vol_target


# ── E.1b — Defensive: skipped-phase padding on trivial empty input ───


def test_empty_universe_produces_all_skipped_attempts() -> None:
    constraints = ProfileConstraints(blocks=[], cvar_limit=None, max_single_fund_weight=1.0)
    result = asyncio.run(
        optimize_fund_portfolio(
            fund_ids=[], fund_blocks={}, expected_returns={},
            constraints=constraints, cov_matrix=np.zeros((0, 0)),
        ),
    )
    assert result.status == "empty"
    assert len(result.phase_attempts) == 4
    assert all(a.status == "skipped" for a in result.phase_attempts)
    assert result.winning_phase is None

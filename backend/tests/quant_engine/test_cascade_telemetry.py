"""PR-A11/A12 — optimizer cascade telemetry unit tests.

A12 reshaped the cascade from the legacy 4-phase variance-proxy
sequence into a 3-phase Rockafellar-Uryasev sequence
(``phase_1_ru_max_return`` → ``phase_2_ru_robust`` →
``phase_3_min_cvar``). The PR-A11 invariants preserved here:

- ``phase_attempts`` is a dense list with one entry per cascade phase
  (including skipped ones). Skipped phases have ``status="skipped"``
  and ``wall_ms=0``.
- ``winning_phase`` is one of the three phase keys or None (pre-solve
  failure).
- Empty universe produces all-skipped attempts with ``status="empty"``.
"""

from __future__ import annotations

import asyncio

import numpy as np

from quant_engine.optimizer_service import (
    BlockConstraint,
    FundOptimizationResult,
    PhaseAttempt,
    ProfileConstraints,
    optimize_fund_portfolio,
)


def _make_inputs(
    cvar_limit: float | None = None,
) -> tuple[
    list[str], dict[str, str], dict[str, float], ProfileConstraints,
    np.ndarray, np.ndarray,
]:
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
    # Synth 5Y daily scenarios from cov; reproducible seed.
    rng = np.random.default_rng(11)
    daily_cov = cov / 252.0
    L = np.linalg.cholesky(daily_cov)
    daily_mu = np.array([expected_returns[fid] / 252.0 for fid in fund_ids])
    scenarios = (rng.standard_normal((1260, 3)) @ L.T) + daily_mu
    return fund_ids, fund_blocks, expected_returns, constraints, cov, scenarios


def _run(
    cvar_limit: float | None = None,
    robust: bool = False,
) -> FundOptimizationResult:
    fund_ids, fund_blocks, er, constraints, cov, R = _make_inputs(cvar_limit)
    return asyncio.run(
        optimize_fund_portfolio(
            fund_ids=fund_ids,
            fund_blocks=fund_blocks,
            expected_returns=er,
            constraints=constraints,
            cov_matrix=cov,
            returns_scenarios=R,
            robust=robust,
        ),
    )


def _get_attempt(attempts: list[PhaseAttempt], phase: str) -> PhaseAttempt:
    for a in attempts:
        if a.phase == phase:
            return a
    raise AssertionError(f"phase {phase!r} not found in attempts")


# ── E.1 — Phase 1 success ────────────────────────────────────────────


def test_phase_attempts_recorded_for_phase1_success() -> None:
    result = _run(cvar_limit=None)

    assert result.status == "optimal"
    assert result.winning_phase == "phase_1_ru_max_return"
    # Cascade has 3 phases; Phase 2 skipped (robust=False), Phase 3 always runs.
    assert len(result.phase_attempts) == 3
    p1 = _get_attempt(result.phase_attempts, "phase_1_ru_max_return")
    assert p1.status == "succeeded"
    p2 = _get_attempt(result.phase_attempts, "phase_2_ru_robust")
    assert p2.status == "skipped"
    assert p2.wall_ms == 0
    # Phase 3 ALWAYS runs for the achievable-return band
    p3 = _get_attempt(result.phase_attempts, "phase_3_min_cvar")
    assert p3.status == "succeeded"
    assert p3.wall_ms > 0


# ── E.2 — Phase 2 robust success ─────────────────────────────────────


def test_phase_attempts_records_phase2_robust_success() -> None:
    # Run with robust=True and no cvar_limit so both Phase 1 (no CVaR
    # constraint, max μᵀw) and Phase 2 robust can solve. Phase 1 wins
    # because the robust penalty is strictly worse than the pure
    # max-return objective; Phase 2 is recorded as ``succeeded`` but
    # not selected. The invariant we care about: Phase 2 logged a real
    # attempt (not ``skipped``) when robust=True.
    result = _run(cvar_limit=None, robust=True)

    p1 = _get_attempt(result.phase_attempts, "phase_1_ru_max_return")
    assert p1.status == "succeeded"

    p2 = _get_attempt(result.phase_attempts, "phase_2_ru_robust")
    assert p2.status in ("succeeded", "infeasible")
    assert p2.wall_ms > 0
    if p2.status == "succeeded":
        assert p2.kappa_used is not None and p2.kappa_used > 0


# ── E.3 — Phase 3 winner (tight CVaR limit, degraded) ────────────────


def test_phase_attempts_records_phase3_winner_degraded() -> None:
    # Impossibly tight CVaR (0.1%) — Phase 1 infeasible, Phase 3 wins
    # with status=degraded (universe floor binds).
    result = _run(cvar_limit=0.001)

    assert result.winning_phase == "phase_3_min_cvar", (
        f"expected Phase 3 winner, got {result.winning_phase!r} "
        f"(status={result.status})"
    )
    assert result.status == "degraded"
    assert result.min_achievable_cvar is not None
    assert result.min_achievable_cvar > 0.001, (
        "min-CVaR must exceed the impossible limit"
    )
    assert result.achievable_return_band is not None
    band = result.achievable_return_band
    # Band collapses when limit < floor.
    assert band["lower"] == band["upper"]

    p1 = _get_attempt(result.phase_attempts, "phase_1_ru_max_return")
    assert p1.status == "infeasible"
    p3 = _get_attempt(result.phase_attempts, "phase_3_min_cvar")
    assert p3.status == "succeeded"
    assert p3.objective_value is not None and p3.objective_value > 0


# ── E.1b — Defensive: empty universe produces all-skipped attempts ───


def test_empty_universe_produces_all_skipped_attempts() -> None:
    constraints = ProfileConstraints(blocks=[], cvar_limit=None, max_single_fund_weight=1.0)
    result = asyncio.run(
        optimize_fund_portfolio(
            fund_ids=[], fund_blocks={}, expected_returns={},
            constraints=constraints, cov_matrix=np.zeros((0, 0)),
        ),
    )
    assert result.status == "empty"
    # PR-A12 cascade has 3 phases
    assert len(result.phase_attempts) == 3
    assert all(a.status == "skipped" for a in result.phase_attempts)
    assert result.winning_phase is None
    # Skipped phases carry the A12 phase keys
    phase_keys = [a.phase for a in result.phase_attempts]
    assert phase_keys == [
        "phase_1_ru_max_return",
        "phase_2_ru_robust",
        "phase_3_min_cvar",
    ]

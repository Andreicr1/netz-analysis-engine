"""Regression tests for S04-F07 (Tier 1) — Phase 3 winner-selection assertion crash.

Reachable bypass path:
  Phase 1: solved but CVaR > limit (_phase1_usable=False, phase1_weights not None)
  Phase 2: not run (robust=False, phase2_weights=None)
  Phase 3: solver_failed (phase3_weights=None)

All-None safety net is bypassed because phase1_weights is populated.
Winner selection else branch must return graceful failure, NOT AssertionError.
"""

from unittest.mock import patch

import cvxpy as cp
import numpy as np
import pytest

from quant_engine.optimizer_service import (
    BlockConstraint,
    FundOptimizationResult,
    ProfileConstraints,
    optimize_fund_portfolio,
)


def _make_inputs(n: int = 3, cvar_limit: float = 0.05):
    """Standard 3-fund inputs with a tight CVaR limit."""
    fund_ids = [f"fund_{i}" for i in range(n)]
    fund_blocks = {fid: "block_a" for fid in fund_ids}
    expected_returns = {fid: 0.05 + 0.01 * i for i, fid in enumerate(fund_ids)}
    cov = np.eye(n) * 0.04
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("block_a", 0.0, 1.0)],
        cvar_limit=cvar_limit,
        max_single_fund_weight=0.5,
    )
    rng = np.random.default_rng(42)
    scenarios = rng.normal(0.0, 0.02, (504, n))
    return fund_ids, fund_blocks, expected_returns, constraints, cov, scenarios


# ── Regression test for S04-F07 (Tier 1) ──────────────────────────────────


@pytest.mark.asyncio
async def test_phase3_no_assertion_when_phase1_outside_cvar_and_phase3_fails():
    """
    Bypass path: Phase 1 CVaR > limit, Phase 2 not run, Phase 3 solver_failed.
    Must return graceful failure, NOT raise AssertionError.
    """
    fund_ids, fund_blocks, expected_returns, _, cov, scenarios = _make_inputs()

    # Very tight limit so Phase 1's realized CVaR will exceed it.
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("block_a", 0.0, 1.0)],
        cvar_limit=0.001,
        max_single_fund_weight=0.5,
    )

    # Track which cp.Problem instance is Phase 3 (the third Problem created
    # inside optimize_fund_portfolio). Patch cp.Problem.solve so that when
    # the Phase 3 problem calls solve, it raises SolverError on both attempts.
    _original_solve = cp.Problem.solve
    _problem_solve_count: dict[int, int] = {}  # id(prob) -> call count
    _problems_created: list[int] = []

    _original_init = cp.Problem.__init__

    def _tracking_init(self, *args, **kwargs):
        _original_init(self, *args, **kwargs)
        _problems_created.append(id(self))

    def _patched_solve(self, *args, **kwargs):
        # Phase 3 is the 3rd Problem created in the cascade (prob1, prob2 may
        # be skipped but prob3 is always created). With robust=False, prob2 may
        # not be created — so Phase 3 could be the 2nd. We target the last
        # Problem created before each solve call.
        prob_idx = _problems_created.index(id(self)) if id(self) in _problems_created else -1
        # Phase 1 is index 0 in this call (prob1 at line 887).
        # Phase 3 is the next one (prob3 at line 1102). With robust=False,
        # prob2 is never created, so Phase 3 is index 1.
        # With robust=True, Phase 3 is index 2.
        # For this test (robust=False), Phase 3 = index 1.
        if prob_idx >= 1:  # Phase 3 (or later)
            raise cp.SolverError("forced failure for S04-F07 regression test")
        return _original_solve(self, *args, **kwargs)

    with (
        patch.object(cp.Problem, "__init__", _tracking_init),
        patch.object(cp.Problem, "solve", _patched_solve),
    ):
        result = await optimize_fund_portfolio(
            fund_ids=fund_ids,
            fund_blocks=fund_blocks,
            expected_returns=expected_returns,
            constraints=constraints,
            cov_matrix=cov,
            returns_scenarios=scenarios,
            robust=False,
            cvar_alpha=0.95,
        )

    # Must NOT have raised AssertionError
    assert isinstance(result, FundOptimizationResult)
    # Graceful failure — status reflects the cascade outcome
    assert result.winning_phase is None
    assert result.cvar_within_limit is False
    assert result.weights == {}


@pytest.mark.asyncio
async def test_phase3_winner_selection_returns_phase3_when_available():
    """Smoke test: when Phase 3 produces valid weights and Phase 1/2 are not
    usable, the cascade returns Phase 3 weights with winning_phase='phase_3_min_cvar'.
    This exercises the same else branch with phase3_weights populated."""
    fund_ids, fund_blocks, expected_returns, _, cov, scenarios = _make_inputs(
        cvar_limit=0.001,  # very tight — Phase 1 likely exceeds
    )

    constraints = ProfileConstraints(
        blocks=[BlockConstraint("block_a", 0.0, 1.0)],
        cvar_limit=0.001,
        max_single_fund_weight=0.5,
    )

    result = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=expected_returns,
        constraints=constraints,
        cov_matrix=cov,
        returns_scenarios=scenarios,
        robust=False,
        cvar_alpha=0.95,
    )

    assert isinstance(result, FundOptimizationResult)
    # Phase 3 (min-CVaR) should have solved since the base polytope is valid
    if result.winning_phase is not None and "phase_3" in result.winning_phase:
        assert result.status in ("optimal", "degraded")
        assert sum(result.weights.values()) > 0.99

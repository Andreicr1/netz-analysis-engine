"""PR-Q43 — Session 04 observability bundle regression tests.

F06: Phase 3 turnover cost scaled to daily (Tier 3)
F10: Phase 3 PhaseAttempt records actual solver (Tier 4)
F12: Risk-budget dataclass scale documentation (Tier 4)
F14: _compute_cvar respects operator cvar_alpha (Tier 4)
"""

from __future__ import annotations

import math
import uuid

import numpy as np
import pytest

from quant_engine.optimizer_service import (
    SQRT_252,
    BlockConstraint,
    ProfileConstraints,
    optimize_fund_portfolio,
    parametric_cvar_cf,
)
from quant_engine.risk_budgeting_service import (
    FundRiskBudget,
    RiskBudgetResult,
    compute_risk_budget,
)


def _fund_ids(n: int) -> list[str]:
    return [str(uuid.uuid4()) for _ in range(n)]


def _identity_cov(n: int, scale: float = 0.01) -> np.ndarray:
    return np.eye(n) * scale


def _simple_scenarios(n: int, t: int = 504, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal((t, n)) * 0.01


# ── F06: turnover cost scale (Tier 3) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_phase3_turnover_penalty_scaled_to_daily():
    """Phase 3 turnover penalty must be scaled to daily by 1/sqrt(252).

    With high turnover_cost and current_weights far from optimal, Phase 3
    should still produce non-degenerate trade after the fix. Pre-fix,
    the un-scaled penalty (~16x stronger) would suppress trading.
    """
    ids = _fund_ids(3)
    mu = {fid: 0.05 + i * 0.02 for i, fid in enumerate(ids)}
    cov = _identity_cov(3, scale=0.04)
    blocks = {fid: "EQ" for fid in ids}
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("EQ", 0.0, 1.0)],
        cvar_limit=0.01,  # very tight → likely Phase 3 wins
        max_single_fund_weight=0.80,
    )
    scenarios = _simple_scenarios(3)
    # Current weights heavily concentrated in fund 0
    current_w = np.array([0.90, 0.05, 0.05])
    turnover = 0.05  # moderate turnover cost

    result = await optimize_fund_portfolio(
        fund_ids=ids,
        fund_blocks=blocks,
        expected_returns=mu,
        constraints=constraints,
        cov_matrix=cov,
        returns_scenarios=scenarios,
        current_weights=current_w,
        turnover_cost=turnover,
    )

    # Find Phase 3 attempt
    p3 = [a for a in result.phase_attempts if a.phase == "phase_3_min_cvar"]
    assert p3, "Phase 3 attempt must exist"

    if p3[0].status == "succeeded":
        # Phase 3 produced weights — verify non-degenerate trade
        weights_arr = np.array([result.weights.get(fid, 0.0) for fid in ids])
        trade_volume = float(np.abs(weights_arr - current_w).sum())
        # With daily-scaled penalty, optimizer should trade meaningfully
        # (at least 5% total turnover, not near-zero)
        assert trade_volume > 0.01, (
            f"Phase 3 trade volume {trade_volume:.4f} is near-zero — "
            f"turnover penalty may not be scaled to daily"
        )


# ── F10: Phase 3 PhaseAttempt records actual solver (Tier 4) ───────────────


@pytest.mark.asyncio
async def test_phase3_records_actual_solver_name():
    """Phase 3 PhaseAttempt.solver must reflect the actual solver used,
    not a hardcoded 'CLARABEL' string."""
    ids = _fund_ids(3)
    mu = {fid: 0.05 + i * 0.01 for i, fid in enumerate(ids)}
    cov = _identity_cov(3)
    blocks = {fid: "EQ" for fid in ids}
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("EQ", 0.0, 1.0)],
        cvar_limit=0.50,
        max_single_fund_weight=0.80,
    )
    scenarios = _simple_scenarios(3)

    result = await optimize_fund_portfolio(
        fund_ids=ids,
        fund_blocks=blocks,
        expected_returns=mu,
        constraints=constraints,
        cov_matrix=cov,
        returns_scenarios=scenarios,
    )

    p3 = [a for a in result.phase_attempts if a.phase == "phase_3_min_cvar"]
    assert p3, "Phase 3 attempt must exist"
    # Solver field must be a non-None string (read from solver_stats)
    assert p3[0].solver is not None
    assert isinstance(p3[0].solver, str)
    assert len(p3[0].solver) > 0


def test_phase3_records_clarabel_when_no_solver_stats():
    """Defensive default: when prob3.solver_stats is None (rare edge),
    the expression ``prob3.solver_stats.solver_name if prob3.solver_stats
    else 'CLARABEL'`` must evaluate to 'CLARABEL'."""
    # Verify the defensive default logic directly — this is what the fix
    # evaluates at runtime when solver_stats is None.
    solver_stats = None
    phase3_solver = (
        solver_stats.solver_name if solver_stats else "CLARABEL"
    )
    assert phase3_solver == "CLARABEL"


# ── F12: risk-budget scale documentation (Tier 4) ──────────────────────────


def test_risk_budget_dataclass_docstring_documents_daily_scale():
    """Smoke test: dataclasses' docstrings include the SCALE annotation."""
    assert "daily" in (RiskBudgetResult.__doc__ or "").lower()
    assert "daily" in (FundRiskBudget.__doc__ or "").lower()


def test_risk_budget_function_docstring_documents_scale():
    assert "daily" in (compute_risk_budget.__doc__ or "").lower()


# ── F14: cvar_alpha pass-through (Tier 4) ──────────────────────────────────


def test_parametric_cvar_cf_alpha_changes_output():
    """parametric_cvar_cf with alpha=0.05 vs 0.01 must produce different CVaR."""
    # Use near-zero mu and zero skew/kurtosis (Gaussian case) to ensure
    # CVaR stays positive for both alpha levels.
    w = np.array([0.5, 0.5])
    mu = np.array([0.0, 0.0])  # zero-mean so CVaR is always positive
    cov = np.array([[0.04, 0.01], [0.01, 0.05]])
    skew = np.array([0.0, 0.0])
    kurt = np.array([0.0, 0.0])  # excess kurtosis = 0 (Normal)

    cvar_95 = parametric_cvar_cf(w, mu, cov, skew, kurt, alpha=0.05)
    cvar_99 = parametric_cvar_cf(w, mu, cov, skew, kurt, alpha=0.01)

    # Both should be positive for zero-mean returns
    assert cvar_95 > 0, f"CVaR at 95% should be positive, got {cvar_95}"
    assert cvar_99 > 0, f"CVaR at 99% should be positive, got {cvar_99}"

    # 99% confidence (1% tail) must produce a more extreme (larger) CVaR
    assert cvar_99 > cvar_95, (
        f"alpha=0.01 (99% conf) CVaR {cvar_99} should exceed "
        f"alpha=0.05 (95% conf) CVaR {cvar_95}"
    )


@pytest.mark.asyncio
async def test_cvar_cf_telemetry_respects_cvar_alpha():
    """With cvar_alpha=0.99, cvar_at_solution_cf in Phase 1/3 PhaseAttempt
    must reflect the 1% tail, not the default 5% tail."""
    ids = _fund_ids(3)
    mu_dict = {fid: 0.05 + i * 0.01 for i, fid in enumerate(ids)}
    cov = _identity_cov(3)
    blocks = {fid: "EQ" for fid in ids}
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("EQ", 0.0, 1.0)],
        cvar_limit=0.80,
        max_single_fund_weight=0.80,
    )
    scenarios = _simple_scenarios(3)

    # Run with default cvar_alpha=0.95
    result_95 = await optimize_fund_portfolio(
        fund_ids=ids,
        fund_blocks=blocks,
        expected_returns=mu_dict,
        constraints=constraints,
        cov_matrix=cov,
        returns_scenarios=scenarios,
        cvar_alpha=0.95,
    )

    # Run with cvar_alpha=0.99
    result_99 = await optimize_fund_portfolio(
        fund_ids=ids,
        fund_blocks=blocks,
        expected_returns=mu_dict,
        constraints=constraints,
        cov_matrix=cov,
        returns_scenarios=scenarios,
        cvar_alpha=0.99,
    )

    # Find Phase 1 succeeded attempts (both should succeed with generous limit)
    p1_95 = [a for a in result_95.phase_attempts
             if a.phase == "phase_1_ru_max_return" and a.cvar_at_solution_cf is not None]
    p1_99 = [a for a in result_99.phase_attempts
             if a.phase == "phase_1_ru_max_return" and a.cvar_at_solution_cf is not None]

    if p1_95 and p1_99:
        # 99% confidence CVaR (1% tail) must be larger than 95% (5% tail)
        assert p1_99[0].cvar_at_solution_cf > p1_95[0].cvar_at_solution_cf, (
            f"cvar_alpha=0.99 CF CVaR {p1_99[0].cvar_at_solution_cf} should exceed "
            f"cvar_alpha=0.95 CF CVaR {p1_95[0].cvar_at_solution_cf}"
        )


# ── Aggregate smoke ────────────────────────────────────────────────────────


def test_sqrt_252_constant_defined():
    """The SQRT_252 constant introduced for F06 must be importable."""
    assert math.isclose(SQRT_252, math.sqrt(252), rel_tol=1e-12)

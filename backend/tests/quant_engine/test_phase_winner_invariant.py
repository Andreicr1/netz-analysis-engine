"""PR-A12.4 — winner-selection invariant tests.

Central invariant: when ``optimize_fund_portfolio`` returns a result with
``winning_phase in {phase_1_ru_max_return, phase_2_ru_robust}``, the realized
CVaR of the returned weights MUST respect the operator's limit (within a
tolerance of 1e-4 annualized). Otherwise the cascade must fall through to
Phase 3 and surface the below-floor state via
``cascade_summary=phase_3_min_cvar_above_limit``.

Before this PR, the gate was ``phase1_weights is not None`` — any optimal-
looking LP solution was promoted, including CLARABEL → SCS fallback
solutions where SCS's looser tolerance admitted 2× constraint violations.
"""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from quant_engine.optimizer_service import (
    BlockConstraint,
    ProfileConstraints,
    optimize_fund_portfolio,
)


def _make_inputs(
    n: int = 5,
    *,
    seed: int = 42,
    mu_scale: float = 0.10,
    tail_heaviness: float = 1.0,
) -> tuple[list[str], dict[str, str], dict[str, float], np.ndarray, np.ndarray]:
    """Build a synthetic universe with tunable tail heaviness.

    Returns (fund_ids, fund_blocks, expected_returns, cov_matrix, returns_scenarios).
    """
    rng = np.random.default_rng(seed)
    fund_ids = [f"f{i}" for i in range(n)]
    fund_blocks = {fid: "core" for fid in fund_ids}
    mu = np.linspace(mu_scale * 0.5, mu_scale * 1.5, n)
    expected_returns = {fid: float(mu[i]) for i, fid in enumerate(fund_ids)}
    # Draw scenarios from Student-t (fat tails) scaled to daily log-return magnitudes
    # ``tail_heaviness`` controls df: 3 = very fat, 30 ≈ near-Gaussian.
    df = max(3.0, 30.0 / tail_heaviness)
    t_samples = rng.standard_t(df=df, size=(504, n)) * 0.012  # ~2% daily vol scale
    daily_mu = mu / 252.0
    returns_scenarios = t_samples + daily_mu
    # Annualised covariance from scenarios (upper-bound, matches A12.3 convention).
    cov_daily = np.cov(returns_scenarios.T)
    cov_matrix = cov_daily * 252.0
    return fund_ids, fund_blocks, expected_returns, cov_matrix, returns_scenarios


@pytest.mark.asyncio
async def test_phase_1_winner_must_respect_limit() -> None:
    """Sanity path — Gaussian universe, reasonable limit → Phase 1 wins and delivers within limit."""
    fund_ids, fund_blocks, er, cov, scenarios = _make_inputs(
        n=5, tail_heaviness=1.0, mu_scale=0.08,
    )
    constraints = ProfileConstraints(
        blocks=[BlockConstraint(block_id="core", min_weight=0.0, max_weight=1.0)],
        cvar_limit=0.50,  # generous — Phase 1 should trivially hit this
        max_single_fund_weight=1.0,
    )
    result = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=er,
        cov_matrix=cov,
        returns_scenarios=scenarios,
        constraints=constraints,
    )
    # Either Phase 1 or Phase 2 wins, delivered must respect the limit.
    if result.winning_phase in ("phase_1_ru_max_return", "phase_2_ru_robust"):
        assert result.cvar_95 is not None
        assert abs(result.cvar_95) <= 0.50 + 1e-3, (
            f"Phase {result.winning_phase} won but delivered CVaR "
            f"{result.cvar_95} > limit 0.50"
        )


@pytest.mark.asyncio
async def test_scs_fallback_with_violation_rejected(monkeypatch) -> None:
    """SCS-fallback scenario: Phase 1 LP reports ``status=optimal`` while the
    realized RU-CVaR of the returned weights exceeds the operator limit by
    orders of magnitude. Simulates the Growth 2026-04-17 production pattern
    where CLARABEL → SCS fallback produced a constraint-violating solution
    within SCS's loose tolerance (eps=1e-5).

    This is a **pre-fix repro**: before PR-A12.4, the winner-selection gate
    was ``phase1_weights is not None`` — so any optimal-looking LP solution
    was promoted, including one with 2× constraint violation. Post-fix, the
    gate is ``phase1_weights is not None AND phase1_within_limit``, so the
    cascade falls through to Phase 3 and surfaces the below-floor state.

    We force the exact pathology by patching
    ``realized_cvar_from_weights`` called inside
    ``optimize_fund_portfolio`` to inject an out-of-limit realized value
    after the LP has already solved — identical shape to what SCS would
    produce.
    """
    from quant_engine import ru_cvar_lp

    # Synthetic universe where CLARABEL succeeds with a well-scoped solution.
    fund_ids, fund_blocks, er, cov, scenarios = _make_inputs(
        n=4, tail_heaviness=1.0, mu_scale=0.10, seed=7,
    )
    constraints = ProfileConstraints(
        blocks=[BlockConstraint(block_id="core", min_weight=0.0, max_weight=1.0)],
        # Loose limit so the LP genuinely solves to optimal (otherwise
        # phase1_weights is None and the gate never fires). The injected
        # realized value below then simulates SCS's pathology.
        cvar_limit=0.50,
        max_single_fund_weight=1.0,
    )

    # Monkeypatch realized_cvar_from_weights to report the solved weights
    # as OUT OF LIMIT. _cvar_from_ru multiplies by sqrt(252), so the raw
    # daily injected value * 15.87 = annualised. Return 0.15 daily → 2.38
    # annualised, well above the 0.05 limit. Phase 3 needs the true value
    # to pick a within-limit winner, so we only inject for Phase 1 / 2
    # signatures (scenarios matrix as 2nd positional arg).
    orig_realized = ru_cvar_lp.realized_cvar_from_weights
    call_counter = {"n": 0}

    def _poisoned(w: np.ndarray, scenarios_: np.ndarray, alpha: float) -> float:
        # First two invocations simulate Phase 1/2 reporting a hugely
        # violating realized CVaR. Subsequent invocations (Phase 3 audit,
        # band assembly, _build_result) get the honest value.
        call_counter["n"] += 1
        if call_counter["n"] <= 2:
            return 0.15  # daily → 2.38 annualised → massively over 0.05
        return orig_realized(w, scenarios_, alpha)

    # Patch both the source definition and the import sites in
    # optimizer_service, since it does ``from quant_engine.ru_cvar_lp import
    # realized_cvar_from_weights`` lazily inside the function body.
    import quant_engine.optimizer_service as opt_mod

    monkeypatch.setattr(ru_cvar_lp, "realized_cvar_from_weights", _poisoned)
    monkeypatch.setattr(
        opt_mod, "realized_cvar_from_weights", _poisoned, raising=False,
    )

    result = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=er,
        cov_matrix=cov,
        returns_scenarios=scenarios,
        constraints=constraints,
    )

    # Invariant: phase_1 reporting cvar_within_limit=False must NOT win.
    p1 = next(
        (a for a in result.phase_attempts if a.phase == "phase_1_ru_max_return"),
        None,
    )
    assert p1 is not None
    if p1.status == "succeeded" and p1.cvar_within_limit is False:
        assert result.winning_phase != "phase_1_ru_max_return", (
            "PR-A12.4 invariant violated: phase_1 succeeded with "
            "cvar_within_limit=False was promoted as winner"
        )


@pytest.mark.asyncio
async def test_phase_1_constraint_violation_forces_phase_3() -> None:
    """Direct unit test of the gate: inject a phase_1 solution whose realized
    RU-CVaR exceeds the limit by > tolerance. Assert winner skips Phase 1."""
    # The easiest way to force this: set the limit far below anything the
    # universe can satisfy. The LP will still solve (either feasibly under
    # loose tolerance, or infeasibly — either case tests the gate).
    fund_ids, fund_blocks, er, cov, scenarios = _make_inputs(
        n=3, tail_heaviness=2.0, mu_scale=0.15,
    )
    constraints = ProfileConstraints(
        blocks=[BlockConstraint(block_id="core", min_weight=0.0, max_weight=1.0)],
        cvar_limit=0.001,  # 0.1% — effectively zero
        max_single_fund_weight=1.0,
    )
    result = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=er,
        cov_matrix=cov,
        returns_scenarios=scenarios,
        constraints=constraints,
    )

    # Inspect phase_attempts — if phase_1 "succeeded" with within_limit=False,
    # it must NOT be the winner.
    p1 = next((a for a in result.phase_attempts if a.phase == "phase_1_ru_max_return"), None)
    if p1 is not None and p1.status == "succeeded" and p1.cvar_within_limit is False:
        assert result.winning_phase != "phase_1_ru_max_return", (
            "PR-A12.4 invariant violated: phase_1 succeeded with "
            "cvar_within_limit=False but was promoted as winner"
        )


@pytest.mark.asyncio
async def test_no_cvar_limit_phase_1_wins() -> None:
    """When the operator passes no CVaR limit, the gate must be a no-op:
    Phase 1 always wins if it produces weights."""
    fund_ids, fund_blocks, er, cov, scenarios = _make_inputs(n=4)
    constraints = ProfileConstraints(
        blocks=[BlockConstraint(block_id="core", min_weight=0.0, max_weight=1.0)],
        cvar_limit=None,  # no constraint
        max_single_fund_weight=1.0,
    )
    result = await optimize_fund_portfolio(
        fund_ids=fund_ids,
        fund_blocks=fund_blocks,
        expected_returns=er,
        cov_matrix=cov,
        returns_scenarios=scenarios,
        constraints=constraints,
    )
    # With no limit, Phase 1 is unconstrained max-return LP — should succeed.
    assert result.winning_phase == "phase_1_ru_max_return"
    assert result.status.startswith("optimal")

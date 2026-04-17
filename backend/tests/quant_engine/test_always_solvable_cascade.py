"""PR-A12 — always-solvable Rockafellar-Uryasev cascade tests.

Covers Section E of ``docs/prompts/2026-04-16-pr-a12-always-solvable-cascade.md``:

E.1 — Phase 1 succeeds within CVaR limit.
E.2 — Impossibly tight limit: Phase 3 wins with status=degraded.
E.3 — Always-solvable invariant across random configs.
E.4 — Band monotonicity across tightening limits.
E.5 — Phase 3 runs even on Phase 1 success.
E.6 — RU constraint matches empirical CVaR modulo solver tolerance.
E.7 — Empty constraint polytope produces ``constraint_polytope_empty``.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from quant_engine.optimizer_service import (
    BlockConstraint,
    FundOptimizationResult,
    ProfileConstraints,
    optimize_fund_portfolio,
)
from quant_engine.ru_cvar_lp import realized_cvar_from_weights


def _build_universe(
    n: int,
    seed: int,
    T: int = 1260,
    annual_mu_range: tuple[float, float] = (0.04, 0.12),
    vol_range: tuple[float, float] = (0.10, 0.25),
) -> tuple[list[str], dict[str, str], dict[str, float], np.ndarray, np.ndarray]:
    """Return (fund_ids, fund_blocks, expected_returns, cov_matrix, scenarios)."""
    rng = np.random.default_rng(seed)
    fund_ids = [f"F{i}" for i in range(n)]
    fund_blocks = {fid: "eq" for fid in fund_ids}
    annual_mu = rng.uniform(*annual_mu_range, size=n)
    annual_vol = rng.uniform(*vol_range, size=n)
    # Random correlation matrix via factor model structure.
    F = rng.standard_normal((n, 3))
    corr = F @ F.T
    D = np.sqrt(np.diag(corr))
    corr = corr / np.outer(D, D)
    annual_cov = np.outer(annual_vol, annual_vol) * corr
    # Repair PSD
    eigvals, eigvecs = np.linalg.eigh(annual_cov)
    eigvals = np.maximum(eigvals, 1e-8)
    annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
    daily_cov = annual_cov / 252.0
    daily_mu = annual_mu / 252.0
    L = np.linalg.cholesky(daily_cov)
    scenarios = (rng.standard_normal((T, n)) @ L.T) + daily_mu
    expected_returns = {fid: float(annual_mu[i]) for i, fid in enumerate(fund_ids)}
    return fund_ids, fund_blocks, expected_returns, annual_cov, scenarios


def _run(
    cvar_limit: float | None,
    *,
    n: int = 5,
    seed: int = 42,
    max_single: float = 0.50,
    robust: bool = False,
    block_bounds: tuple[float, float] = (0.0, 1.0),
) -> FundOptimizationResult:
    fund_ids, fund_blocks, er, cov, R = _build_universe(n=n, seed=seed)
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("eq", block_bounds[0], block_bounds[1])],
        cvar_limit=cvar_limit,
        max_single_fund_weight=max_single,
    )
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


# ── E.1 — Phase 1 succeeds within CVaR limit ─────────────────────────


def test_phase_1_succeeds_within_cvar_limit() -> None:
    result = _run(cvar_limit=0.10, n=3, max_single=1.0)

    assert result.status == "optimal"
    assert result.winning_phase == "phase_1_ru_max_return"
    assert result.min_achievable_cvar is not None
    assert result.min_achievable_cvar <= 0.10
    band = result.achievable_return_band
    assert band is not None
    assert band["upper"] >= band["lower"]


# ── E.2 — Impossibly tight limit: Phase 3 wins with degraded ─────────


def test_phase_3_above_limit_returns_min_cvar() -> None:
    # cvar_limit=0.0005 is well below any achievable CVaR_95 on a 5Y daily
    # universe with vol >= 10% — guaranteed Phase 3 winner.
    result = _run(cvar_limit=0.0005, n=3, max_single=1.0)

    assert result.status == "degraded"
    assert result.winning_phase == "phase_3_min_cvar"
    assert len(result.weights) > 0  # always-solvable invariant
    assert result.min_achievable_cvar is not None
    assert result.min_achievable_cvar > 0.0005
    band = result.achievable_return_band
    assert band is not None
    # Band collapses at the floor.
    assert band["lower"] == band["upper"]


# ── E.3 — Always-solvable invariant across random configs ────────────


def _invariant_params() -> list[tuple[int, float, int, float]]:
    rng = np.random.default_rng(99)
    out: list[tuple[int, float, int, float]] = []
    for s in range(50):
        n = int(rng.choice([3, 4, 5, 6, 8]))
        max_single = float(rng.choice([0.30, 0.40, 0.50, 0.60, 1.0]))
        # Ensure polytope non-empty: n * max_single must exceed 1.
        while n * max_single < 1.05:
            max_single = min(1.0, max_single + 0.10)
        lim = float(rng.choice([0.02, 0.05, 0.08, 0.12, 0.30]))
        out.append((s, lim, n, max_single))
    return out


@pytest.mark.parametrize("seed, cvar_limit, n, max_single", _invariant_params())
def test_always_solvable_invariant(
    seed: int, cvar_limit: float, n: int, max_single: float,
) -> None:
    result = _run(
        cvar_limit=float(cvar_limit),
        n=int(n),
        seed=int(seed),
        max_single=float(max_single),
    )
    # Cascade NEVER fails for solver / feasibility reasons.
    assert result.status in ("optimal", "degraded"), (
        f"seed={seed} cvar={cvar_limit} n={n}: status={result.status}"
    )
    assert len(result.weights) > 0
    total = sum(result.weights.values())
    assert abs(total - 1.0) < 1e-4
    assert result.min_achievable_cvar is not None


# ── E.4 — Band monotonicity across tightening limits ─────────────────


def test_achievable_band_monotonic() -> None:
    # Include a value well below any plausible universe floor (0.0005)
    # so the sweep guarantees at least one band collapse.
    limits = [0.10, 0.07, 0.05, 0.03, 0.01, 0.0005]
    bands: list[tuple[float, float]] = []
    for lim in limits:
        r = _run(cvar_limit=lim, n=4, max_single=0.50, seed=3)
        assert r.achievable_return_band is not None
        bands.append(
            (r.achievable_return_band["lower"], r.achievable_return_band["upper"]),
        )

    # Upper bound is non-increasing as we tighten the limit.
    uppers = [b[1] for b in bands]
    for prev, cur in zip(uppers, uppers[1:]):
        assert cur <= prev + 1e-6, f"band.upper not monotonic: {uppers}"

    # When the limit drops below the universe floor the band collapses.
    collapsed = [abs(b[0] - b[1]) < 1e-6 for b in bands]
    assert any(collapsed), "no limit was below universe floor in the sweep"


# ── E.5 — Phase 3 runs even on Phase 1 success ───────────────────────


def test_phase_3_runs_even_on_phase_1_success() -> None:
    result = _run(cvar_limit=0.20, n=3, max_single=1.0)

    assert result.winning_phase == "phase_1_ru_max_return"
    p3 = next(
        (a for a in result.phase_attempts if a.phase == "phase_3_min_cvar"),
        None,
    )
    assert p3 is not None
    assert p3.status == "succeeded"
    assert p3.wall_ms > 0
    assert p3.objective_value is not None and p3.objective_value > 0


# ── E.6 — RU constraint matches empirical CVaR ───────────────────────


def test_ru_cvar_constraint_matches_empirical() -> None:
    # Deterministic small fixture: T=500, N=2 with one low-risk + one
    # high-risk fund so the LP has something to trade off.
    rng = np.random.default_rng(123)
    T = 500
    R_low = rng.normal(0.0003, 0.005, size=T)
    R_high = rng.normal(0.0008, 0.020, size=T)
    R = np.column_stack([R_low, R_high])

    cvar_limit = 0.04
    fund_ids = ["LOW", "HIGH"]
    fund_blocks = {"LOW": "x", "HIGH": "x"}
    annual_mu = np.array([R_low.mean() * 252, R_high.mean() * 252])
    expected_returns = {fid: float(annual_mu[i]) for i, fid in enumerate(fund_ids)}
    annual_cov = np.cov(R, rowvar=False) * 252.0

    constraints = ProfileConstraints(
        blocks=[BlockConstraint("x", 0.0, 1.0)],
        cvar_limit=cvar_limit,
        max_single_fund_weight=1.0,
    )
    result = asyncio.run(
        optimize_fund_portfolio(
            fund_ids=fund_ids, fund_blocks=fund_blocks,
            expected_returns=expected_returns, cov_matrix=annual_cov,
            returns_scenarios=R, constraints=constraints,
        ),
    )

    assert result.status == "optimal"
    weights = np.array([result.weights[fid] for fid in fund_ids])
    realized = realized_cvar_from_weights(weights, R, alpha=0.95)
    # LP enforces empirical CVaR <= limit; allow a small solver tolerance.
    assert realized <= cvar_limit + 1e-3, (
        f"realized CVaR {realized:.4f} breaches limit {cvar_limit}"
    )


# ── E.7 — Empty constraint polytope ──────────────────────────────────


def test_polytope_empty_returns_constraint_polytope_empty() -> None:
    # Block min sums > 1 — no feasible point.
    fund_ids = ["A", "B", "C"]
    fund_blocks = {"A": "X", "B": "Y", "C": "Z"}
    annual_mu = np.array([0.08, 0.09, 0.07])
    expected_returns = {fid: float(annual_mu[i]) for i, fid in enumerate(fund_ids)}
    annual_cov = np.eye(3) * 0.02
    rng = np.random.default_rng(7)
    R = rng.normal(0.0003, 0.01, size=(500, 3))

    # Each block must hold >=0.5, sum of mins = 1.5 > 1 → infeasible polytope.
    constraints = ProfileConstraints(
        blocks=[
            BlockConstraint("X", 0.5, 1.0),
            BlockConstraint("Y", 0.5, 1.0),
            BlockConstraint("Z", 0.5, 1.0),
        ],
        cvar_limit=0.10,
        max_single_fund_weight=1.0,
    )
    result = asyncio.run(
        optimize_fund_portfolio(
            fund_ids=fund_ids, fund_blocks=fund_blocks,
            expected_returns=expected_returns, cov_matrix=annual_cov,
            returns_scenarios=R, constraints=constraints,
        ),
    )

    assert result.status == "constraint_polytope_empty"
    assert result.weights == {}


# ── PR-A12.1 — caller_kind propagates to synthesis warning ──────────


def test_caller_kind_tag_flows_to_scenarios_synth_warning(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When ``returns_scenarios=None`` the synthesizer fires a warning.
    The ``caller_kind`` kwarg must appear on the structured record so a
    dashboard alert can filter production-path invocations vs intentional
    screener / block-pareto calls."""
    fund_ids = ["X", "Y"]
    fund_blocks = {"X": "b", "Y": "b"}
    expected_returns = {"X": 0.08, "Y": 0.10}
    cov = np.array([[0.04, 0.01], [0.01, 0.03]])
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("b", 0.0, 1.0)],
        cvar_limit=0.10, max_single_fund_weight=1.0,
    )

    asyncio.run(
        optimize_fund_portfolio(
            fund_ids=fund_ids, fund_blocks=fund_blocks,
            expected_returns=expected_returns, cov_matrix=cov,
            returns_scenarios=None,
            constraints=constraints,
            caller_kind="screener_preview",
        ),
    )
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "returns_scenarios_missing_using_covariance_synth" in combined, (
        "synth warning must fire when returns_scenarios is None"
    )
    assert "caller_kind=screener_preview" in combined, (
        "caller_kind tag missing from synth warning output"
    )

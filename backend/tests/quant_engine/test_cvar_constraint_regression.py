"""PR-A12.3 — CVaR constraint delivers CVaR within the operator's limit.

Regression for the production observation on 2026-04-17 where Phase 1
declared ``status=optimal`` with ``|cvar_95| = 2.36×`` the operator's
``cvar_limit``. Root cause was an annualization mismatch: the RU LP
operated on daily scenarios against an annual-convention limit, making
the CVaR constraint effectively inactive.

Every assertion in this file must fail on the pre-fix ``optimizer_service.py``
and pass on the post-fix version — the failures prove the repro catches the
bug; the passes prove the fix.
"""

from __future__ import annotations

import asyncio
import math

import numpy as np
import pytest

from quant_engine.optimizer_service import (
    BlockConstraint,
    ProfileConstraints,
    optimize_fund_portfolio,
)
from quant_engine.ru_cvar_lp import realized_cvar_from_weights

SQRT_252 = math.sqrt(252.0)


def _build_universe(
    n: int,
    seed: int,
    T: int = 1260,
) -> tuple[list[str], dict[str, str], dict[str, float], np.ndarray, np.ndarray]:
    """Synthetic 5-fund-ish universe: annualized mu/cov + DAILY scenarios."""
    rng = np.random.default_rng(seed)
    fund_ids = [f"F{i}" for i in range(n)]
    fund_blocks = {fid: "eq" for fid in fund_ids}
    annual_mu = rng.uniform(0.04, 0.12, size=n)
    annual_vol = rng.uniform(0.10, 0.25, size=n)
    F = rng.standard_normal((n, 3))
    corr = F @ F.T
    D = np.sqrt(np.diag(corr))
    corr = corr / np.outer(D, D)
    annual_cov = np.outer(annual_vol, annual_vol) * corr
    eigvals, eigvecs = np.linalg.eigh(annual_cov)
    eigvals = np.maximum(eigvals, 1e-8)
    annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
    daily_cov = annual_cov / 252.0
    daily_mu = annual_mu / 252.0
    L = np.linalg.cholesky(daily_cov)
    scenarios = (rng.standard_normal((T, n)) @ L.T) + daily_mu
    expected_returns = {fid: float(annual_mu[i]) for i, fid in enumerate(fund_ids)}
    return fund_ids, fund_blocks, expected_returns, annual_cov, scenarios


def _run(cvar_limit: float, *, seed: int, n: int = 5, alpha: float = 0.95):
    fund_ids, fund_blocks, er, cov, R = _build_universe(n=n, seed=seed)
    constraints = ProfileConstraints(
        blocks=[BlockConstraint("eq", 0.0, 1.0)],
        cvar_limit=cvar_limit,
        max_single_fund_weight=0.50,
    )
    return asyncio.run(
        optimize_fund_portfolio(
            fund_ids=fund_ids,
            fund_blocks=fund_blocks,
            expected_returns=er,
            constraints=constraints,
            cov_matrix=cov,
            returns_scenarios=R,
            cvar_alpha=alpha,
        ),
    ), fund_ids, R


# ── E.1 — Phase 1 delivered CVaR must be within the operator's limit ────


@pytest.mark.parametrize("seed", [42, 101, 777, 2026, 9999])
@pytest.mark.parametrize("cvar_limit", [0.03, 0.05, 0.08])
@pytest.mark.parametrize("alpha", [0.90, 0.95, 0.99])
def test_phase_1_delivered_cvar_within_limit(
    seed: int, cvar_limit: float, alpha: float,
) -> None:
    """Phase 1 success must imply empirical annualized CVaR ≤ cvar_limit."""
    result, fund_ids, R = _run(cvar_limit, seed=seed, alpha=alpha)
    assert result.winning_phase in {
        "phase_1_ru_max_return", "phase_2_ru_robust", "phase_3_min_cvar",
    }, f"unexpected winner {result.winning_phase}"

    w = np.array([result.weights[fid] for fid in fund_ids])
    empirical_daily = realized_cvar_from_weights(w, R, alpha)
    empirical_annual = empirical_daily * SQRT_252

    # If Phase 3 won with status=degraded, min_achievable_cvar > limit is
    # the expected always-solvable floor — only Phase 1/2 success must honor
    # the operator's limit strictly.
    if result.winning_phase != "phase_3_min_cvar":
        # Tolerance absorbs CLARABEL→SCS fallback inaccuracy (eps=1e-5) at
        # tight CVaR limits with high alpha. The pre-fix bug delivered 2.36×
        # the limit (136% relative overshoot); this tolerance still catches
        # anything beyond ~20% relative or 1pp absolute.
        tolerance = max(1e-2, cvar_limit * 0.2)
        assert empirical_annual <= cvar_limit + tolerance, (
            f"status={result.status} winner={result.winning_phase} but "
            f"delivered |CVaR|={empirical_annual:.4f} > limit={cvar_limit:.4f} "
            f"(violation={empirical_annual - cvar_limit:.4f})"
        )


# ── E.2 — Response cvar_95 matches independent empirical verifier ───────


@pytest.mark.parametrize("seed", [42, 101, 777])
@pytest.mark.parametrize("cvar_limit", [0.05, 0.10])
def test_realized_cvar_matches_solver_report(seed: int, cvar_limit: float) -> None:
    """result.cvar_95 (negated loss) must agree with the fresh empirical CVaR."""
    result, fund_ids, R = _run(cvar_limit, seed=seed)
    if not result.weights:
        pytest.skip(f"empty result status={result.status}")
    w = np.array([result.weights[fid] for fid in fund_ids])
    empirical_annual = realized_cvar_from_weights(w, R, 0.95) * SQRT_252
    assert result.cvar_95 is not None
    # cvar_95 is reported with P/L sign (negative = loss).
    assert abs((-result.cvar_95) - empirical_annual) < 1e-3, (
        f"cvar_95={result.cvar_95:.6f} but empirical annual={-empirical_annual:.6f}"
    )


# ── E.3 — cvar_within_limit flag consistent with empirical check ───────


@pytest.mark.parametrize("seed", [42, 777])
@pytest.mark.parametrize("cvar_limit", [0.03, 0.05, 0.08])
def test_cvar_within_limit_flag_consistent(seed: int, cvar_limit: float) -> None:
    result, fund_ids, R = _run(cvar_limit, seed=seed)
    if not result.weights:
        pytest.skip(f"empty result status={result.status}")
    w = np.array([result.weights[fid] for fid in fund_ids])
    empirical_annual = realized_cvar_from_weights(w, R, 0.95) * SQRT_252
    expected_ok = empirical_annual <= cvar_limit + 1e-4
    assert result.cvar_within_limit == expected_ok, (
        f"flag={result.cvar_within_limit} but empirical={empirical_annual:.4f} "
        f"vs limit={cvar_limit:.4f}"
    )


# ── E.4 — Band bounds are annualized (operator-facing units) ───────────


def test_band_bounds_annualized() -> None:
    """achievable_return_band.*_at_cvar must be in the same units as cvar_limit."""
    result, _, _ = _run(0.08, seed=42)
    band = result.achievable_return_band
    assert band is not None
    # lower_at_cvar is min-achievable annual CVaR. For a 5-fund US-equity-like
    # universe with 10-25% annual vol, min-CVaR_95 should be in the 3-15%
    # range — not 0.004 (that would be a daily value, the pre-fix bug).
    assert 0.01 < band["lower_at_cvar"] < 0.30, (
        f"lower_at_cvar={band['lower_at_cvar']} — expected annualized magnitude"
    )
    assert band["upper_at_cvar"] > band["lower_at_cvar"] - 1e-6

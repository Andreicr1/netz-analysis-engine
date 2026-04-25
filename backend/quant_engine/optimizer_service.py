"""Portfolio optimizer service.

Uses cvxpy with CLARABEL solver to compute optimal portfolio weights.
Objective: maximize Sharpe ratio (or minimize CVaR for conservative).
Constraints: weights sum to 1, per-block bounds, portfolio CVaR <= limit, long-only.
"""

import asyncio
import time
import zlib
from dataclasses import dataclass, field
from datetime import date as date_type
from typing import Any

import cvxpy as cp
import numpy as np
import structlog

from app.utils.hashing import compute_input_hash, derive_seed
from quant_engine.mandate_risk_aversion import resolve_risk_aversion

logger = structlog.get_logger()


@dataclass
class BlockConstraint:
    block_id: str
    min_weight: float
    max_weight: float


@dataclass
class ProfileConstraints:
    blocks: list[BlockConstraint]
    cvar_limit: float | None = None
    max_single_fund_weight: float = 0.15


@dataclass
class OptimizationResult:
    weights: dict[str, float]
    expected_return: float
    portfolio_volatility: float
    sharpe_ratio: float
    status: str
    solver_info: str | None = None


# ``resolve_risk_aversion`` lives in ``quant_engine.mandate_risk_aversion`` so
# the optimizer, Black-Litterman and any future quant consumer share a single
# source of truth for Mean-Variance λ (see S3 consolidation, 2026-04-08).


def _safe_volatility(weights: np.ndarray, cov: np.ndarray) -> float:
    """sqrt of weights @ cov @ weights, floored at 0 to absorb tiny
    negative eigenvalues from numerical noise (PSD check tolerates them
    above -1e-10)."""
    return float(np.sqrt(max(float(weights @ cov @ weights), 0.0)))


def parametric_cvar_cf(
    weights: "np.ndarray",
    mu: "np.ndarray",
    cov: "np.ndarray",
    skewness: "np.ndarray",
    excess_kurtosis: "np.ndarray",
    alpha: float = 0.05,
) -> float:
    """Cornish-Fisher adjusted parametric CVaR.

    Returns positive loss value (higher = worse).
    More accurate than plain Normal for equity-heavy portfolios with fat tails.
    Historical simulation CVaR (exact) is too slow for 20,000 fitness evaluations.
    """
    from scipy.stats import norm as sp_norm
    mu_p = float(weights @ mu)
    sigma_p = _safe_volatility(weights, cov)
    port_skew = float(weights @ skewness)
    port_kurt = float(weights @ excess_kurtosis)

    z = sp_norm.ppf(alpha)  # base quantile (negative)
    z_cf = (
        z
        + (z**2 - 1) * port_skew / 6
        + (z**3 - 3 * z) * port_kurt / 24
        - (2 * z**3 - 5 * z) * port_skew**2 / 36
    )
    phi_z_cf = sp_norm.pdf(z_cf)  # evaluate density at CF-adjusted quantile
    # Cornish-Fisher Expected Shortfall (loss-space, positive):
    #   ES_CF = -mu + sigma * phi(z_CF) / alpha
    # Reference: Boudt, Peterson, Croux 2008 "Estimation and decomposition
    # of downside risk for portfolios with non-normal distributions".
    cvar = -mu_p + sigma_p * phi_z_cf / alpha
    return max(float(cvar), 0.0)


@dataclass
class ParetoResult:
    """Result from multi-objective NSGA-II optimization."""

    pareto_weights: list[list[float]]   # N Pareto-optimal weight vectors
    pareto_sharpe: list[float]          # Sharpe for each solution
    pareto_cvar: list[float]            # CVaR for each solution
    recommended_weights: dict[str, float]  # Best feasible (max Sharpe with CVaR <= limit)
    n_solutions: int
    seed: int
    input_hash: str
    status: str
    solver_info: str | None = None


def _build_block_map(blocks: list[BlockConstraint]) -> dict[str, BlockConstraint]:
    """Build {block_id: constraint} dict, raising on duplicates."""
    seen: set[str] = set()
    out: dict[str, BlockConstraint] = {}
    for bc in blocks:
        if bc.block_id in seen:
            raise ValueError(
                f"Duplicate BlockConstraint for block_id={bc.block_id!r}; "
                f"constraints.blocks must be uniquely keyed"
            )
        seen.add(bc.block_id)
        out[bc.block_id] = bc
    return out


def _project_to_bounded_simplex(
    z: np.ndarray, xl: np.ndarray, xu: np.ndarray, max_iters: int = 50,
) -> np.ndarray:
    """Project vector z onto {w: sum(w)=1, xl<=w<=xu}. Iterative clip-to-bounds
    + redistribute residual across not-yet-saturated coordinates."""
    w = np.clip(z, xl, xu)
    for _ in range(max_iters):
        residual = 1.0 - w.sum()
        if abs(residual) < 1e-9:
            return w
        if residual > 0:
            free = w < xu - 1e-12
        else:
            free = w > xl + 1e-12
        if not free.any():
            return w
        w[free] += residual / free.sum()
        w = np.clip(w, xl, xu)
    return w


def _make_portfolio_problem_class() -> tuple[type, type]:
    """Lazy factory for PortfolioProblem — only called when pymoo is available."""
    from pymoo.core.problem import Problem
    from pymoo.core.repair import Repair

    class PortfolioWeightRepair(Repair):
        """Repair operator: enforces sum=1 and per-block bounds.

        ALWAYS use Repair for weight constraints — penalty approach requires
        per-run tuning and is numerically unreliable for budget constraints.
        """

        def _do(self, problem: Any, Z: Any, **kwargs: Any) -> Any:
            Z_proj = np.empty_like(Z)
            for i, z in enumerate(Z):
                Z_proj[i] = _project_to_bounded_simplex(z, problem.xl, problem.xu)
            return Z_proj

    class PortfolioProblem(Problem):
        """Bi-objective: minimize [-Sharpe, CVaR_95].
        Optional tri-objective when esg_weight > 0: [-Sharpe, CVaR_95, -ESG_score].

        Constraint: portfolio_cvar <= cvar_limit (G[i] <= 0 = feasible).
        """

        def __init__(
            self,
            block_ids: list[str],
            mu: np.ndarray,
            cov: np.ndarray,
            rf: float,
            skewness: np.ndarray,
            excess_kurtosis: np.ndarray,
            cvar_limit: float,
            xl: np.ndarray,
            xu: np.ndarray,
            esg_scores: np.ndarray | None = None,
            esg_weight: float = 0.0,
        ):
            n_var = len(mu)
            n_obj = 3 if (esg_scores is not None and esg_weight > 0) else 2
            super().__init__(
                n_var=n_var,
                n_obj=n_obj,
                n_ieq_constr=1,
                xl=xl,
                xu=xu,
            )
            self.block_ids = block_ids
            self.mu = mu
            self.cov = cov
            self.rf = rf
            self.skewness = skewness
            self.excess_kurtosis = excess_kurtosis
            self.cvar_limit = cvar_limit
            self.esg_scores = esg_scores
            self.esg_weight = esg_weight

        def _evaluate(self, x: Any, out: Any, *args: Any, **kwargs: Any) -> None:
            n = x.shape[0]
            sharpes = np.zeros(n)
            cvars = np.zeros(n)

            for i, w in enumerate(x):
                mu_p = float(w @ self.mu)
                sigma_p = float(np.sqrt(max(float(w @ self.cov @ w), 1e-12)))
                sharpes[i] = -(mu_p - self.rf) / (sigma_p + 1e-12)  # minimize neg sharpe
                cvars[i] = parametric_cvar_cf(
                    w, self.mu, self.cov,
                    self.skewness, self.excess_kurtosis,
                )

            if self.n_obj == 3 and self.esg_scores is not None:
                esg_obj = np.array([
                    -float(w @ self.esg_scores) * self.esg_weight for w in x
                ])
                out["F"] = np.column_stack([sharpes, cvars, esg_obj])
            else:
                out["F"] = np.column_stack([sharpes, cvars])

            # Inequality constraint: cvar <= cvar_limit (G <= 0 = feasible)
            out["G"] = (cvars - self.cvar_limit).reshape(-1, 1)

    return PortfolioProblem, PortfolioWeightRepair


async def optimize_portfolio(
    block_ids: list[str],
    expected_returns: dict[str, float],
    cov_matrix: np.ndarray,
    constraints: ProfileConstraints,
    risk_free_rate: float = 0.04,
    objective: str = "max_sharpe",
    mandate: str | None = None,
    risk_aversion: float | None = None,
) -> OptimizationResult:
    """Optimize portfolio weights using cvxpy.

    Args:
        block_ids: ordered list of block IDs (corresponds to cov_matrix rows/cols)
        expected_returns: {block_id: expected annual return}
        cov_matrix: NxN covariance matrix (annualized)
        constraints: per-block min/max bounds and portfolio CVaR limit
        risk_free_rate: annualized risk-free rate
        objective: 'max_sharpe' or 'min_variance'

    """
    n = len(block_ids)

    if n == 0:
        return OptimizationResult(
            weights={}, expected_return=0.0, portfolio_volatility=0.0,
            sharpe_ratio=0.0, status="empty",
        )

    # Build expected returns vector
    mu = np.array([expected_returns.get(bid, 0.0) for bid in block_ids])

    # Decision variable
    w = cp.Variable(n, nonneg=True)

    # Portfolio return and risk
    port_return = mu @ w
    port_risk = cp.quad_form(w, cp.psd_wrap(cov_matrix))

    # Constraints
    cvx_constraints = [
        cp.sum(w) == 1,  # fully invested
    ]

    # Per-block bounds
    block_bounds = {bc.block_id: bc for bc in constraints.blocks}
    for i, bid in enumerate(block_ids):
        if bid in block_bounds:
            bc = block_bounds[bid]
            cvx_constraints.append(w[i] >= bc.min_weight)
            cvx_constraints.append(w[i] <= bc.max_weight)
        else:
            cvx_constraints.append(w[i] <= constraints.max_single_fund_weight)

    # Objective
    if objective == "min_variance":
        prob = cp.Problem(cp.Minimize(port_risk), cvx_constraints)
    else:
        # "max_sharpe" is implemented as a convex MV-utility surrogate
        # (E[r] − λ·σ²) so CVXPY stays DCP-compliant. λ is NOT a constant —
        # it must reflect the client mandate (fiduciary requirement, S2-C).
        lambda_risk = resolve_risk_aversion(risk_aversion, mandate)
        prob = cp.Problem(
            cp.Maximize(port_return - lambda_risk * port_risk),
            cvx_constraints,
        )

    # Offload CPU-bound solver to thread pool to avoid blocking the event loop
    def _solve() -> None:
        try:
            prob.solve(solver=cp.CLARABEL, verbose=False)  # type: ignore[no-untyped-call]
        except cp.SolverError:
            try:
                prob.solve(solver=cp.SCS, verbose=False)  # type: ignore[no-untyped-call]
            except cp.SolverError:
                pass  # handled below by status check

    await asyncio.to_thread(_solve)

    if prob.status is None or prob.status == "solver_error":
        return OptimizationResult(
            weights={}, expected_return=0.0, portfolio_volatility=0.0,
            sharpe_ratio=0.0, status="solver_failed",
            solver_info="Both CLARABEL and SCS failed",
        )

    if prob.status not in ("optimal", "optimal_inaccurate"):
        return OptimizationResult(
            weights={}, expected_return=0.0, portfolio_volatility=0.0,
            sharpe_ratio=0.0, status=f"infeasible: {prob.status}",
        )

    opt_weights = w.value
    if opt_weights is None:
        return OptimizationResult(
            weights={}, expected_return=0.0, portfolio_volatility=0.0,
            sharpe_ratio=0.0, status="solver_failed: no weights",
        )
    # Clean near-zero weights
    opt_weights = np.maximum(opt_weights, 0)
    total = opt_weights.sum()
    if total == 0:
        return OptimizationResult(
            weights={}, expected_return=0.0, portfolio_volatility=0.0,
            sharpe_ratio=0.0, status="infeasible: zero weights after clipping",
        )
    opt_weights /= total

    port_ret = float(mu @ opt_weights)
    port_vol = _safe_volatility(opt_weights, cov_matrix)
    sharpe = (port_ret - risk_free_rate) / port_vol if port_vol > 0 else 0.0

    return OptimizationResult(
        weights={bid: round(float(opt_weights[i]), 6) for i, bid in enumerate(block_ids)},
        expected_return=round(port_ret, 6),
        portfolio_volatility=round(port_vol, 6),
        sharpe_ratio=round(sharpe, 4),
        status="optimal",
        solver_info=prob.solver_stats.solver_name if prob.solver_stats else None,
    )


@dataclass
class PhaseAttempt:
    """PR-A11 — per-phase audit trail entry for the optimizer cascade.

    One instance per cascade phase (including skipped ones) is appended
    to ``FundOptimizationResult.phase_attempts``. The executor persists
    the list to ``portfolio_construction_runs.cascade_telemetry`` so
    operators can see which phase actually won and why earlier phases
    failed.
    """

    # PR-A12 phase keys: "phase_1_ru_max_return" | "phase_2_ru_robust"
    # | "phase_3_min_cvar". Legacy keys (primary/robust/variance_capped/
    # min_variance/heuristic) are retired. Kept as ``str`` to preserve A11
    # dataclass discipline.
    phase: str
    status: str                        # "succeeded"|"infeasible"|"solver_failed"|"skipped"
    solver: str | None
    objective_value: float | None
    wall_ms: int
    infeasibility_reason: str | None   # raw CVXPY status string when status != "succeeded"
    # Phase-specific fields (None when N/A):
    cvar_at_solution: float | None = None
    cvar_limit_effective: float | None = None
    cvar_within_limit: bool | None = None
    kappa_used: float | None = None
    # PR-A12 — CF CVaR kept as legacy comparator alongside RU-empirical
    # ``cvar_at_solution``. Populated only on succeeded phases.
    cvar_at_solution_cf: float | None = None


@dataclass
class FundOptimizationResult:
    """Result from fund-level CLARABEL optimization with block-group constraints."""

    weights: dict[str, float]  # instrument_id -> weight
    block_weights: dict[str, float]  # block_id -> aggregate weight
    expected_return: float
    portfolio_volatility: float
    sharpe_ratio: float
    cvar_95: float | None  # parametric CVaR post-check (negative = loss)
    cvar_limit: float | None
    cvar_within_limit: bool
    status: str
    solver_info: str | None = None
    # PR-A11 — cascade audit trail. Post-PR-A12 the cascade has 3 phases:
    # "phase_1_ru_max_return" | "phase_2_ru_robust" | "phase_3_min_cvar".
    # ``winning_phase`` is one of those keys or None (pre-solve failure).
    phase_attempts: list[PhaseAttempt] = field(default_factory=list)
    winning_phase: str | None = None
    # PR-A12 — Phase 3 (min-CVaR) ALWAYS runs for telemetry. These fields
    # populate the achievable-return band the Builder slider uses.
    min_achievable_cvar: float | None = None
    achievable_return_band: dict[str, float] | None = None


async def optimize_fund_portfolio(
    fund_ids: list[str],
    fund_blocks: dict[str, str],
    expected_returns: dict[str, float],
    constraints: ProfileConstraints,
    cov_matrix: np.ndarray,
    returns_scenarios: np.ndarray | None = None,
    risk_free_rate: float = 0.04,
    skewness: np.ndarray | None = None,
    excess_kurtosis: np.ndarray | None = None,
    current_weights: np.ndarray | None = None,
    turnover_cost: float = 0.0,
    robust: bool = False,
    uncertainty_level: float | None = None,
    regime_cvar_multiplier: float = 1.0,
    cvar_alpha: float = 0.95,
    mandate: str | None = None,
    risk_aversion: float | None = None,
    caller_kind: str = "unspecified",
    trace_indices: dict[str, int] | None = None,
    mu_trace_reference: dict[str, float] | None = None,
) -> FundOptimizationResult:
    """Optimize fund-level weights with block-group sum constraints.

    PR-A12 — always-solvable Rockafellar-Uryasev cascade:

    1. **Phase 1 (RU max-return LP)**: maximize μᵀw s.t. empirical
       CVaR_α(w) ≤ limit via the RU auxiliary-variable linearization.
       Pure LP, no variance proxy, no Cornish-Fisher approximation.
    2. **Phase 2 (robust RU, opt-in)**: adds PR-A3 ellipsoidal uncertainty
       penalty ``κ·‖Lᵀw‖₂`` to Phase 1's objective. SOCP.
    3. **Phase 3 (min-CVaR LP, ALWAYS runs)**: minimizes empirical CVaR
       on the base polytope. Feasible for any non-empty polytope;
       populates ``achievable_return_band`` for the Builder slider.

    When ``cvar_limit`` is None, Phase 1 becomes unconstrained max-return;
    Phase 3 still runs for the band. When Phase 1/2 both fail (the
    polytope is non-empty but the CVaR band is binding), Phase 3 wins
    with ``status=degraded`` and ``operator_signal`` flags the universe
    floor. The cascade never produces ``status=failed`` for solver /
    feasibility reasons — only for upstream data failures (no funds, PSD
    violation, empty polytope).

    ``caller_kind`` tags the call site so the auto-synthesis warning
    ("returns_scenarios_missing_using_covariance_synth") can be filtered
    by dashboard. Production construction runs should always pass
    ``caller_kind="construction_run"`` AND ``returns_scenarios`` — if
    the warning fires with that tag it is a P1 bug.

    Constraints:
        sum(w) == 1                          (fully invested)
        w >= 0                               (long only)
        w_i <= max_single_fund_weight        (concentration limit)
        sum(w[funds_in_block]) >= block_min  (block floor)
        sum(w[funds_in_block]) <= block_max  (block ceiling)
    """
    n = len(fund_ids)
    cvar_limit = constraints.cvar_limit

    if n == 0:
        return FundOptimizationResult(
            weights={}, block_weights={}, expected_return=0.0,
            portfolio_volatility=0.0, sharpe_ratio=0.0,
            cvar_95=None, cvar_limit=cvar_limit,
            cvar_within_limit=True, status="empty",
            phase_attempts=[
                PhaseAttempt(
                    phase=p, status="skipped", solver=None,
                    objective_value=None, wall_ms=0, infeasibility_reason=None,
                )
                for p in ("phase_1_ru_max_return", "phase_2_ru_robust", "phase_3_min_cvar")
            ],
            winning_phase=None,
        )

    if current_weights is not None:
        if current_weights.shape != (n,):
            raise ValueError(
                f"current_weights shape {current_weights.shape} does not match "
                f"len(fund_ids)={n}; caller must pass a 1D array "
                f"aligned by fund_ids order"
            )

    # B.7 — caller is responsible for assembling Σ. The optimizer
    # validates the matrix shape and enforces PSD before handing it to
    # CVXPY (cp.psd_wrap raises late and unhelpfully). A negative
    # eigenvalue beyond the float tolerance returns a ``psd_violation``
    # status so callers can repair upstream rather than hide the bug.
    if cov_matrix is None:
        raise ValueError("optimize_fund_portfolio requires cov_matrix")
    expected_shape = (n, n)
    if cov_matrix.shape != expected_shape:
        raise ValueError(
            f"cov_matrix shape mismatch: expected {expected_shape}, got {cov_matrix.shape}"
        )
    min_eig = float(np.linalg.eigvalsh(cov_matrix).min())
    if min_eig < -1e-10:
        return FundOptimizationResult(
            weights={}, block_weights={}, expected_return=0.0,
            portfolio_volatility=0.0, sharpe_ratio=0.0,
            cvar_95=None, cvar_limit=cvar_limit,
            cvar_within_limit=False, status="psd_violation",
            solver_info=f"min_eigenvalue={min_eig:.3e}",
            phase_attempts=[
                PhaseAttempt(
                    phase=p, status="skipped", solver=None,
                    objective_value=None, wall_ms=0, infeasibility_reason="psd_violation",
                )
                for p in ("phase_1_ru_max_return", "phase_2_ru_robust", "phase_3_min_cvar")
            ],
            winning_phase=None,
        )

    missing = set(fund_ids) - expected_returns.keys()
    if missing:
        raise ValueError(
            f"expected_returns missing {len(missing)} fund(s) of {len(fund_ids)}: "
            f"{sorted(missing)[:5]}{'...' if len(missing) > 5 else ''}"
        )
    mu = np.array([expected_returns[fid] for fid in fund_ids])

    # ── PR-A19 L8 — mu_trace_lp_input + invariant check (diagnose-only) ────
    # Confirms nothing between ``compute_fund_level_inputs`` and the LP
    # mutates μ. ``mu_trace_reference`` is optional: when present it holds
    # ``{ticker: mu_after_quant_queries[ticker]}``. Any drift is logged but
    # never raises — diagnostic first, fix second (per A19 spec non-goals).
    if trace_indices:
        _mu_min = float(mu.min()) if mu.size else 0.0
        _mu_max = float(mu.max()) if mu.size else 0.0
        _mu_median = float(np.median(mu)) if mu.size else 0.0
        _mu_argmax_idx = int(np.argmax(mu)) if mu.size else -1
        for _tkr, _idx in trace_indices.items():
            if not (0 <= _idx < n):
                continue
            _mu_i = float(mu[_idx])
            _cov_ii = float(cov_matrix[_idx, _idx]) if cov_matrix is not None else 0.0
            _reference = (mu_trace_reference or {}).get(_tkr)
            _invariant_delta = (
                abs(_mu_i - _reference) if _reference is not None else None
            )
            _invariant_ok = (
                _invariant_delta is not None and _invariant_delta < 1e-12
            )
            logger.info(
                "mu_trace_lp_input",
                ticker=_tkr,
                fund_id=fund_ids[_idx],
                mu_lp_i=_mu_i,
                cov_diag_i=_cov_ii,
                mu_reference=_reference,
                invariant_delta=_invariant_delta,
                invariant_ok=_invariant_ok,
                mu_min=_mu_min,
                mu_max=_mu_max,
                mu_median=_mu_median,
                mu_argmax_idx=_mu_argmax_idx,
                mu_argmax_ticker_match=(_mu_argmax_idx == _idx),
            )

    max_fund_w = constraints.max_single_fund_weight
    psd_cov = cp.psd_wrap(cov_matrix)

    # Pre-compute block structure (shared across all solve phases)
    block_map = _build_block_map(constraints.blocks)
    block_fund_indices: dict[str, list[int]] = {}
    for i, fid in enumerate(fund_ids):
        block = fund_blocks.get(fid)
        if block:
            block_fund_indices.setdefault(block, []).append(i)

    def _build_base_constraints(w_var: cp.Variable) -> list[Any]:
        """Build constraints shared by all solve phases.

        Iterates the FULL block_map (all declared constraints), not just
        blocks that happen to have funds. A constraint for an empty block
        with min_weight > 0 is INFEASIBLE — surface it as such
        (cp.sum([]) == 0, which violates blk_sum >= bc.min_weight > 0).
        """
        cs: list[Any] = [cp.sum(w_var) == 1]  # type: ignore[attr-defined]
        for i in range(n):
            cs.append(w_var[i] <= max_fund_w)
        for blk_id, bc in block_map.items():
            indices = block_fund_indices.get(blk_id, [])
            blk_sum = cp.sum([w_var[i] for i in indices]) if indices else 0
            cs.append(blk_sum >= bc.min_weight)
            cs.append(blk_sum <= bc.max_weight)
        return cs

    async def _solve_problem(prob: cp.Problem) -> str | None:
        """Solve with CLARABEL → SCS fallback. Returns status."""
        def _do() -> None:
            try:
                prob.solve(solver=cp.CLARABEL, verbose=False)  # type: ignore[no-untyped-call]
                if prob.status not in ("optimal", "optimal_inaccurate"):
                    # CLARABEL failed — try SCS with looser tolerances
                    prob.solve(solver=cp.SCS, verbose=False,  # type: ignore[no-untyped-call]
                               eps=1e-5, max_iters=10000)
            except cp.SolverError:
                try:
                    prob.solve(solver=cp.SCS, verbose=False,  # type: ignore[no-untyped-call]
                               eps=1e-5, max_iters=10000)
                except cp.SolverError:
                    pass
        await asyncio.to_thread(_do)
        return str(prob.status) if prob.status is not None else None

    def _extract_weights(w_var: cp.Variable) -> np.ndarray | None:
        """Clean and normalize solved weights. Returns None if degenerate or NaN."""
        if w_var.value is None or not np.all(np.isfinite(w_var.value)):
            return None
        w_arr: np.ndarray = np.maximum(w_var.value, 0)
        total = w_arr.sum()
        if total == 0:
            return None
        result: np.ndarray = w_arr / total
        return result

    def _verify_weight_constraints(
        w: np.ndarray,
        tol: float = 1e-4,
    ) -> tuple[bool, str | None]:
        """Returns (ok, violation_reason). tol is a numerical tolerance for
        optimal_inaccurate solver tolerance — outside this band the solve is
        not usable."""
        if abs(w.sum() - 1.0) > tol:
            return False, f"sum_violation {w.sum():.6f}"
        if (w > max_fund_w + tol).any():
            return False, f"max_fund {w.max():.6f} > {max_fund_w}"
        for blk_id, indices in block_fund_indices.items():
            if blk_id not in block_map:
                continue
            bc = block_map[blk_id]
            bs = float(w[indices].sum()) if indices else 0.0
            if bs < bc.min_weight - tol or bs > bc.max_weight + tol:
                return False, f"block_{blk_id} {bs:.6f} not in [{bc.min_weight}, {bc.max_weight}]"
        return True, None

    def _add_turnover_penalty(
        w_var: cp.Variable,
        constraints_list: list[Any],
        objective_expr: Any,
    ) -> Any:
        """Add L1 turnover penalty to the constraints + objective. No-op when
        current_weights is None or turnover_cost is 0. Returns the updated
        objective_expr (constraints list mutated in-place)."""
        if current_weights is None or turnover_cost <= 0:
            return objective_expr
        t = cp.Variable(w_var.size, nonneg=True)
        constraints_list += [t >= w_var - current_weights, t >= current_weights - w_var]
        return objective_expr - turnover_cost * cp.sum(t)

    # Resolve moments: use provided arrays or fall back to zeros
    _skew = skewness if skewness is not None else np.zeros(n)
    _kurt = excess_kurtosis if excess_kurtosis is not None else np.zeros(n)

    def _compute_cvar(w_arr: np.ndarray) -> float:
        """Compute parametric CVaR (Cornish-Fisher)."""
        return -parametric_cvar_cf(w_arr, mu, cov_matrix, _skew, _kurt)

    # PR-A11 — cascade audit trail. The list is appended to as each phase
    # completes (or is skipped); ``_pad_skipped`` backfills the remaining
    # cascade slots at every return site so the shape is uniform.
    attempts: list[PhaseAttempt] = []
    _CASCADE_PHASE_ORDER = (
        "phase_1_ru_max_return",
        "phase_2_ru_robust",
        "phase_3_min_cvar",
    )

    def _pad_skipped() -> list[PhaseAttempt]:
        seen = {a.phase for a in attempts}
        for phase in _CASCADE_PHASE_ORDER:
            if phase not in seen:
                attempts.append(
                    PhaseAttempt(
                        phase=phase,
                        status="skipped",
                        solver=None,
                        objective_value=None,
                        wall_ms=0,
                        infeasibility_reason=None,
                    ),
                )
        return attempts

    def _build_result(
        w_arr: np.ndarray, solver: str | None, status: str,
        winning_phase: str | None = None,
        min_achievable_cvar: float | None = None,
        achievable_return_band: dict[str, float] | None = None,
    ) -> FundOptimizationResult:
        """Build FundOptimizationResult from optimized weights.

        PR-A12.3 — ``cvar_95`` is the **empirical** RU CVaR annualized via
        √252, reported with P/L sign (negative = loss). Previously returned
        the Cornish-Fisher parametric CVaR on annual moments, which could
        diverge silently from the value the LP actually constrained.
        """
        ret = float(mu @ w_arr)
        vol = _safe_volatility(w_arr, cov_matrix)
        sharpe = (ret - risk_free_rate) / vol if vol > 0 else 0.0
        # Empirical annualized CVaR magnitude (matches the LP's realized value).
        cvar_emp_annual = realized_cvar_from_weights(w_arr, returns_scenarios, cvar_alpha) * SQRT_252
        # P/L sign convention: loss expressed as a negative number.
        cvar_95_neg = -cvar_emp_annual
        cvar_ok = (
            cvar_emp_annual <= effective_cvar_limit + 1e-4
            if effective_cvar_limit is not None
            else True
        )

        # Aggregate weights when fund_ids contains duplicates (e.g. dual share
        # classes mapped to the same instrument). Dict comprehension would drop
        # the earlier slice and silently underweight the instrument.
        fw: dict[str, float] = {}
        for i, fid in enumerate(fund_ids):
            fw[fid] = round(fw.get(fid, 0.0) + float(w_arr[i]), 6)
        bw: dict[str, float] = {}
        for fid, wt in fw.items():
            blk = fund_blocks.get(fid, "unknown")
            bw[blk] = bw.get(blk, 0.0) + wt

        return FundOptimizationResult(
            weights=fw,
            block_weights={k: round(v, 6) for k, v in bw.items()},
            expected_return=round(ret, 6),
            portfolio_volatility=round(vol, 6),
            sharpe_ratio=round(sharpe, 4),
            cvar_95=round(cvar_95_neg, 6),
            cvar_limit=cvar_limit,
            cvar_within_limit=cvar_ok,
            status=status,
            solver_info=solver,
            phase_attempts=_pad_skipped(),
            winning_phase=winning_phase,
            min_achievable_cvar=min_achievable_cvar,
            achievable_return_band=achievable_return_band,
        )

    def _empty_result(
        status: str, solver: str | None = None,
        winning_phase: str | None = None,
    ) -> FundOptimizationResult:
        return FundOptimizationResult(
            weights={}, block_weights={}, expected_return=0.0,
            portfolio_volatility=0.0, sharpe_ratio=0.0,
            cvar_95=None, cvar_limit=cvar_limit,
            cvar_within_limit=False, status=status, solver_info=solver,
            phase_attempts=_pad_skipped(),
            winning_phase=winning_phase,
        )

    # ── PR-A12 cascade bootstrap ──────────────────────────────────────────
    # The Rockafellar-Uryasev LP needs a raw scenario matrix. The legacy
    # entry points for ``optimize_fund_portfolio`` (screener drill-downs,
    # block-level allocations) never supplied one; synthesize it from the
    # covariance when absent so those callers still work while
    # construction runs pass the real series.
    from quant_engine.ru_cvar_lp import (
        build_ru_cvar_constraints,
        build_ru_cvar_objective,
        realized_cvar_from_weights,
    )

    # PR-A12.3 — annualization convention for the RU CVaR cascade.
    #
    # Inputs and outputs are annualized to match the operator's mental model
    # (``cvar_limit`` expresses an annual tail loss). The RU LP internally
    # operates on daily scenarios, so the limit is rescaled to daily before
    # entering the constraint and every CVaR the function returns is rescaled
    # back to annual via sqrt(252). Scenarios are NEVER rescaled in place —
    # that would break the iid distributional assumption. This docstring is
    # load-bearing for PR-A13/A13.1; changing the convention here requires
    # updating the Builder slider ranges and the preview endpoint in lockstep.
    SQRT_252 = float(np.sqrt(252.0))

    if returns_scenarios is None or returns_scenarios.size == 0:
        logger.warning(
            "returns_scenarios_missing_using_covariance_synth",
            n_funds=n,
            caller_kind=caller_kind,
        )
        # CLAUDE.md: never use Python built-in hash() for deterministic
        # cross-process seeds. PYTHONHASHSEED randomization causes identical
        # inputs to produce different scenario matrices across Railway pods.
        seed = zlib.crc32(",".join(fund_ids).encode("utf-8")) & 0xFFFFFFFF
        rng = np.random.default_rng(seed)
        try:
            L_synth = np.linalg.cholesky(cov_matrix / 252.0)
        except np.linalg.LinAlgError:
            eig_v, eig_vec = np.linalg.eigh(cov_matrix / 252.0)
            eig_v = np.maximum(eig_v, 1e-10)
            L_synth = eig_vec @ np.diag(np.sqrt(eig_v))
        returns_scenarios = (rng.standard_normal((504, n)) @ L_synth.T) + (mu / 252.0)

    if returns_scenarios.shape[1] != n:
        raise ValueError(
            f"returns_scenarios has {returns_scenarios.shape[1]} columns, expected {n}",
        )
    T = int(returns_scenarios.shape[0])
    if T < 252:
        logger.error(
            "returns_scenarios_below_minimum_observations",
            t=T, min_required=252,
        )
        return _empty_result("insufficient_scenarios")

    # Regime-adjusted effective CVaR limit — same semantics as the legacy
    # cascade so downstream telemetry keeps its meaning.
    effective_cvar_limit: float | None = cvar_limit
    if cvar_limit is not None and regime_cvar_multiplier != 1.0:
        effective_cvar_limit = float(abs(cvar_limit)) * regime_cvar_multiplier
        logger.info(
            "regime_cvar_multiplier_applied",
            original_limit=cvar_limit,
            effective_limit=effective_cvar_limit,
            multiplier=regime_cvar_multiplier,
        )
    elif cvar_limit is not None:
        effective_cvar_limit = float(abs(cvar_limit))

    # Daily-scale limit fed into the LP constraint; annual limit preserved for
    # telemetry + within-limit checks against annualized realized CVaR.
    lp_cvar_limit_daily: float | None = (
        effective_cvar_limit / SQRT_252 if effective_cvar_limit is not None else None
    )

    lambda_risk = resolve_risk_aversion(risk_aversion, mandate)  # Phase 2 only

    def _cvar_from_ru(w_arr: np.ndarray) -> float:
        """Annualized RU-empirical CVaR (matches Phase 1/3 LP objective, √252 scaled)."""
        return realized_cvar_from_weights(w_arr, returns_scenarios, cvar_alpha) * SQRT_252

    # PR-A12.4 — winner-selection must verify realized CVaR against the
    # operator's limit before promoting Phase 1 / Phase 2. The SCS fallback
    # (CLARABEL → SCS) can return ``status=optimal`` with realized CVaR
    # violating the constraint by orders of magnitude at its loose tolerance
    # (eps=1e-5). Before this PR, the gate was ``phase1_weights is not None``
    # — any optimal-looking solution was promoted, even when it delivered
    # 2× the operator's CVaR budget. These flags are hoisted to function
    # scope so winner selection can read them uniformly.
    _phase1_within_limit: bool | None = None
    _phase2_within_limit: bool | None = None
    _USABLE_TOLERANCE = 1e-4  # annualized; tight enough to reject 2× violations,
                              # loose enough to accept CLARABEL precision (~1e-6).

    phase1_weights: np.ndarray | None = None
    phase1_solver: str | None = None
    phase1_expected_return: float | None = None
    phase2_weights: np.ndarray | None = None
    phase2_solver: str | None = None
    phase2_expected_return: float | None = None

    # ── Phase 1 — RU CVaR-constrained max return ──────────────────────────
    w1 = cp.Variable(n, nonneg=True)
    phase1_constraints = _build_base_constraints(w1)
    if lp_cvar_limit_daily is not None:
        ru_cs, _, _ = build_ru_cvar_constraints(
            w_var=w1,
            returns_scenarios=returns_scenarios,
            alpha=cvar_alpha,
            cvar_limit=lp_cvar_limit_daily,
        )
        phase1_constraints.extend(ru_cs)

    objective_expr1 = _add_turnover_penalty(w1, phase1_constraints, mu @ w1)

    prob1 = cp.Problem(cp.Maximize(objective_expr1), phase1_constraints)
    _t_p1 = time.perf_counter()
    status1 = await _solve_problem(prob1)
    _wall_p1 = int((time.perf_counter() - _t_p1) * 1000)

    if status1 in ("optimal", "optimal_inaccurate"):
        opt_w1 = _extract_weights(w1)
        if opt_w1 is not None:
            _ok1, _reason1 = _verify_weight_constraints(opt_w1)
            if not _ok1:
                logger.warning("phase1_solver_imprecise", reason=_reason1)
                attempts.append(PhaseAttempt(
                    phase="phase_1_ru_max_return", status="solver_imprecise",
                    solver=prob1.solver_stats.solver_name if prob1.solver_stats else None,
                    objective_value=None, wall_ms=_wall_p1,
                    infeasibility_reason=_reason1,
                    cvar_limit_effective=effective_cvar_limit,
                ))
                opt_w1 = None
        if opt_w1 is not None:
            phase1_weights = opt_w1
            phase1_solver = prob1.solver_stats.solver_name if prob1.solver_stats else "CLARABEL"
            phase1_expected_return = float(mu @ opt_w1)
            phase1_cvar_ru = _cvar_from_ru(opt_w1)
            phase1_cvar_cf = _compute_cvar(opt_w1)  # legacy comparator (positive = loss)
            # PR-A12.3 diag — post-solve verification + solver-vs-verifier
            # divergence check. Kept until live smoke confirms the
            # annualization fix binds the constraint in production.
            losses_p1 = -returns_scenarios @ opt_w1
            realized_daily_p1 = float(
                realized_cvar_from_weights(opt_w1, returns_scenarios, cvar_alpha),
            )
            zeta_star_p1 = float(np.quantile(losses_p1, cvar_alpha))
            u_star_p1 = np.maximum(losses_p1 - zeta_star_p1, 0.0)
            ru_direct_daily = float(
                zeta_star_p1
                + u_star_p1.sum() / ((1.0 - cvar_alpha) * losses_p1.shape[0])
            )
            logger.info(
                "phase_1_post_solve_cvar_verification",
                realized_daily=realized_daily_p1,
                realized_annual=realized_daily_p1 * SQRT_252,
                ru_direct_daily=ru_direct_daily,
                ru_direct_annual=ru_direct_daily * SQRT_252,
                lp_constraint_rhs_daily=lp_cvar_limit_daily,
                lp_constraint_rhs_annual=effective_cvar_limit,
                delta_annual_vs_limit=(realized_daily_p1 * SQRT_252)
                - (effective_cvar_limit or 0.0),
                cvar_alpha=cvar_alpha,
                n_funds=int(opt_w1.shape[0]),
                T=int(returns_scenarios.shape[0]),
                solver=phase1_solver,
                sum_weights=float(opt_w1.sum()),
            )
            phase1_within = (
                phase1_cvar_ru <= effective_cvar_limit + _USABLE_TOLERANCE
                if effective_cvar_limit is not None
                else True
            )
            _phase1_within_limit = phase1_within  # PR-A12.4 winner gate
            attempts.append(PhaseAttempt(
                phase="phase_1_ru_max_return",
                status="succeeded",
                solver=phase1_solver,
                objective_value=round(phase1_expected_return, 6),
                wall_ms=_wall_p1,
                infeasibility_reason=None,
                cvar_at_solution=round(phase1_cvar_ru, 6),
                cvar_at_solution_cf=round(abs(phase1_cvar_cf), 6),
                cvar_limit_effective=effective_cvar_limit,
                cvar_within_limit=phase1_within,
            ))
        else:
            attempts.append(PhaseAttempt(
                phase="phase_1_ru_max_return", status="infeasible",
                solver=None, objective_value=None, wall_ms=_wall_p1,
                infeasibility_reason="zero weights after clipping",
                cvar_limit_effective=effective_cvar_limit,
            ))
    elif status1 in (None, "solver_error"):
        attempts.append(PhaseAttempt(
            phase="phase_1_ru_max_return", status="solver_failed", solver=None,
            objective_value=None, wall_ms=_wall_p1,
            infeasibility_reason="Both CLARABEL and SCS failed",
            cvar_limit_effective=effective_cvar_limit,
        ))
    else:
        attempts.append(PhaseAttempt(
            phase="phase_1_ru_max_return", status="infeasible", solver=None,
            objective_value=None, wall_ms=_wall_p1,
            infeasibility_reason=str(status1),
            cvar_limit_effective=effective_cvar_limit,
        ))

    # ── Phase 2 — Robust RU (ellipsoidal uncertainty on μ) ────────────────
    if not robust:
        attempts.append(PhaseAttempt(
            phase="phase_2_ru_robust", status="skipped", solver=None,
            objective_value=None, wall_ms=0, infeasibility_reason=None,
        ))
    else:
        try:
            from scipy.stats import chi2 as sp_chi2
            kappa_95 = float(np.sqrt(sp_chi2.ppf(0.95, df=max(n, 1))))
            kappa = kappa_95 if uncertainty_level is None else (
                float(uncertainty_level) * (kappa_95 / 0.5) * 0.5
            )
            try:
                L_chol = np.linalg.cholesky(cov_matrix)
            except np.linalg.LinAlgError:
                eig_v, eig_vec = np.linalg.eigh(cov_matrix)
                eig_v = np.maximum(eig_v, 1e-8)
                L_chol = eig_vec @ np.diag(np.sqrt(eig_v))

            w2 = cp.Variable(n, nonneg=True)
            constraints2 = _build_base_constraints(w2)
            if lp_cvar_limit_daily is not None:
                ru_cs2, _, _ = build_ru_cvar_constraints(
                    w_var=w2,
                    returns_scenarios=returns_scenarios,
                    alpha=cvar_alpha,
                    cvar_limit=lp_cvar_limit_daily,
                )
                constraints2.extend(ru_cs2)

            robust_expr = _add_turnover_penalty(
                w2, constraints2,
                mu @ w2 - kappa * cp.norm(L_chol.T @ w2, 2),
            )
            prob2 = cp.Problem(cp.Maximize(robust_expr), constraints2)

            _t_p2 = time.perf_counter()
            status2 = await _solve_problem(prob2)
            _wall_p2 = int((time.perf_counter() - _t_p2) * 1000)

            if status2 in ("optimal", "optimal_inaccurate"):
                opt_w2 = _extract_weights(w2)
                if opt_w2 is not None:
                    _ok2, _reason2 = _verify_weight_constraints(opt_w2)
                    if not _ok2:
                        logger.warning("phase2_solver_imprecise", reason=_reason2)
                        attempts.append(PhaseAttempt(
                            phase="phase_2_ru_robust", status="solver_imprecise",
                            solver=prob2.solver_stats.solver_name if prob2.solver_stats else None,
                            objective_value=None, wall_ms=_wall_p2,
                            infeasibility_reason=_reason2,
                            kappa_used=round(kappa, 6),
                            cvar_limit_effective=effective_cvar_limit,
                        ))
                        opt_w2 = None
                if opt_w2 is not None:
                    phase2_weights = opt_w2
                    phase2_solver = prob2.solver_stats.solver_name if prob2.solver_stats else "CLARABEL"
                    phase2_expected_return = float(mu @ opt_w2)
                    phase2_cvar_ru = _cvar_from_ru(opt_w2)
                    phase2_cvar_cf = _compute_cvar(opt_w2)
                    phase2_within = (
                        phase2_cvar_ru <= effective_cvar_limit + _USABLE_TOLERANCE
                        if effective_cvar_limit is not None
                        else True
                    )
                    _phase2_within_limit = phase2_within  # PR-A12.4 winner gate
                    attempts.append(PhaseAttempt(
                        phase="phase_2_ru_robust",
                        status="succeeded",
                        solver=phase2_solver,
                        objective_value=round(phase2_expected_return, 6),
                        wall_ms=_wall_p2,
                        infeasibility_reason=None,
                        cvar_at_solution=round(phase2_cvar_ru, 6),
                        cvar_at_solution_cf=round(abs(phase2_cvar_cf), 6),
                        cvar_limit_effective=effective_cvar_limit,
                        cvar_within_limit=phase2_within,
                        kappa_used=round(kappa, 6),
                    ))
                else:
                    attempts.append(PhaseAttempt(
                        phase="phase_2_ru_robust", status="infeasible",
                        solver=phase2_solver, objective_value=None, wall_ms=_wall_p2,
                        infeasibility_reason="zero weights after clipping",
                        kappa_used=round(kappa, 6),
                        cvar_limit_effective=effective_cvar_limit,
                    ))
            else:
                attempts.append(PhaseAttempt(
                    phase="phase_2_ru_robust", status="infeasible",
                    solver=None, objective_value=None, wall_ms=_wall_p2,
                    infeasibility_reason=str(status2),
                    kappa_used=round(kappa, 6),
                    cvar_limit_effective=effective_cvar_limit,
                ))
        except Exception as e:
            attempts.append(PhaseAttempt(
                phase="phase_2_ru_robust", status="solver_failed",
                solver=None, objective_value=None, wall_ms=0,
                infeasibility_reason=str(e),
                cvar_limit_effective=effective_cvar_limit,
            ))
            logger.warning("phase_2_ru_robust_failed", error=str(e))

    # ── Phase 3 — Min-CVaR LP (ALWAYS runs for telemetry band) ────────────
    w3 = cp.Variable(n, nonneg=True)
    cvar_expr3, slack_cs3, _zeta3, _u3 = build_ru_cvar_objective(
        w_var=w3,
        returns_scenarios=returns_scenarios,
        alpha=cvar_alpha,
    )
    constraints3 = _build_base_constraints(w3) + slack_cs3
    # Turnover penalty for Phase 3 (minimize objective): add cost instead of
    # subtract, since we're minimizing. min(CVaR + turnover_cost * |Δw|).
    phase3_obj_expr = cvar_expr3
    if current_weights is not None and turnover_cost > 0:
        t3 = cp.Variable(n, nonneg=True)
        constraints3 += [t3 >= w3 - current_weights, t3 >= current_weights - w3]
        phase3_obj_expr = cvar_expr3 + turnover_cost * cp.sum(t3)
    prob3 = cp.Problem(cp.Minimize(phase3_obj_expr), constraints3)

    _t_p3 = time.perf_counter()
    status3 = await _solve_problem(prob3)
    _wall_p3 = int((time.perf_counter() - _t_p3) * 1000)

    phase3_weights: np.ndarray | None = None
    min_achievable_cvar: float | None = None
    if status3 in ("optimal", "optimal_inaccurate"):
        opt_w3 = _extract_weights(w3)
        if opt_w3 is not None:
            _ok3, _reason3 = _verify_weight_constraints(opt_w3)
            if not _ok3:
                logger.warning("phase3_solver_imprecise", reason=_reason3)
                attempts.append(PhaseAttempt(
                    phase="phase_3_min_cvar", status="solver_imprecise",
                    solver="CLARABEL", objective_value=None, wall_ms=_wall_p3,
                    infeasibility_reason=_reason3,
                    cvar_limit_effective=effective_cvar_limit,
                ))
                opt_w3 = None
        # PR-A17.1 C.1 — Phase 3 post-solve inspection. Diagnoses the
        # "objective_value=0.0 → upstream_heuristic" regression: logs the
        # extracted weight vector's shape (sum, max, nonzero count) plus
        # the LP's empirical realized CVaR (daily + annualized) so we can
        # distinguish genuine near-zero min-CVaR from degenerate solver output.
        logger.info(
            "phase_3_post_solve_inspection",
            prob_status=str(prob3.status),
            prob_value=float(prob3.value) if prob3.value is not None else None,
            extracted_is_none=(opt_w3 is None),
            weights_sum=float(opt_w3.sum()) if opt_w3 is not None else None,
            weights_max=float(opt_w3.max()) if opt_w3 is not None else None,
            weights_nonzero_count=int((opt_w3 > 1e-6).sum()) if opt_w3 is not None else None,
            realized_cvar_daily=(
                float(realized_cvar_from_weights(opt_w3, returns_scenarios, cvar_alpha))
                if opt_w3 is not None else None
            ),
            realized_cvar_annual=(
                float(realized_cvar_from_weights(opt_w3, returns_scenarios, cvar_alpha) * SQRT_252)
                if opt_w3 is not None else None
            ),
            n_funds=n,
            n_scenarios=int(returns_scenarios.shape[0]),
            cvar_alpha=cvar_alpha,
            effective_cvar_limit=effective_cvar_limit,
        )
        if opt_w3 is not None:
            phase3_weights = opt_w3
            # prob3.value is the daily RU-LP objective; annualize to match
            # effective_cvar_limit and the band panel's operator-facing units.
            min_achievable_cvar = (
                float(prob3.value) * SQRT_252
                if prob3.value is not None
                else _cvar_from_ru(opt_w3)
            )
            phase3_cvar_cf = _compute_cvar(opt_w3)
            phase3_within = (
                min_achievable_cvar <= effective_cvar_limit
                if effective_cvar_limit is not None
                else True
            )
            attempts.append(PhaseAttempt(
                phase="phase_3_min_cvar",
                status="succeeded",
                solver="CLARABEL",
                objective_value=round(min_achievable_cvar, 6),
                wall_ms=_wall_p3,
                infeasibility_reason=None,
                cvar_at_solution=round(min_achievable_cvar, 6),
                cvar_at_solution_cf=round(abs(phase3_cvar_cf), 6),
                cvar_limit_effective=effective_cvar_limit,
                cvar_within_limit=phase3_within,
            ))
        else:
            attempts.append(PhaseAttempt(
                phase="phase_3_min_cvar", status="infeasible",
                solver="CLARABEL", objective_value=None, wall_ms=_wall_p3,
                infeasibility_reason="zero weights after clipping",
                cvar_limit_effective=effective_cvar_limit,
            ))
    else:
        attempts.append(PhaseAttempt(
            phase="phase_3_min_cvar", status="solver_failed",
            solver="CLARABEL", objective_value=None, wall_ms=_wall_p3,
            infeasibility_reason=str(status3),
            cvar_limit_effective=effective_cvar_limit,
        ))

    # Phase 3 is "always-solvable by construction" via the min-CVaR objective
    # on the base polytope. If it returns None despite a valid base polytope
    # (rare — usually a numerical solver glitch), don't discard a valid Phase 1
    # result. Only abort when all three phases failed.
    if phase1_weights is None and phase2_weights is None and phase3_weights is None:
        logger.error("constraint_polytope_empty", n_funds=n)
        return _empty_result("constraint_polytope_empty", "CLARABEL")

    if phase3_weights is None:
        logger.warning(
            "phase3_solver_glitch_phase1_or_2_valid",
            phase1_valid=phase1_weights is not None,
            phase2_valid=phase2_weights is not None,
        )
        phase3_expected_return = 0.0
    else:
        assert min_achievable_cvar is not None
        phase3_expected_return = float(mu @ phase3_weights)

    # ── Winner selection (Phase 1 > Phase 2 > Phase 3) ───────────────────
    # PR-A12.4 — gate Phase 1 / Phase 2 promotion on realized CVaR honouring
    # the operator's limit. Without this gate, the CLARABEL → SCS fallback
    # could return ``status=optimal`` with realized CVaR >> limit (SCS's
    # ``eps=1e-5`` tolerance is loose enough to admit large violations on
    # heavy-tailed universes). Observed on Growth 2026-04-17 post PR-A12.3:
    # Phase 1 (SCS) ``status=optimal``, realized 0.1714 vs limit 0.08 —
    # 2.14× overshoot silently promoted. Phase 3 is always-solvable by
    # construction (min-CVaR on the base polytope) and does not need
    # a within-limit gate — its below-floor state is reflected in the
    # ``phase_3_min_cvar_above_limit`` cascade summary downstream.
    _phase1_usable = (
        phase1_weights is not None
        and (effective_cvar_limit is None or _phase1_within_limit is True)
    )
    _phase2_usable = (
        phase2_weights is not None
        and (effective_cvar_limit is None or _phase2_within_limit is True)
    )
    # Robust mode (when caller passed robust=True): prefer Phase 2 (robust SOCP)
    # over Phase 1 if both are usable. This is the difference between "max return
    # with CVaR limit" (Phase 1) and "robust max return under ellipsoidal mu
    # uncertainty with CVaR limit" (Phase 2). Without this branch, the robust
    # flag is effectively a no-op for healthy universes.
    if robust and _phase2_usable:
        winner_w = phase2_weights
        winner_phase = "phase_2_ru_robust"
        winner_solver = phase2_solver
        winner_return = phase2_expected_return
        winner_status = "optimal"
    elif _phase1_usable:
        winner_w = phase1_weights
        winner_phase = "phase_1_ru_max_return"
        winner_solver = phase1_solver
        winner_return = phase1_expected_return
        winner_status = "optimal"
    elif _phase2_usable:
        winner_w = phase2_weights
        winner_phase = "phase_2_ru_robust"
        winner_solver = phase2_solver
        winner_return = phase2_expected_return
        winner_status = "optimal"
    else:
        winner_w = phase3_weights
        winner_phase = "phase_3_min_cvar"
        winner_solver = "CLARABEL"
        winner_return = phase3_expected_return
        within_limit = (
            min_achievable_cvar <= effective_cvar_limit
            if effective_cvar_limit is not None
            else True
        )
        winner_status = "optimal" if within_limit else "degraded"

    # PR-A17.1 C.2 — winner-selection trace. Captures which phase won,
    # whether each upstream phase was usable, and the full post-gate state
    # that feeds _build_result. Pairs with the executor's cascade_summary
    # mapping so we can see end-to-end how phase_3_min_cvar with
    # objective_value=0.0 resolves.
    logger.info(
        "phase_winner_selection_trace",
        phase1_usable=bool(_phase1_usable),
        phase1_weights_valid=(phase1_weights is not None),
        phase1_within_limit=_phase1_within_limit,
        phase2_usable=bool(_phase2_usable),
        phase2_weights_valid=(phase2_weights is not None),
        phase2_within_limit=_phase2_within_limit,
        phase3_weights_valid=(phase3_weights is not None),
        phase3_weights_sum=(
            float(phase3_weights.sum()) if phase3_weights is not None else None
        ),
        phase3_weights_nonzero=(
            int((phase3_weights > 1e-6).sum()) if phase3_weights is not None else None
        ),
        min_achievable_cvar=min_achievable_cvar,
        effective_cvar_limit=effective_cvar_limit,
        winning_phase=winner_phase,
        winner_status=winner_status,
        winner_return=winner_return,
    )

    assert winner_return is not None
    winner_cvar_ru = _cvar_from_ru(winner_w)
    band: dict[str, float] | None = (
        {
            "lower": round(phase3_expected_return, 6),
            "upper": round(float(winner_return), 6),
            "lower_at_cvar": round(min_achievable_cvar, 6),
            "upper_at_cvar": round(winner_cvar_ru, 6),
        }
        if min_achievable_cvar is not None
        else None
    )

    result = _build_result(
        winner_w, winner_solver, winner_status,
        winning_phase=winner_phase,
        min_achievable_cvar=(
            round(min_achievable_cvar, 6) if min_achievable_cvar is not None else None
        ),
        achievable_return_band=band,
    )

    logger.info(
        "fund_portfolio_optimized",
        n_funds=n, sharpe=result.sharpe_ratio,
        cvar_95=result.cvar_95, cvar_limit=effective_cvar_limit,
        solver=winner_solver, status=winner_status,
        winning_phase=winner_phase,
        min_achievable_cvar=(
            round(min_achievable_cvar, 6) if min_achievable_cvar is not None else None
        ),
        band_upper=band["upper"] if band else None,
        band_lower=band["lower"] if band else None,
    )
    return result


async def optimize_portfolio_pareto(
    block_ids: list[str],
    expected_returns: dict[str, float],
    cov_matrix: np.ndarray,
    constraints: ProfileConstraints,
    risk_free_rate: float = 0.04,
    pop_size: int = 100,
    n_gen: int = 200,
    calc_date: "date_type | None" = None,
    profile: str = "unknown",
    esg_scores: dict[str, float] | None = None,
    esg_weight: float = 0.0,
) -> ParetoResult:
    """Multi-objective NSGA-II portfolio optimization for IC Pareto visualization.

    WEEKLY / ON-DEMAND ONLY — NSGA-II takes 45–135s.
    Daily pipeline MUST use optimize_portfolio() (CLARABEL, 50–200ms).

    Falls back to single-objective CLARABEL if pymoo is not installed.

    Objectives:
        1. Maximize Sharpe (minimize -Sharpe)
        2. Minimize CVaR_95 (Cornish-Fisher adjusted)
        3. Optional: maximize ESG score (if esg_weight > 0)

    Constraint: portfolio_cvar <= cvar_limit (feasibility-first tournament).

    Returns ParetoResult with Pareto front weights and recommended allocation.
    """
    if calc_date is None:
        calc_date = date_type.today()

    try:
        from pymoo.algorithms.moo.nsga2 import NSGA2
        from pymoo.optimize import minimize as pymoo_minimize
    except ImportError:
        logger.warning(
            "pymoo not installed; falling back to CLARABEL single-objective. "
            "Install with: pip install netz-wealth-os[multiobjective]",
        )
        # Graceful fallback
        single = await optimize_portfolio(
            block_ids=block_ids,
            expected_returns=expected_returns,
            cov_matrix=cov_matrix,
            constraints=constraints,
            risk_free_rate=risk_free_rate,
        )
        return ParetoResult(
            pareto_weights=[list(single.weights.values())],
            pareto_sharpe=[single.sharpe_ratio or 0.0],
            pareto_cvar=[0.0],
            recommended_weights=single.weights,
            n_solutions=1,
            seed=0,
            input_hash="fallback",
            status="fallback_clarabel",
            solver_info="pymoo not installed",
        )

    seed = derive_seed(profile, calc_date)
    mu = np.array([expected_returns.get(bid, 0.0) for bid in block_ids])

    # Compute skewness and excess kurtosis from diagonal approximation
    # (No cross-asset moments available without raw returns — use zero as conservative)
    n = len(block_ids)
    skewness = np.zeros(n)
    excess_kurtosis = np.zeros(n)

    cvar_limit = (
        0.15 if constraints.cvar_limit is None else float(constraints.cvar_limit)
    )
    rf = risk_free_rate

    # Per-block bounds
    block_map = _build_block_map(constraints.blocks)
    xl = np.array([block_map[bid].min_weight if bid in block_map else 0.0 for bid in block_ids])
    xu = np.array([block_map[bid].max_weight if bid in block_map else 1.0 for bid in block_ids])

    # ESG scores array
    esg_arr = None
    if esg_scores and esg_weight > 0:
        esg_arr = np.array([esg_scores.get(bid, 0.0) for bid in block_ids])

    try:
        PortfolioProblem, PortfolioWeightRepair = _make_portfolio_problem_class()

        problem = PortfolioProblem(
            block_ids=block_ids,
            mu=mu,
            cov=cov_matrix,
            rf=rf,
            skewness=skewness,
            excess_kurtosis=excess_kurtosis,
            cvar_limit=cvar_limit,
            xl=xl,
            xu=xu,
            esg_scores=esg_arr,
            esg_weight=esg_weight,
        )

        algorithm = NSGA2(
            pop_size=pop_size,
            repair=PortfolioWeightRepair(),
        )

        def _run_pareto(
            _problem: "PortfolioProblem",
            _algorithm: "NSGA2",
            _seed: int,
            _n_gen: int,
        ) -> object:
            return pymoo_minimize(
                _problem,
                _algorithm,
                seed=_seed,
                termination=("n_gen", _n_gen),
                verbose=False,
            )

        result = await asyncio.to_thread(_run_pareto, problem, algorithm, seed, n_gen)

    except Exception as e:
        logger.error("nsga2_optimization_failed", error=str(e))
        single = await optimize_portfolio(
            block_ids=block_ids,
            expected_returns=expected_returns,
            cov_matrix=cov_matrix,
            constraints=constraints,
            risk_free_rate=risk_free_rate,
        )
        return ParetoResult(
            pareto_weights=[list(single.weights.values())],
            pareto_sharpe=[single.sharpe_ratio or 0.0],
            pareto_cvar=[0.0],
            recommended_weights=single.weights,
            n_solutions=1,
            seed=seed,
            input_hash=compute_input_hash(list(expected_returns.values())),
            status="fallback_clarabel",
            solver_info=str(e),
        )

    if result.X is None or len(result.X) == 0:
        single = await optimize_portfolio(
            block_ids=block_ids,
            expected_returns=expected_returns,
            cov_matrix=cov_matrix,
            constraints=constraints,
            risk_free_rate=risk_free_rate,
        )
        return ParetoResult(
            pareto_weights=[list(single.weights.values())],
            pareto_sharpe=[single.sharpe_ratio or 0.0],
            pareto_cvar=[0.0],
            recommended_weights=single.weights,
            n_solutions=1,
            seed=seed,
            input_hash=compute_input_hash(list(expected_returns.values())),
            status="no_feasible_solutions",
        )

    pareto_weights_arr = result.X  # (n_solutions, n_var)
    pareto_F = result.F             # (n_solutions, n_obj): [-sharpe, cvar, ...]

    pareto_sharpe_list = [-float(f[0]) for f in pareto_F]
    pareto_cvar_list = [float(f[1]) for f in pareto_F]

    # Recommended: max Sharpe among feasible solutions (CVaR <= limit)
    feasible_mask = np.array(pareto_cvar_list) <= cvar_limit
    if feasible_mask.any():
        feasible_sharpes = np.array(pareto_sharpe_list)
        feasible_sharpes[~feasible_mask] = -np.inf
        best_idx = int(np.argmax(feasible_sharpes))
    else:
        # No feasible — pick min CVaR
        best_idx = int(np.argmin(pareto_cvar_list))

    recommended_w = pareto_weights_arr[best_idx]
    recommended_weights = {bid: round(float(recommended_w[i]), 6) for i, bid in enumerate(block_ids)}

    input_hash = compute_input_hash(list(expected_returns.values()))

    return ParetoResult(
        pareto_weights=[list(row) for row in pareto_weights_arr],
        pareto_sharpe=pareto_sharpe_list,
        pareto_cvar=pareto_cvar_list,
        recommended_weights=recommended_weights,
        n_solutions=len(pareto_weights_arr),
        seed=seed,
        input_hash=input_hash,
        status="optimal",
    )

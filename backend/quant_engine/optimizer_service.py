"""Portfolio optimizer service.

Uses cvxpy with CLARABEL solver to compute optimal portfolio weights.
Objective: maximize Sharpe ratio (or minimize CVaR for conservative).
Constraints: weights sum to 1, per-block bounds, portfolio CVaR <= limit, long-only.
"""

import asyncio
from dataclasses import dataclass
from datetime import date as date_type

import cvxpy as cp
import numpy as np
import structlog

from app.utils.hashing import compute_input_hash, derive_seed

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
    sigma_p = float(np.sqrt(weights @ cov @ weights))
    port_skew = float(weights @ skewness)
    port_kurt = float(weights @ excess_kurtosis)

    z = sp_norm.ppf(alpha)  # base quantile
    z_cf = (
        z
        + (z**2 - 1) * port_skew / 6
        + (z**3 - 3 * z) * port_kurt / 24
        - (2 * z**3 - 5 * z) * port_skew**2 / 36
    )
    phi_z = sp_norm.pdf(z_cf)
    cvar = -(mu_p + sigma_p * z_cf) + sigma_p * phi_z / alpha
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


def _make_portfolio_problem_class():
    """Lazy factory for PortfolioProblem — only called when pymoo is available."""
    from pymoo.core.problem import Problem
    from pymoo.core.repair import Repair

    class PortfolioWeightRepair(Repair):
        """Repair operator: enforces sum=1 and per-block bounds.

        ALWAYS use Repair for weight constraints — penalty approach requires
        per-run tuning and is numerically unreliable for budget constraints.
        """

        def _do(self, problem, Z, **kwargs):
            Z = np.clip(Z, problem.xl, problem.xu)
            Z[Z < 1e-4] = 0.0
            row_sums = Z.sum(axis=1, keepdims=True)
            row_sums = np.where(row_sums == 0, 1.0, row_sums)
            return Z / row_sums

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

        def _evaluate(self, x, out, *args, **kwargs):
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
        # Max Sharpe approximation: maximize (return - rf) / risk
        # Use risk-adjusted return: maximize return - lambda * risk
        risk_aversion = 2.0  # moderate risk aversion
        prob = cp.Problem(
            cp.Maximize(port_return - risk_aversion * port_risk),
            cvx_constraints,
        )

    # Offload CPU-bound solver to thread pool to avoid blocking the event loop
    def _solve():
        try:
            prob.solve(solver=cp.CLARABEL, verbose=False)
        except cp.SolverError:
            try:
                prob.solve(solver=cp.SCS, verbose=False)
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
    port_vol = float(np.sqrt(opt_weights @ cov_matrix @ opt_weights))
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


async def optimize_fund_portfolio(
    fund_ids: list[str],
    fund_blocks: dict[str, str],
    expected_returns: dict[str, float],
    cov_matrix: np.ndarray,
    constraints: ProfileConstraints,
    risk_free_rate: float = 0.04,
    skewness: np.ndarray | None = None,
    excess_kurtosis: np.ndarray | None = None,
    current_weights: np.ndarray | None = None,
    turnover_cost: float = 0.0,
    robust: bool = False,
    uncertainty_level: float = 0.5,
    regime_cvar_multiplier: float = 1.0,
) -> FundOptimizationResult:
    """Optimize fund-level weights with block-group sum constraints.

    Unlike optimize_portfolio() which works at block level, this optimizes
    individual fund weights while enforcing block-level allocation bands
    from StrategicAllocation.

    CVaR enforcement cascade:
    1. Solve max risk-adjusted return (primary)
    2. If CVaR violates limit → re-solve with variance ceiling derived from
       cvar_limit (max return subject to σ² ≤ σ²_max)
    3. If variance-capped solve infeasible → solve min_variance (safest
       allocation within block constraints)

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
        )

    mu = np.array([expected_returns.get(fid, 0.0) for fid in fund_ids])
    max_fund_w = constraints.max_single_fund_weight
    psd_cov = cp.psd_wrap(cov_matrix)

    # Pre-compute block structure (shared across all solve phases)
    block_map = {bc.block_id: bc for bc in constraints.blocks}
    block_fund_indices: dict[str, list[int]] = {}
    for i, fid in enumerate(fund_ids):
        block = fund_blocks.get(fid)
        if block:
            block_fund_indices.setdefault(block, []).append(i)

    def _build_base_constraints(w_var: cp.Variable) -> list:
        """Build constraints shared by all solve phases."""
        cs: list = [cp.sum(w_var) == 1]
        for i in range(n):
            cs.append(w_var[i] <= max_fund_w)
        for blk_id, indices in block_fund_indices.items():
            if blk_id in block_map:
                bc = block_map[blk_id]
                blk_sum = cp.sum([w_var[i] for i in indices])
                cs.append(blk_sum >= bc.min_weight)
                cs.append(blk_sum <= bc.max_weight)
        return cs

    async def _solve_problem(prob: cp.Problem) -> str | None:
        """Solve with CLARABEL → SCS fallback. Returns status."""
        def _do():
            try:
                prob.solve(solver=cp.CLARABEL, verbose=False)
                if prob.status not in ("optimal", "optimal_inaccurate"):
                    # CLARABEL failed — try SCS with looser tolerances
                    prob.solve(solver=cp.SCS, verbose=False,
                               eps=1e-5, max_iters=10000)
            except cp.SolverError:
                try:
                    prob.solve(solver=cp.SCS, verbose=False,
                               eps=1e-5, max_iters=10000)
                except cp.SolverError:
                    pass
        await asyncio.to_thread(_do)
        return prob.status

    def _extract_weights(w_var: cp.Variable) -> np.ndarray | None:
        """Clean and normalize solved weights. Returns None if degenerate."""
        if w_var.value is None:
            return None
        w_arr = np.maximum(w_var.value, 0)
        total = w_arr.sum()
        if total == 0:
            return None
        return w_arr / total

    # Resolve moments: use provided arrays or fall back to zeros
    _skew = skewness if skewness is not None else np.zeros(n)
    _kurt = excess_kurtosis if excess_kurtosis is not None else np.zeros(n)

    def _compute_cvar(w_arr: np.ndarray) -> float:
        """Compute parametric CVaR (Cornish-Fisher)."""
        return -parametric_cvar_cf(w_arr, mu, cov_matrix, _skew, _kurt)

    def _build_result(
        w_arr: np.ndarray, solver: str | None, status: str,
    ) -> FundOptimizationResult:
        """Build FundOptimizationResult from optimized weights."""
        ret = float(mu @ w_arr)
        vol = float(np.sqrt(w_arr @ cov_matrix @ w_arr))
        sharpe = (ret - risk_free_rate) / vol if vol > 0 else 0.0
        cvar_neg = _compute_cvar(w_arr)
        cvar_ok = cvar_neg >= cvar_limit if cvar_limit is not None else True

        fw = {fid: round(float(w_arr[i]), 6) for i, fid in enumerate(fund_ids)}
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
            cvar_95=round(cvar_neg, 6),
            cvar_limit=cvar_limit,
            cvar_within_limit=cvar_ok,
            status=status,
            solver_info=solver,
        )

    def _empty_result(status: str, solver: str | None = None) -> FundOptimizationResult:
        return FundOptimizationResult(
            weights={}, block_weights={}, expected_return=0.0,
            portfolio_volatility=0.0, sharpe_ratio=0.0,
            cvar_95=None, cvar_limit=cvar_limit,
            cvar_within_limit=False, status=status, solver_info=solver,
        )

    # ── Phase 1: Max risk-adjusted return (with optional turnover penalty) ──
    w1 = cp.Variable(n, nonneg=True)
    risk_aversion = 2.0
    objective_expr = mu @ w1 - risk_aversion * cp.quad_form(w1, psd_cov)
    phase1_constraints = _build_base_constraints(w1)

    if current_weights is not None and turnover_cost > 0:
        t1 = cp.Variable(n, nonneg=True)  # slack for |w - w_current|
        phase1_constraints += [
            t1 >= w1 - current_weights,
            t1 >= current_weights - w1,
        ]
        objective_expr = objective_expr - turnover_cost * cp.sum(t1)

    prob1 = cp.Problem(cp.Maximize(objective_expr), phase1_constraints)

    status1 = await _solve_problem(prob1)
    if status1 in (None, "solver_error"):
        return _empty_result("solver_failed", "Both CLARABEL and SCS failed")
    if status1 not in ("optimal", "optimal_inaccurate"):
        # If turnover penalty caused infeasibility, retry without it
        if current_weights is not None and turnover_cost > 0:
            logger.warning("turnover_penalty_infeasible_retrying_without")
            w1_retry = cp.Variable(n, nonneg=True)
            prob1_retry = cp.Problem(
                cp.Maximize(mu @ w1_retry - risk_aversion * cp.quad_form(w1_retry, psd_cov)),
                _build_base_constraints(w1_retry),
            )
            status1 = await _solve_problem(prob1_retry)
            if status1 in ("optimal", "optimal_inaccurate"):
                w1 = w1_retry
                prob1 = prob1_retry
            else:
                return _empty_result(f"infeasible: {status1}")
        else:
            return _empty_result(f"infeasible: {status1}")

    opt_w = _extract_weights(w1)
    if opt_w is None:
        return _empty_result("infeasible: zero weights")

    solver_name = prob1.solver_stats.solver_name if prob1.solver_stats else None

    # Check CVaR against limit
    cvar_neg = _compute_cvar(opt_w)
    cvar_ok = cvar_neg >= cvar_limit if cvar_limit is not None else True

    # Apply regime CVaR multiplier (tighter limit in adverse regimes)
    effective_cvar_limit = cvar_limit
    if cvar_limit is not None and regime_cvar_multiplier != 1.0:
        effective_cvar_limit = cvar_limit * regime_cvar_multiplier
        logger.info(
            "regime_cvar_multiplier_applied",
            original_limit=cvar_limit,
            effective_limit=effective_cvar_limit,
            multiplier=regime_cvar_multiplier,
        )
        # Re-check with effective limit
        cvar_ok = cvar_neg >= effective_cvar_limit

    if cvar_ok or effective_cvar_limit is None:
        result = _build_result(opt_w, solver_name, "optimal")
        logger.info(
            "fund_portfolio_optimized",
            n_funds=n, sharpe=result.sharpe_ratio,
            cvar_95=result.cvar_95, cvar_limit=effective_cvar_limit,
            solver=solver_name, status="optimal",
        )
        return result

    # ── Phase 1.5: Robust optimization (ellipsoidal uncertainty set) ──
    if robust:
        try:
            kappa = uncertainty_level * np.sqrt(n)
            # Cholesky of PSD-wrapped covariance for SOCP norm
            try:
                L = np.linalg.cholesky(cov_matrix)
            except np.linalg.LinAlgError:
                # Fallback: eigenvalue clipping for near-PSD matrices
                eigvals, eigvecs = np.linalg.eigh(cov_matrix)
                eigvals = np.maximum(eigvals, 1e-8)
                L = eigvecs @ np.diag(np.sqrt(eigvals))

            w_robust = cp.Variable(n, nonneg=True)
            robust_penalty = kappa * cp.norm(L.T @ w_robust, 2)
            robust_obj = cp.Maximize(
                mu @ w_robust - robust_penalty - risk_aversion * cp.quad_form(w_robust, psd_cov)
            )
            robust_constraints = _build_base_constraints(w_robust)
            prob_robust = cp.Problem(robust_obj, robust_constraints)

            status_robust = await _solve_problem(prob_robust)
            if status_robust in ("optimal", "optimal_inaccurate"):
                opt_w_robust = _extract_weights(w_robust)
                if opt_w_robust is not None:
                    cvar_robust = _compute_cvar(opt_w_robust)
                    cvar_ok_robust = (
                        cvar_robust >= effective_cvar_limit
                        if effective_cvar_limit is not None
                        else True
                    )
                    if cvar_ok_robust:
                        result = _build_result(opt_w_robust, "CLARABEL:robust", "optimal:robust")
                        logger.info(
                            "robust_optimization_succeeded",
                            sharpe=result.sharpe_ratio,
                            cvar_95=result.cvar_95,
                            kappa=round(kappa, 4),
                        )
                        return result
                    else:
                        logger.warning(
                            "robust_cvar_still_violated",
                            cvar_95=round(cvar_robust, 6),
                            limit=effective_cvar_limit,
                        )
            else:
                logger.warning("robust_optimization_infeasible", status=status_robust)
        except Exception as e:
            logger.warning("robust_optimization_failed", error=str(e))

    # ── Phase 2: CVaR violated — re-solve with variance ceiling ──
    # Derive σ_max from cvar_limit under normal approximation:
    # CVaR_95 = σ * (-z + φ(z)/α) - μ  →  σ_max = |cvar_limit| / cvar_coeff
    from scipy.stats import norm as sp_norm

    z_alpha = sp_norm.ppf(0.05)  # -1.645
    phi_z = sp_norm.pdf(z_alpha)
    cvar_coeff = -z_alpha + phi_z / 0.05  # ≈ 3.71
    max_var = (abs(cvar_limit) / cvar_coeff) ** 2

    logger.warning(
        "cvar_violation_re_optimizing",
        cvar_95=round(cvar_neg, 6), cvar_limit=cvar_limit,
        max_vol_target=round(abs(cvar_limit) / cvar_coeff, 6),
    )

    w2 = cp.Variable(n, nonneg=True)
    constraints2 = _build_base_constraints(w2)
    constraints2.append(cp.quad_form(w2, psd_cov) <= max_var)

    prob2 = cp.Problem(cp.Maximize(mu @ w2), constraints2)
    status2 = await _solve_problem(prob2)

    if status2 in ("optimal", "optimal_inaccurate"):
        opt_w2 = _extract_weights(w2)
        if opt_w2 is not None:
            solver2 = prob2.solver_stats.solver_name if prob2.solver_stats else solver_name
            result = _build_result(opt_w2, solver2, "optimal:cvar_constrained")
            logger.info(
                "cvar_constrained_re_optimization_succeeded",
                cvar_95=result.cvar_95, cvar_limit=cvar_limit,
                cvar_within_limit=result.cvar_within_limit,
                sharpe=result.sharpe_ratio,
            )
            return result

    # ── Phase 3: Variance-capped infeasible — fall back to min_variance ──
    logger.warning("cvar_capped_infeasible_falling_back_to_min_variance")

    w3 = cp.Variable(n, nonneg=True)
    prob3 = cp.Problem(
        cp.Minimize(cp.quad_form(w3, psd_cov)),
        _build_base_constraints(w3),
    )
    status3 = await _solve_problem(prob3)

    if status3 in ("optimal", "optimal_inaccurate"):
        opt_w3 = _extract_weights(w3)
        if opt_w3 is not None:
            result = _build_result(opt_w3, "min_variance_fallback", "optimal:min_variance_fallback")
            logger.warning(
                "min_variance_fallback_used",
                cvar_95=result.cvar_95, cvar_limit=cvar_limit,
                cvar_within_limit=result.cvar_within_limit,
            )
            return result

    # All three phases failed — return original Phase 1 result with violation flag
    result = _build_result(opt_w, solver_name, "optimal:cvar_violated")
    logger.error(
        "all_cvar_enforcement_phases_failed",
        cvar_95=result.cvar_95, cvar_limit=cvar_limit,
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

    cvar_limit = constraints.cvar_limit or 0.15
    rf = risk_free_rate

    # Per-block bounds
    block_map = {c.block_id: c for c in constraints.blocks}
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

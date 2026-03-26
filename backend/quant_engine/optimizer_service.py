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
) -> FundOptimizationResult:
    """Optimize fund-level weights with block-group sum constraints.

    Unlike optimize_portfolio() which works at block level, this optimizes
    individual fund weights while enforcing block-level allocation bands
    from StrategicAllocation.

    Constraints:
        sum(w) == 1                          (fully invested)
        w >= 0                               (long only)
        w_i <= max_single_fund_weight        (concentration limit)
        sum(w[funds_in_block]) >= block_min  (block floor)
        sum(w[funds_in_block]) <= block_max  (block ceiling)
    """
    n = len(fund_ids)
    if n == 0:
        return FundOptimizationResult(
            weights={}, block_weights={}, expected_return=0.0,
            portfolio_volatility=0.0, sharpe_ratio=0.0,
            cvar_95=None, cvar_limit=constraints.cvar_limit,
            cvar_within_limit=True, status="empty",
        )

    mu = np.array([expected_returns.get(fid, 0.0) for fid in fund_ids])
    w = cp.Variable(n, nonneg=True)

    port_return = mu @ w
    port_risk = cp.quad_form(w, cp.psd_wrap(cov_matrix))

    cvx_constraints = [cp.sum(w) == 1]

    # Per-fund concentration limit
    max_fund_w = constraints.max_single_fund_weight
    for i in range(n):
        cvx_constraints.append(w[i] <= max_fund_w)

    # Block-group sum constraints from StrategicAllocation
    block_map = {bc.block_id: bc for bc in constraints.blocks}
    block_fund_indices: dict[str, list[int]] = {}
    for i, fid in enumerate(fund_ids):
        block = fund_blocks.get(fid)
        if block:
            block_fund_indices.setdefault(block, []).append(i)

    for block_id, indices in block_fund_indices.items():
        if block_id in block_map:
            bc = block_map[block_id]
            block_sum = cp.sum([w[i] for i in indices])
            cvx_constraints.append(block_sum >= bc.min_weight)
            cvx_constraints.append(block_sum <= bc.max_weight)

    # Objective: risk-adjusted return (max Sharpe approximation)
    risk_aversion = 2.0
    prob = cp.Problem(
        cp.Maximize(port_return - risk_aversion * port_risk),
        cvx_constraints,
    )

    def _solve():
        try:
            prob.solve(solver=cp.CLARABEL, verbose=False)
        except cp.SolverError:
            try:
                prob.solve(solver=cp.SCS, verbose=False)
            except cp.SolverError:
                pass

    await asyncio.to_thread(_solve)

    if prob.status is None or prob.status == "solver_error":
        return FundOptimizationResult(
            weights={}, block_weights={}, expected_return=0.0,
            portfolio_volatility=0.0, sharpe_ratio=0.0,
            cvar_95=None, cvar_limit=constraints.cvar_limit,
            cvar_within_limit=False, status="solver_failed",
            solver_info="Both CLARABEL and SCS failed",
        )

    if prob.status not in ("optimal", "optimal_inaccurate"):
        return FundOptimizationResult(
            weights={}, block_weights={}, expected_return=0.0,
            portfolio_volatility=0.0, sharpe_ratio=0.0,
            cvar_95=None, cvar_limit=constraints.cvar_limit,
            cvar_within_limit=False, status=f"infeasible: {prob.status}",
        )

    opt_w = np.maximum(w.value, 0)
    total = opt_w.sum()
    if total == 0:
        return FundOptimizationResult(
            weights={}, block_weights={}, expected_return=0.0,
            portfolio_volatility=0.0, sharpe_ratio=0.0,
            cvar_95=None, cvar_limit=constraints.cvar_limit,
            cvar_within_limit=False, status="infeasible: zero weights",
        )
    opt_w /= total

    port_ret = float(mu @ opt_w)
    port_vol = float(np.sqrt(opt_w @ cov_matrix @ opt_w))
    sharpe = (port_ret - risk_free_rate) / port_vol if port_vol > 0 else 0.0

    # CVaR post-check (parametric Cornish-Fisher, zero skew/kurtosis as conservative)
    skewness = np.zeros(n)
    excess_kurtosis = np.zeros(n)
    cvar_val = parametric_cvar_cf(opt_w, mu, cov_matrix, skewness, excess_kurtosis)
    cvar_neg = -cvar_val  # convention: negative = loss

    cvar_limit = constraints.cvar_limit
    cvar_ok = True
    if cvar_limit is not None:
        cvar_ok = cvar_neg >= cvar_limit  # e.g. -0.05 >= -0.08 means within limit

    # Build per-fund weight dict
    fund_weights = {fid: round(float(opt_w[i]), 6) for i, fid in enumerate(fund_ids)}

    # Aggregate to block-level weights
    blk_weights: dict[str, float] = {}
    for fid, fw in fund_weights.items():
        blk = fund_blocks.get(fid, "unknown")
        blk_weights[blk] = blk_weights.get(blk, 0.0) + fw

    solver_name = prob.solver_stats.solver_name if prob.solver_stats else None

    logger.info(
        "fund_portfolio_optimized",
        n_funds=n,
        sharpe=round(sharpe, 4),
        volatility=round(port_vol, 6),
        cvar_95=round(cvar_neg, 6),
        cvar_limit=cvar_limit,
        cvar_within_limit=cvar_ok,
        solver=solver_name,
    )

    return FundOptimizationResult(
        weights=fund_weights,
        block_weights={k: round(v, 6) for k, v in blk_weights.items()},
        expected_return=round(port_ret, 6),
        portfolio_volatility=round(port_vol, 6),
        sharpe_ratio=round(sharpe, 4),
        cvar_95=round(cvar_neg, 6),
        cvar_limit=cvar_limit,
        cvar_within_limit=cvar_ok,
        status="optimal",
        solver_info=solver_name,
    )


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
            "Install with: pip install netz-wealth-os[multiobjective]"
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

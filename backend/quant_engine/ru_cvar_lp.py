"""Rockafellar-Uryasev CVaR LP formulation helpers (PR-A12).

Implements the auxiliary-variable linearization from Uryasev (2000):
    CVaR_alpha(L) = min_zeta { zeta + (1/(1-alpha)) E[(L - zeta)+] }

where L is the loss random variable. For a portfolio with weights w and
historical scenarios ``returns_scenarios`` (shape (T, N)), the loss in
scenario i is L_i = -returns_scenarios[i, :] @ w. The expectation is
replaced by the empirical mean (1/T) sum_i max(L_i - zeta, 0), and the
max is linearized via slack variables u_i >= 0, u_i >= L_i - zeta.

Two entry points:

- :func:`build_ru_cvar_constraints` — CVaR as a constraint (Phase 1 / 2).
- :func:`build_ru_cvar_objective` — CVaR as the minimization objective
  (Phase 3 min-CVaR LP, always feasible on a non-empty constraint
  polytope).

Both return the auxiliary ``zeta`` / ``u`` variables so callers can
introspect the realized CVaR post-solve via
``float(zeta.value + u.value.sum() / ((1 - alpha) * T))``.
"""

from __future__ import annotations

import cvxpy as cp
import numpy as np
import structlog

_log = structlog.get_logger(__name__)


def build_ru_cvar_constraints(
    w_var: cp.Variable,
    returns_scenarios: np.ndarray,
    alpha: float,
    cvar_limit: float,
) -> tuple[list[cp.constraints.Constraint], cp.Variable, cp.Variable]:
    """Return ``(constraints, zeta, u)`` enforcing CVaR_alpha(w) <= cvar_limit.

    Loss-distribution convention: ``cvar_limit > 0`` is the maximum tail
    loss the operator tolerates (e.g. ``0.05`` = 5% loss).

    Internally::

        L_i  = -returns_scenarios[i, :] @ w_var       (loss = -return)
        CVaR = zeta + (1 / ((1 - alpha) * T)) * sum(u) <= cvar_limit
        u_i >= L_i - zeta,   u_i >= 0
    """
    T, N = returns_scenarios.shape
    if w_var.shape != (N,):
        raise ValueError(f"w_var shape {w_var.shape} != ({N},)")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if cvar_limit <= 0.0:
        raise ValueError(f"cvar_limit must be > 0, got {cvar_limit}")

    _log.info(
        "ru_cvar_constraint_built",
        function="build_ru_cvar_constraints",
        alpha_input=float(alpha),
        tail_fraction_used=float(1.0 - alpha),
        T=int(T),
        N=int(N),
        cvar_limit_input=float(cvar_limit),
        R_mean=float(returns_scenarios.mean()),
        R_std=float(returns_scenarios.std()),
        loss_sign_convention="L_i = -R_i @ w",
    )

    zeta = cp.Variable()
    u = cp.Variable(T, nonneg=True)
    losses = -returns_scenarios @ w_var

    cvar_expr = zeta + (1.0 / ((1.0 - alpha) * T)) * cp.sum(u)
    constraints: list[cp.constraints.Constraint] = [
        u >= losses - zeta,
        cvar_expr <= cvar_limit,
    ]
    return constraints, zeta, u


def build_ru_cvar_objective(
    w_var: cp.Variable,
    returns_scenarios: np.ndarray,
    alpha: float,
) -> tuple[cp.Expression, list[cp.constraints.Constraint], cp.Variable, cp.Variable]:
    """Return ``(cvar_expr, slack_constraints, zeta, u)`` for min-CVaR.

    Usage::

        cvar_expr, slack_cs, zeta, u = build_ru_cvar_objective(w, R, 0.95)
        prob = cp.Problem(cp.Minimize(cvar_expr), slack_cs + base_constraints)

    Phase 3 min-CVaR LP is feasible for any non-empty constraint polytope
    (RU slacks ``u_i`` are unbounded above), so this path is the
    always-solvable floor of the PR-A12 cascade.
    """
    T, N = returns_scenarios.shape
    if w_var.shape != (N,):
        raise ValueError(f"w_var shape {w_var.shape} != ({N},)")
    if not (0.0 < alpha < 1.0):
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")

    zeta = cp.Variable()
    u = cp.Variable(T, nonneg=True)
    losses = -returns_scenarios @ w_var
    cvar_expr = zeta + (1.0 / ((1.0 - alpha) * T)) * cp.sum(u)
    slack_constraints: list[cp.constraints.Constraint] = [u >= losses - zeta]
    return cvar_expr, slack_constraints, zeta, u


def realized_cvar_from_weights(
    weights: np.ndarray,
    returns_scenarios: np.ndarray,
    alpha: float,
) -> float:
    """Empirical CVaR_alpha of a realized weight vector (post-solve check).

    Used for telemetry and tests — computes CVaR directly from the
    scenario matrix without re-solving an LP. Equivalent to the LP
    objective value at optimality.
    """
    T, _ = returns_scenarios.shape
    losses = -returns_scenarios @ weights
    # Empirical VaR at level alpha = (1-alpha)-quantile of losses from above.
    # For CVaR: average of losses exceeding VaR.
    var_threshold = float(np.quantile(losses, alpha))
    tail = losses[losses >= var_threshold]
    tail_count = int(tail.size)
    expected_tail_mass = (1.0 - alpha) * T
    _log.info(
        "ru_cvar_realized_verifier",
        function="realized_cvar_from_weights",
        alpha_input=float(alpha),
        tail_fraction_used=float(1.0 - alpha),
        T=int(T),
        var_threshold=var_threshold,
        tail_count_observed=tail_count,
        tail_count_expected=float(expected_tail_mass),
        loss_sign_convention="L_i = -R_i @ weights",
    )
    if tail_count == 0:
        return float(var_threshold)
    # RU definition equivalent: CVaR = zeta + mean(max(L - zeta, 0)) / (1 - alpha)
    # At zeta = VaR, this reduces to mean of tail losses when tail mass = (1-alpha).
    return float(tail.mean())

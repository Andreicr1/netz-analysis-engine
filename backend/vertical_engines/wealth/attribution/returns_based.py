"""Sharpe 1992 returns-based style analysis.

Minimise ||r_fund - R_styles w||^2  s.t.  sum(w) = 1, w >= 0  (QP / CLARABEL).

Pure sync, designed for ``asyncio.to_thread()``. No DB, no I/O, no
module-level asyncio primitives. Configurable only through function args.
"""

from __future__ import annotations

import cvxpy as cp
import numpy as np
import numpy.typing as npt
import structlog

from vertical_engines.wealth.attribution.models import (
    ReturnsBasedResult,
    StyleExposure,
)

logger = structlog.get_logger()

_EPS_VARIANCE = 1e-12
_COND_NUMBER_LIMIT = 1e8


def fit_style(
    r_fund: npt.NDArray[np.float64],
    r_styles: npt.NDArray[np.float64],
    tickers: tuple[str, ...],
    min_months: int = 36,
    periods_per_year: int = 12,
) -> ReturnsBasedResult:
    """Solve Sharpe 1992 style regression.

    Parameters
    ----------
    r_fund : shape (T,) monthly fund excess returns.
    r_styles : shape (T, M) monthly returns per style basket column.
    tickers : length M, one ticker per column of ``r_styles``.
    min_months : minimum observations. Below threshold returns ``degraded``.
    periods_per_year : annualisation factor for tracking error.

    """
    t_obs = r_fund.shape[0]
    m_styles = r_styles.shape[1]

    if m_styles != len(tickers):
        return _degraded(tickers, t_obs, "ticker_mismatch")
    if t_obs != r_styles.shape[0]:
        return _degraded(tickers, t_obs, "shape_mismatch")
    if t_obs < min_months:
        return _degraded(tickers, t_obs, "insufficient_history")

    if not np.isfinite(r_fund).all() or not np.isfinite(r_styles).all():
        return _degraded(tickers, t_obs, "non_finite_inputs")

    styles_var = r_styles.var(axis=0)
    if (styles_var < _EPS_VARIANCE).any():
        return _degraded(tickers, t_obs, "zero_variance_style")

    cond = float(np.linalg.cond(r_styles))
    if not np.isfinite(cond) or cond > _COND_NUMBER_LIMIT:
        return _degraded(tickers, t_obs, "rank_deficient")

    w = cp.Variable(m_styles)
    constraints = [cp.sum(w) == 1, w >= 0]  # type: ignore[attr-defined]
    objective = cp.Minimize(cp.sum_squares(r_fund - r_styles @ w))  # type: ignore[attr-defined]
    prob = cp.Problem(objective, constraints)

    try:
        prob.solve(solver=cp.CLARABEL, verbose=False)  # type: ignore[no-untyped-call]
    except cp.error.SolverError as exc:
        logger.warning("returns_based_solver_error", error=str(exc))
        try:
            prob.solve(solver=cp.SCS, verbose=False)  # type: ignore[no-untyped-call]
        except cp.error.SolverError:
            return _degraded(tickers, t_obs, "solver_failed")

    if prob.status != "optimal" or w.value is None:
        return _degraded(tickers, t_obs, str(prob.status or "solver_failed"))

    weights = np.clip(np.asarray(w.value, dtype=np.float64), 0.0, None)
    w_sum = float(weights.sum())
    if w_sum > 0:
        weights = weights / w_sum

    fitted = r_styles @ weights
    residuals = r_fund - fitted
    ss_res = float(np.sum(residuals ** 2))
    centered = r_fund - float(r_fund.mean())
    ss_tot = float(np.sum(centered ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > _EPS_VARIANCE else 0.0
    # Bound R² in [0, 1] — OLS with constraints can produce negative R² if
    # the constrained fit is worse than the mean.
    r_squared = max(0.0, min(1.0, r_squared))

    te_annualized = float(np.std(residuals) * np.sqrt(periods_per_year))
    confidence = max(0.0, r_squared)

    exposures = tuple(
        StyleExposure(ticker=tickers[i], weight=float(weights[i]))
        for i in range(m_styles)
    )

    return ReturnsBasedResult(
        exposures=exposures,
        r_squared=float(r_squared),
        tracking_error_annualized=te_annualized,
        confidence=float(confidence),
        n_months=t_obs,
        degraded=False,
        degraded_reason=None,
    )


def _degraded(
    tickers: tuple[str, ...],
    n_months: int,
    reason: str,
) -> ReturnsBasedResult:
    empty = tuple(StyleExposure(ticker=t, weight=0.0) for t in tickers)
    return ReturnsBasedResult(
        exposures=empty,
        r_squared=0.0,
        tracking_error_annualized=0.0,
        confidence=0.0,
        n_months=n_months,
        degraded=True,
        degraded_reason=reason,
    )


__all__ = ["fit_style", "ReturnsBasedResult"]

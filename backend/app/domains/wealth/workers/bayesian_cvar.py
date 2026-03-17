"""Bayesian CVaR worker — ADVI daily, NUTS weekly.

Run AFTER portfolio_eval.py in the daily pipeline (needs portfolio weights from portfolio_snapshots).
Updates portfolio_snapshots with Bayesian CVaR credible intervals.

Optional dependency: pymc>=5.0 (bayesian group).
Install: pip install netz-wealth-os[bayesian]
"""

import asyncio
import gc
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

import numpy as np
import structlog
from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.settings import settings
from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from app.utils.hashing import compute_input_hash, derive_seed

logger = structlog.get_logger()

ADVI_N_APPROX = 30000
ADVI_POSTERIOR_DRAWS = 1000
RHAT_THRESHOLD = 1.01
ESS_TAIL_MIN = 400


@contextmanager
def _pymc_cleanup():
    """Context manager: ensures PyMC model + trace are deleted and gc.collect() runs.

    Required in long-running FastAPI processes — PyMC/pytensor leave
    compiled graph objects in memory. Without this, 3 daily profiles = 150MB leak.
    """
    try:
        yield
    finally:
        gc.collect()



def _compute_bayesian_cvar_advi(
    returns: list[float],
    confidence: float = 0.95,
    n_approx: int = ADVI_N_APPROX,
    posterior_draws: int = ADVI_POSTERIOR_DRAWS,
) -> dict[str, float] | None:
    """Bayesian CVaR with credible intervals using ADVI approximation.

    Model: r ~ StudentT(nu, mu, sigma)
    CVaR computed via ANALYTICAL closed-form formula over posterior samples.

    DO NOT use sample_posterior_predictive — it is O(n_posterior × n_sim)
    and introduces unnecessary Monte Carlo error. The analytical formula is exact.

    Returns dict with cvar_mean, cvar_lower_5, cvar_upper_95.

    Sign convention: all three values are returned as NEGATIVE numbers
    (loss magnitude as negative), consistent with cvar_current stored in
    portfolio_snapshots which is produced by compute_cvar_from_returns()
    (mean of worst tail returns, naturally negative).

    The DB check constraint enforces:
        cvar_lower_5 <= cvar_current <= cvar_upper_95
    With negative values this reads as:
        more-negative-bound <= point-estimate <= less-negative-bound
    i.e. cvar_lower_5 is the 5th percentile of the posterior CVaR
    distribution (worst-case tail) and cvar_upper_95 is the 95th
    percentile (best-case tail within the credible interval).

    Returns None on convergence failure or import error.
    """
    try:
        import arviz as az
        import pymc as pm
        from scipy.stats import t as t_dist
    except ImportError:
        logger.warning("PyMC not installed; cannot compute Bayesian CVaR. "
                       "Install with: pip install netz-wealth-os[bayesian]")
        return None

    r = np.array(returns, dtype=float)
    if len(r) < 30:
        return None

    model = None
    trace = None
    approx = None

    with _pymc_cleanup():
        try:
            with pm.Model() as model:
                mu = pm.Normal("mu", mu=0.0, sigma=0.02)
                sigma = pm.HalfNormal("sigma", sigma=0.05)
                nu = pm.Exponential("nu", lam=1.0 / 10.0)  # prior mean=10
                _ = pm.StudentT("returns", nu=nu, mu=mu, sigma=sigma, observed=r)
                approx = pm.fit(n=n_approx, method="advi", progressbar=False)

            with model:
                trace = approx.sample(draws=posterior_draws)

            # Convergence check — modern standard (Vehtari et al. 2021)
            summary = az.summary(trace, round_to=4)
            rhat_max = float(summary["r_hat"].max())
            ess_tail_min = float(summary["ess_tail"].min())

            if rhat_max > RHAT_THRESHOLD or ess_tail_min < ESS_TAIL_MIN:
                logger.warning(
                    "bayesian_cvar_convergence_warning",
                    rhat_max=rhat_max,
                    ess_tail_min=ess_tail_min,
                )
                return None

            # Analytical CVaR for Student-t
            # For r ~ t(ν, μ, σ), CVaR_α = -μ + σ * φ(t_α; ν) / α * (ν + t_α²) / (ν - 1)
            # The formula yields a positive loss magnitude. We negate it so all CVaR
            # values in portfolio_snapshots share cvar_current's sign convention
            # (negative = loss), satisfying the DB check constraint:
            #   cvar_lower_5 <= cvar_current <= cvar_upper_95
            alpha = 1.0 - confidence  # 0.05 for 95% CVaR
            mu_samp = trace.posterior["mu"].values.flatten()
            sig_samp = trace.posterior["sigma"].values.flatten()
            nu_samp = trace.posterior["nu"].values.flatten()

            cvar_list = []
            for mu_i, sig_i, nu_i in zip(mu_samp, sig_samp, nu_samp, strict=False):
                if nu_i <= 1.0:
                    continue  # CVaR undefined for ν ≤ 1 (infinite mean)
                t_alpha = float(t_dist.ppf(alpha, df=nu_i))
                pdf_t = float(t_dist.pdf(t_alpha, df=nu_i))
                # Positive loss magnitude (formula convention)
                cvar_i = float(-mu_i + sig_i * (pdf_t / alpha) * (nu_i + t_alpha**2) / (nu_i - 1))
                cvar_list.append(cvar_i)

            if not cvar_list:
                return None

            cvar_samples = np.array(cvar_list)
            # Negate: positive loss magnitudes → negative numbers matching cvar_current.
            # Percentile order is flipped: 95th positive percentile becomes the
            # most-negative lower bound; 5th becomes the least-negative upper bound.
            return {
                "cvar_mean": round(-float(np.mean(cvar_samples)), 6),
                "cvar_lower_5": round(-float(np.percentile(cvar_samples, 95)), 6),
                "cvar_upper_95": round(-float(np.percentile(cvar_samples, 5)), 6),
            }

        except Exception as e:
            logger.warning("bayesian_cvar_advi_failed", error=str(e))
            return None
        finally:
            del model, trace, approx
            gc.collect()


async def _fetch_portfolio_returns(
    db: AsyncSession,
    profile: str,
    lookback_days: int = 252,
) -> list[float]:
    """Fetch recent portfolio-level returns from the latest portfolio snapshot weights."""
    # Get the current snapshot weights
    snap_stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    snap = (await db.execute(snap_stmt)).scalar_one_or_none()
    if snap is None or not snap.weights:
        return []

    weights: dict[str, float] = {k: float(v) for k, v in snap.weights.items()}

    # Get active fund IDs for the blocks present in the snapshot weights.
    # One representative fund per block is used for NAV data; the block weight
    # from the snapshot drives the portfolio-return aggregation below.
    cutoff = snap.snapshot_date

    # Fetch NAV returns for each fund in weights
    fund_stmt = (
        select(Fund.fund_id, Fund.block_id)
        .where(Fund.block_id.in_(list(weights.keys())))
        .where(Fund.is_active.is_(True))
    )
    funds = (await db.execute(fund_stmt)).fetchall()
    if not funds:
        return []

    fund_map: dict[str, list] = {}  # block_id → list of fund_ids
    for row in funds:
        block = str(row.block_id)
        fund_map.setdefault(block, []).append(row.fund_id)

    # Pick one representative fund per block (first active)
    rep_fund_ids = [ids[0] for ids in fund_map.values() if ids]
    if not rep_fund_ids:
        return []

    start_date = cutoff - timedelta(days=lookback_days + 30)

    nav_stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            and_(
                NavTimeseries.instrument_id.in_(rep_fund_ids),
                NavTimeseries.nav_date >= start_date,
                NavTimeseries.nav_date <= cutoff,
                NavTimeseries.return_1d.isnot(None),
            )
        )
        .order_by(NavTimeseries.nav_date)
    )
    rows = (await db.execute(nav_stmt)).fetchall()
    if not rows:
        return []

    # Build a mapping from fund_id → block_id so we can look up the portfolio weight
    fund_id_to_block: dict = {}
    for row in funds:
        fund_id_to_block[str(row.fund_id)] = str(row.block_id)  # Fund.fund_id stays

    # Aggregate to portfolio return using actual portfolio weights per date.
    # For each date we accumulate:
    #   weighted_sum  = Σ weight_i * return_i
    #   weight_sum    = Σ weight_i   (for normalisation)
    #   raw_returns   = [return_i, …]  (equal-weight fallback)
    date_weighted_sum: dict = defaultdict(float)
    date_weight_sum: dict = defaultdict(float)
    date_raw: dict = defaultdict(list)

    for row in rows:
        if row.return_1d is not None:
            ret = float(row.return_1d)
            block = fund_id_to_block.get(str(row.instrument_id), "")
            w = weights.get(block, 0.0)
            date_weighted_sum[row.nav_date] += w * ret
            date_weight_sum[row.nav_date] += w
            date_raw[row.nav_date].append(ret)

    # Compute portfolio return per date; fall back to equal-weight when the
    # snapshot weights dict does not cover the funds present on that date.
    portfolio_returns = []
    for nav_date in sorted(date_weighted_sum.keys()):
        w_sum = date_weight_sum[nav_date]
        if w_sum > 0:
            portfolio_returns.append(date_weighted_sum[nav_date] / w_sum)
        else:
            # Equal-weight fallback — no matching block weights found in snapshot
            raw = date_raw[nav_date]
            if raw:
                portfolio_returns.append(sum(raw) / len(raw))

    return portfolio_returns[-lookback_days:]


async def run_bayesian_cvar() -> dict[str, Any]:
    """Run Bayesian CVaR ADVI for all 3 profiles and update portfolio_snapshots.

    Skipped entirely if FEATURE_BAYESIAN_CVAR is not enabled.
    Returns a summary of what was computed.

    Three-phase design to avoid holding a DB connection during CPU-bound ADVI:
      Phase 1 — Read-only fetches (brief, no transaction held).
      Phase 2 — CPU-bound ADVI via asyncio.to_thread (zero DB involvement).
      Phase 3 — Short write transaction that upserts all three profiles atomically.
    """
    VALID_PROFILES = {"conservative", "moderate", "growth"}

    if not getattr(settings, "feature_bayesian_cvar", False):
        logger.info("bayesian_cvar_skipped", reason="FEATURE_BAYESIAN_CVAR=false")
        return {"skipped": True, "reason": "feature flag disabled"}

    profiles = ["conservative", "moderate", "growth"]
    results: dict[str, Any] = {}
    today = date.today()

    # ------------------------------------------------------------------
    # Phase 1: Read-only fetches — no open transaction held.
    # Each profile gets brief SELECTs; the session is released after the
    # loop so the connection returns to the pool before ADVI starts.
    # ------------------------------------------------------------------
    returns_by_profile: dict[str, list[float]] = {}
    async with async_session() as db:
        for profile in profiles:
            assert profile in VALID_PROFILES, f"Invalid profile: {profile}"
            returns = await _fetch_portfolio_returns(db, profile)
            if len(returns) < 30:
                logger.warning(
                    "bayesian_cvar_insufficient_data",
                    profile=profile,
                    n_obs=len(returns),
                )
                results[profile] = {"status": "insufficient_data"}
            else:
                returns_by_profile[profile] = returns

    # ------------------------------------------------------------------
    # Phase 2: CPU-bound ADVI — no DB connection held at all.
    # asyncio.to_thread offloads the blocking PyMC computation to a
    # thread-pool worker so the event loop remains responsive.
    # ------------------------------------------------------------------
    ci_by_profile: dict[str, dict[str, float]] = {}
    for profile, returns in returns_by_profile.items():
        ci = await asyncio.to_thread(_compute_bayesian_cvar_advi, returns)
        if ci is None:
            results[profile] = {"status": "convergence_failure"}
        else:
            ci_by_profile[profile] = ci

    # ------------------------------------------------------------------
    # Phase 3: Short write transaction — seconds, not minutes.
    # All three profile updates are committed atomically.
    # ------------------------------------------------------------------
    async with async_session() as db:
        async with db.begin():
            for profile, ci in ci_by_profile.items():
                stmt = (
                    update(PortfolioSnapshot)
                    .where(
                        PortfolioSnapshot.profile == profile,
                        PortfolioSnapshot.snapshot_date == today,
                    )
                    .values(
                        cvar_lower_5=ci["cvar_lower_5"],
                        cvar_upper_95=ci["cvar_upper_95"],
                    )
                )
                await db.execute(stmt)

                seed = derive_seed(profile, today)
                input_hash = compute_input_hash(returns_by_profile[profile])
                results[profile] = {
                    "status": "ok",
                    "cvar_mean": ci["cvar_mean"],
                    "cvar_lower_5": ci["cvar_lower_5"],
                    "cvar_upper_95": ci["cvar_upper_95"],
                    "n_obs": len(returns_by_profile[profile]),
                    "seed": seed,
                    "input_hash": input_hash,
                }
                logger.info("bayesian_cvar_computed", profile=profile, **ci)

    return results

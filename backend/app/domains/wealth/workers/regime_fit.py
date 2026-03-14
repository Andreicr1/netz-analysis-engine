"""Markov regime switching worker — fits 2-state HMM on VIX log-levels.

Runs AFTER portfolio_eval in the daily pipeline. Enriches today's portfolio
snapshots with probabilistic regime classification via regime_probs JSONB.

Pipeline order:
    fred_ingestion → risk_calc → portfolio_eval → regime_fit

Usage:
    python -m app.workers.regime_fit

Requires optional dependency group [timeseries]:
    pip install netz-wealth-os[timeseries]

Architecture note: This is a SEPARATE worker. Do NOT merge into risk_calc.py
or portfolio_eval.py (God worker anti-pattern).
"""

import asyncio
from datetime import date, timedelta

import numpy as np
import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.models.macro import MacroData
from app.domains.wealth.models.portfolio import PortfolioSnapshot

logger = structlog.get_logger()

MIN_VIX_OBS = 252        # absolute minimum for stable 2-state Markov estimation
PREFERRED_VIX_LOOKBACK = 504  # 2 trading years (expanding window cap)


async def _fetch_vix_series(db: AsyncSession, lookback_days: int = PREFERRED_VIX_LOOKBACK) -> list[float]:
    """Fetch VIX daily observations from macro_data, ascending by date."""
    start_date = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(MacroData.value)
        .where(
            MacroData.series_id == "VIXCLS",
            MacroData.obs_date >= start_date,
        )
        .order_by(MacroData.obs_date)
    )
    result = await db.execute(stmt)
    return [float(row[0]) for row in result.all()]


def _fit_markov_regime(vix_series: list[float]) -> list[float] | None:
    """Fit 2-state Markov switching model on log-VIX.

    Returns filtered P(high-volatility) per observation, or None on failure.

    CRITICAL — filtered vs smoothed:
    - filtered_marginal_probabilities: P(regime_t | y_1…y_t) — causal, production-safe
    - smoothed_marginal_probabilities: P(regime_t | y_1…y_T) — look-ahead bias
    Using smoothed probabilities = live system knows future data. Always use filtered.

    Label consistency: regime with LOWER mean log-VIX = low-vol (risk-on).
    Sorting by mean after each fit prevents regime 0↔1 flipping across weekly re-fits.
    """
    try:
        from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
    except ImportError:
        logger.error(
            "statsmodels not installed — cannot run Markov regime fitting. "
            "Install with: pip install netz-wealth-os[timeseries]"
        )
        return None

    vix = np.log(np.array(vix_series, dtype=float))

    try:
        mod = MarkovRegression(
            endog=vix,
            k_regimes=2,
            trend="c",                # regime-specific intercept = mean log-VIX
            switching_variance=True,  # CRITICAL: distinct σ²; without this, regimes conflate
        )
        res = mod.fit(
            disp=False,
            search_reps=10,    # multiple EM random starts → avoid local optima
            em_iter=500,
            maxiter=100,       # convergence cap to bound wall-clock time
            tol=1e-4,          # convergence tolerance
        )
    except Exception as e:
        logger.warning("Markov fitting failed; threshold-based regime remains active", error=str(e))
        return None

    # CRITICAL: use filtered (causal), NOT smoothed (look-ahead)
    filtered_probs = res.filtered_marginal_probabilities  # shape (nobs, 2)

    # Enforce consistent regime label: lower mean log-VIX = low-vol regime (index 0)
    # This prevents regime index from flipping between weekly re-fits
    try:
        means = [float(res.params[f"const[{i}]"]) for i in range(2)]
    except KeyError:
        # Fallback for different param naming conventions across statsmodels versions
        all_params = dict(res.params)
        const_params = sorted(
            [(k, float(v)) for k, v in all_params.items() if "const" in k.lower()],
            key=lambda x: x[0],
        )
        means = [v for _, v in const_params[:2]] if len(const_params) >= 2 else [0.0, 1.0]

    low_vol_idx = int(np.argmin(means))   # lower mean log-VIX = low-vol = risk-on
    high_vol_col = 1 - low_vol_idx

    return filtered_probs[:, high_vol_col].tolist()


async def _update_snapshots_with_regime_probs(
    db: AsyncSession,
    p_high_vol_current: float,
) -> int:
    """Update today's portfolio snapshots with regime_probs for all profiles.

    Runs after portfolio_eval has already created today's snapshots.
    Returns the number of snapshots updated.
    """
    today = date.today()
    regime_probs_value = {
        "p_low_vol": round(1.0 - p_high_vol_current, 6),
        "p_high_vol": round(p_high_vol_current, 6),
    }

    stmt = (
        update(PortfolioSnapshot)
        .where(PortfolioSnapshot.snapshot_date == today)
        .values(regime_probs=regime_probs_value)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount


async def run_regime_fit() -> dict:
    """Fit Markov regime model on VIX and enrich today's portfolio snapshots."""
    logger.info("Starting Markov regime fitting")

    async with async_session() as db:
        vix_series = await _fetch_vix_series(db)

    n_obs = len(vix_series)
    if n_obs < MIN_VIX_OBS:
        logger.warning(
            "Insufficient VIX history for Markov fit — skipping",
            n_obs=n_obs,
            min_required=MIN_VIX_OBS,
        )
        return {"status": "skipped", "reason": "insufficient_vix_history", "n_obs": n_obs}

    logger.info("VIX history fetched", n_obs=n_obs)
    high_vol_probs = _fit_markov_regime(vix_series)

    if high_vol_probs is None:
        return {"status": "skipped", "reason": "fitting_failed"}

    p_high = round(float(high_vol_probs[-1]), 6)
    logger.info("Markov fit complete", p_high_vol_current=p_high, n_obs=n_obs)

    async with async_session() as db:
        n_updated = await _update_snapshots_with_regime_probs(db, p_high)

    logger.info("Regime probs written to snapshots", snapshots_updated=n_updated)
    return {
        "status": "completed",
        "p_high_vol_current": p_high,
        "n_obs": n_obs,
        "snapshots_updated": n_updated,
    }


if __name__ == "__main__":
    asyncio.run(run_regime_fit())

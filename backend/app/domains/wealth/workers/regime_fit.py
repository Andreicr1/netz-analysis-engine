"""Markov regime switching worker — fits 2-state HMM on VIX log-levels.

Runs AFTER portfolio_eval in the daily pipeline. Enriches today's portfolio
snapshots with probabilistic regime classification via regime_probs JSONB.

Persists the full HMM-classified regime series to macro_regime_history
hypertable (global, no org_id) so that risk_calc can consume per-date
regime states for conditional CVaR — replacing the VIX threshold proxy.

Pipeline order:
    fred_ingestion → risk_calc → portfolio_eval → regime_fit

Note: Operator must ensure `macro_ingestion.py` has been run to backfill VIX
data if the macro_data table is empty or lacks historical coverage.

Usage:
    python -m app.workers.regime_fit

Requires optional dependency group [timeseries]:
    pip install netz-wealth-os[timeseries]

Architecture note: This is a SEPARATE worker. Do NOT merge into risk_calc.py
or portfolio_eval.py (God worker anti-pattern).
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any, cast

import numpy as np
import structlog
from sqlalchemy import CursorResult, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.models.macro import MacroData
from app.domains.wealth.models.portfolio import PortfolioSnapshot

logger = structlog.get_logger()

LOCK_ID = 900_026
MIN_VIX_OBS = 252        # absolute minimum for stable 2-state Markov estimation
PREFERRED_VIX_LOOKBACK = 3650  # 10 calendar years (covers 3-year risk window with burn-in)

# Regime classification thresholds — aligned with regime_service._DEFAULT_THRESHOLDS
_VIX_RISK_OFF = 25.0
_VIX_EXTREME = 35.0
_P_HIGH_VOL_THRESHOLD = 0.6

_UPSERT_BATCH_SIZE = 500


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


async def _fetch_vix_series_with_dates(
    db: AsyncSession, lookback_days: int = PREFERRED_VIX_LOOKBACK,
) -> list[tuple[date, float]]:
    """Fetch VIX daily observations with dates from macro_data, ascending."""
    start_date = date.today() - timedelta(days=lookback_days)
    stmt = (
        select(MacroData.obs_date, MacroData.value)
        .where(
            MacroData.series_id == "VIXCLS",
            MacroData.obs_date >= start_date,
        )
        .order_by(MacroData.obs_date)
    )
    result = await db.execute(stmt)
    return [(row[0], float(row[1])) for row in result.all()]


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
        import warnings

        from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression
    except ImportError:
        logger.error(
            "statsmodels not installed — cannot run Markov regime fitting. "
            "Install with: pip install netz-wealth-os[timeseries]",
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
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # Suppress statsmodels EM and convergence warnings
            res = mod.fit(
                disp=False,
                search_reps=10,    # multiple EM random starts → avoid local optima
                em_iter=500,
                maxiter=100,       # convergence cap to bound wall-clock time
            )
    except Exception as e:
        logger.warning("Markov fitting failed; threshold-based regime remains active", error=str(e))
        return None

    # CRITICAL: use filtered (causal), NOT smoothed (look-ahead)
    filtered_probs = res.filtered_marginal_probabilities  # shape (nobs, 2)

    # Enforce consistent regime label: lower mean log-VIX = low-vol regime (index 0)
    # This prevents regime index from flipping between weekly re-fits.
    # Statsmodels 0.14+ returns res.params as a plain ndarray (not a labelled
    # Series), so we zip against res.model.param_names to build a name→value
    # map that works across versions.
    try:
        param_names = list(res.model.param_names)
        params_by_name = dict(zip(param_names, [float(v) for v in res.params], strict=False))
        means = [params_by_name[f"const[{i}]"] for i in range(2)]
    except (KeyError, IndexError, TypeError, AttributeError):
        # Final fallback: pull any params whose name contains "const", sorted
        # by name so const[0] precedes const[1] deterministically.
        try:
            param_names = list(res.model.param_names)
            const_pairs = sorted(
                [
                    (name, float(val))
                    for name, val in zip(param_names, [float(v) for v in res.params], strict=False)
                    if "const" in name.lower()
                ],
                key=lambda x: x[0],
            )
            means = [v for _, v in const_pairs[:2]] if len(const_pairs) >= 2 else [0.0, 1.0]
        except Exception:
            means = [0.0, 1.0]

    low_vol_idx = int(np.argmin(means))   # lower mean log-VIX = low-vol = risk-on
    high_vol_col = 1 - low_vol_idx

    return list(filtered_probs[:, high_vol_col].tolist())


def _classify_regime_from_probs(
    p_high_vol: float,
    vix_value: float | None,
) -> str:
    """Classify regime from HMM probabilities + VIX audit value.

    Aligned with regime_service._DEFAULT_THRESHOLDS for consistency:
    - VIX >= 35 (vix_extreme) → CRISIS override
    - p_high_vol >= 0.6 → RISK_OFF
    - Otherwise → RISK_ON
    """
    if vix_value is not None and vix_value >= _VIX_EXTREME:
        return "CRISIS"
    if p_high_vol >= _P_HIGH_VOL_THRESHOLD:
        return "RISK_OFF"
    return "RISK_ON"


async def _persist_regime_history(
    db: AsyncSession,
    dates: list[date],
    p_low_vol_series: list[float],
    p_high_vol_series: list[float],
    vix_series: list[float | None],
) -> int:
    """Upsert full regime series to macro_regime_history.

    ON CONFLICT (regime_date) DO UPDATE — idempotent.
    Batches of 500 rows to stay within asyncpg parameter limits.
    Returns number of rows upserted.
    """
    total = len(dates)
    if total == 0:
        return 0

    upserted = 0
    for batch_start in range(0, total, _UPSERT_BATCH_SIZE):
        batch_end = min(batch_start + _UPSERT_BATCH_SIZE, total)
        values_parts: list[str] = []
        params: dict[str, object] = {}

        for i in range(batch_start, batch_end):
            idx = i - batch_start
            p_low = round(p_low_vol_series[i], 6)
            p_high = round(p_high_vol_series[i], 6)
            vix_val = vix_series[i] if i < len(vix_series) else None
            regime = _classify_regime_from_probs(p_high, vix_val)

            values_parts.append(
                f"(:d{idx}, :pl{idx}, :ph{idx}, :r{idx}, :v{idx}, now())"
            )
            params[f"d{idx}"] = dates[i]
            params[f"pl{idx}"] = p_low
            params[f"ph{idx}"] = p_high
            params[f"r{idx}"] = regime
            params[f"v{idx}"] = round(vix_val, 2) if vix_val is not None else None

        sql = f"""
            INSERT INTO macro_regime_history
                (regime_date, p_low_vol, p_high_vol, classified_regime, vix_value, computed_at)
            VALUES {', '.join(values_parts)}
            ON CONFLICT (regime_date) DO UPDATE SET
                p_low_vol = EXCLUDED.p_low_vol,
                p_high_vol = EXCLUDED.p_high_vol,
                classified_regime = EXCLUDED.classified_regime,
                vix_value = EXCLUDED.vix_value,
                computed_at = EXCLUDED.computed_at
        """  # noqa: S608
        await db.execute(text(sql), params)
        upserted += batch_end - batch_start

    await db.commit()
    return upserted


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
    result = cast(CursorResult[Any], await db.execute(stmt))
    await db.commit()
    return result.rowcount


async def run_regime_fit() -> dict[str, Any]:
    """Fit Markov regime model on VIX, persist full series, enrich snapshots."""
    logger.info("Starting Markov regime fitting")

    async with async_session() as db:
        vix_with_dates = await _fetch_vix_series_with_dates(db)

    n_obs = len(vix_with_dates)
    if n_obs < MIN_VIX_OBS:
        logger.warning(
            "Insufficient VIX history for Markov fit — skipping",
            n_obs=n_obs,
            min_required=MIN_VIX_OBS,
        )
        return {"status": "skipped", "reason": "insufficient_vix_history", "n_obs": n_obs}

    dates_list = [d for d, _ in vix_with_dates]
    vix_values = [v for _, v in vix_with_dates]

    logger.info("VIX history fetched", n_obs=n_obs)
    high_vol_probs = _fit_markov_regime(vix_values)

    if high_vol_probs is None:
        return {"status": "skipped", "reason": "fitting_failed"}

    p_high = round(float(high_vol_probs[-1]), 6)
    logger.info("Markov fit complete", p_high_vol_current=p_high, n_obs=n_obs)

    # Persist full regime history BEFORE discarding any data
    p_high_vol_series = high_vol_probs
    p_low_vol_series = [1.0 - p for p in p_high_vol_series]
    vix_or_none: list[float | None] = list(vix_values)

    async with async_session() as db:
        n_persisted = await _persist_regime_history(
            db, dates_list, p_low_vol_series, p_high_vol_series, vix_or_none,
        )
    logger.info("Regime history persisted", rows_upserted=n_persisted)

    # Update today's portfolio snapshots with current regime probs
    async with async_session() as db:
        n_updated = await _update_snapshots_with_regime_probs(db, p_high)

    logger.info("Regime probs written to snapshots", snapshots_updated=n_updated)
    return {
        "status": "completed",
        "p_high_vol_current": p_high,
        "n_obs": n_obs,
        "rows_persisted": n_persisted,
        "snapshots_updated": n_updated,
    }


if __name__ == "__main__":
    asyncio.run(run_regime_fit())

"""ipca_estimation — Kelly-Pruitt-Su IPCA factor model fit.

Advisory lock : 900_092
Frequency     : quarterly (default; can run on-demand for backtest)
Idempotent    : yes — INSERT a new fit row per (engine, universe_hash, fit_date).
                Older rows preserved for drift comparison.
Scope         : global (no RLS) — factor_model_fits is shared.

Reads equity_characteristics_monthly + nav_monthly_returns_agg, fits
IPCA via quant_engine/factor_model_ipca_service.fit_universe (which
applies walk-forward CV to pick K), persists gamma + factor_returns
+ diagnostics to factor_model_fits, and computes drift vs the most
recent prior fit per universe.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory
from quant_engine.factor_model_ipca_service import fit_universe
from quant_engine.ipca.drift_monitor import compute_gamma_drift

logger = structlog.get_logger()

LOCK_ID = 900_092

CHARS_COLS = [
    "size_log_mkt_cap",
    "book_to_market",
    "mom_12_1",
    "quality_roa",
    "investment_growth",
    "profitability_gross",
]

_PANEL_SQL = """\
SELECT
    e.instrument_id,
    e.as_of,
    e.size_log_mkt_cap, e.book_to_market, e.mom_12_1,
    e.quality_roa, e.investment_growth, e.profitability_gross,
    n.compound_return AS monthly_return
FROM equity_characteristics_monthly e
JOIN nav_monthly_returns_agg n
  ON n.instrument_id = e.instrument_id
  AND n.month = date_trunc('month', e.as_of)::date
WHERE e.as_of <= :asof
"""


async def run_ipca_estimation(
    asof: date | None = None,
    min_panel_size: int = 300,
) -> dict[str, Any]:
    """Entry point. Acquires advisory lock, builds panel, fits IPCA, persists."""
    if asof is None:
        asof = date.today()

    async with async_session_factory() as db:
        acquired = await db.scalar(
            text("SELECT pg_try_advisory_lock(:lock)"), {"lock": LOCK_ID}
        )
        if not acquired:
            logger.info("ipca_estimation skip — lock held")
            return {"status": "skipped", "reason": "lock_held"}
        try:
            return await _run(db, asof=asof, min_panel_size=min_panel_size)
        except Exception:
            await db.rollback()
            raise
        finally:
            try:
                await db.execute(
                    text("SELECT pg_advisory_unlock(:lock)"), {"lock": LOCK_ID}
                )
            except Exception:
                logger.warning("ipca_estimation_unlock_failed", exc_info=True)


async def _run(
    db: Any,
    asof: date,
    min_panel_size: int,
) -> dict[str, Any]:
    logger.info("ipca_estimation_started", asof=str(asof))

    # The CAGG has a daily auto-refresh policy (migration 0049/0069).
    # Manual refresh via CALL requires autocommit which is tricky in async
    # sessions. Skip — the data is fresh enough for quarterly fits.

    # Load panel
    res = await db.execute(text(_PANEL_SQL), {"asof": asof})
    rows = res.all()
    if not rows:
        logger.info("ipca_estimation_no_data")
        return {"status": "no_data", "fits": 0}

    df = pd.DataFrame(
        [
            {
                "instrument_id": str(r.instrument_id),
                "month": pd.Timestamp(r.as_of),
                "size_log_mkt_cap": _to_float(r.size_log_mkt_cap),
                "book_to_market": _to_float(r.book_to_market),
                "mom_12_1": _to_float(r.mom_12_1),
                "quality_roa": _to_float(r.quality_roa),
                "investment_growth": _to_float(r.investment_growth),
                "profitability_gross": _to_float(r.profitability_gross),
                "monthly_return": _to_float(r.monthly_return),
            }
            for r in rows
        ]
    )

    df.set_index(["instrument_id", "month"], inplace=True)
    df.sort_index(inplace=True)

    # Drop rows with any NaN in chars or return
    valid = df.dropna(subset=CHARS_COLS + ["monthly_return"])
    n_obs = len(valid)
    logger.info("ipca_panel_loaded", total_rows=len(df), valid_rows=n_obs)

    if n_obs < min_panel_size:
        logger.info("ipca_estimation_skipped_small_panel", n_obs=n_obs, min=min_panel_size)
        return {"status": "skipped", "reason": "panel_too_small", "n_obs": n_obs}

    # Universe hash — stable MD5 of sorted instrument IDs
    instrument_ids = sorted(valid.index.get_level_values(0).unique().tolist())
    universe_hash = hashlib.md5(
        ",".join(instrument_ids).encode()
    ).hexdigest()[:16]

    # Fit
    chars = valid[CHARS_COLS]
    returns = valid[["monthly_return"]]

    logger.info(
        "ipca_fitting",
        n_instruments=len(instrument_ids),
        n_obs=n_obs,
        universe_hash=universe_hash,
    )
    try:
        fit = fit_universe(returns, chars)
    except Exception:
        logger.exception("ipca_fit_failed")
        return {"status": "error", "reason": "fit_failed"}

    # Drift vs prior fit
    drift = None
    try:
        stmt_old = text("""
            SELECT gamma_loadings FROM factor_model_fits
            WHERE engine = 'ipca' AND universe_hash = :hash
            ORDER BY fit_date DESC LIMIT 1
        """)
        res_old = await db.execute(stmt_old, {"hash": universe_hash})
        row_old = res_old.first()
        if row_old and row_old.gamma_loadings:
            gamma_old_data = row_old.gamma_loadings
            if isinstance(gamma_old_data, str):
                gamma_old_data = json.loads(gamma_old_data)
            gamma_old = np.array(gamma_old_data["values"], dtype=np.float64)
            drift = compute_gamma_drift(gamma_old, fit.gamma)
            logger.info("ipca_gamma_drift", drift=drift)
    except Exception:
        logger.warning("ipca_drift_computation_failed", exc_info=True)

    # Persist
    gamma_json = {
        "rows": CHARS_COLS,
        "cols": [f"f{i+1}" for i in range(fit.K)],
        "values": fit.gamma.tolist(),
    }
    dates_str = (
        [d.isoformat() for d in fit.dates.date]
        if fit.dates is not None
        else []
    )
    # factor_returns shape from ipca is (K, T); transpose to (T, K) for JSONB
    factor_returns_json = {
        "dates": dates_str,
        "values": fit.factor_returns.T.tolist(),
    }

    await db.execute(
        text("""
            INSERT INTO factor_model_fits (
                fit_id, engine, fit_date, universe_hash, k_factors,
                gamma_loadings, factor_returns, oos_r_squared,
                converged, n_iterations
            ) VALUES (
                gen_random_uuid(), 'ipca', :fit_date, :hash, :k,
                CAST(:gamma AS jsonb), CAST(:f_returns AS jsonb), :oos_r2,
                :converged, :n_iter
            )
        """),
        {
            "fit_date": asof,
            "hash": universe_hash,
            "k": fit.K,
            "gamma": json.dumps(gamma_json),
            "f_returns": json.dumps(factor_returns_json),
            "oos_r2": float(fit.oos_r_squared) if fit.oos_r_squared is not None else None,
            "converged": fit.converged,
            "n_iter": fit.n_iterations,
        },
    )
    await db.commit()

    summary = {
        "status": "succeeded",
        "fits": 1,
        "k_factors": fit.K,
        "oos_r_squared": float(fit.oos_r_squared) if fit.oos_r_squared is not None else None,
        "converged": fit.converged,
        "n_iterations": fit.n_iterations,
        "n_instruments": len(instrument_ids),
        "n_obs": n_obs,
        "universe_hash": universe_hash,
        "drift": drift,
    }
    logger.info("ipca_estimation_completed", **summary)
    return summary


def _to_float(v: Any) -> float:
    if v is None:
        return np.nan
    return float(v)

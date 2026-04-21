"""Worker for quarterly IPCA factor model estimation."""
import json
import uuid
from datetime import date

import numpy as np
import pandas as pd
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from quant_engine.factor_model_ipca_service import fit_universe
from quant_engine.ipca.drift_monitor import compute_gamma_drift

logger = structlog.get_logger()

# Lock ID for IPCA estimation
LOCK_ID_IPCA_ESTIMATION = 900_092

async def run_ipca_estimation(db: AsyncSession, asof: date | None = None) -> None:
    """Run IPCA estimation for each asset class with sufficient panel history."""
    if asof is None:
        asof = date.today()
    
    logger.info("ipca_estimation_started", asof=asof)
    
    # 1. Discover asset classes with enough data
    stmt_classes = text(
        """
        SELECT DISTINCT instrument_id
        FROM equity_characteristics_monthly
        """
    )
    # Actually, we need to partition by asset_class or strategy. Let's assume there's one global panel for now
    # or one per "universe_hash". The prompt says "Refits for each asset class with panel ≥ 300 instrument-months."
    # Let's group by asset class. We'll join instruments_global to get asset_class.
    stmt = text(
        """
        SELECT i.asset_class,
               e.instrument_id,
               e.as_of,
               e.size, e.value, e.momentum, e.quality, e.investment, e.profitability,
               n.nav_date,
               (array_agg(n.nav ORDER BY n.nav_date DESC))[1] AS nav_eom
        FROM equity_characteristics_monthly e
        JOIN instruments_universe i ON i.instrument_id = e.instrument_id
        LEFT JOIN nav_timeseries n 
          ON n.instrument_id = e.instrument_id 
          AND date_trunc('month', n.nav_date)::date = date_trunc('month', e.as_of)::date
        WHERE e.as_of <= :asof
        GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10
        """
    )
    res = await db.execute(stmt, {"asof": asof})
    rows = res.all()
    if not rows:
        logger.info("ipca_estimation_no_data")
        return
        
    df = pd.DataFrame([
        {
            "asset_class": r.asset_class or "Equity",
            "instrument_id": str(r.instrument_id),
            "obs_date": r.as_of,
            "size": float(r.size) if r.size else np.nan,
            "value": float(r.value) if r.value else np.nan,
            "momentum": float(r.momentum) if r.momentum else np.nan,
            "quality": float(r.quality) if r.quality else np.nan,
            "investment": float(r.investment) if r.investment else np.nan,
            "profitability": float(r.profitability) if r.profitability else np.nan,
            "nav_eom": float(r.nav_eom) if r.nav_eom else np.nan,
        }
        for r in rows
    ])
    
    # Needs MultiIndex (instrument_id, month)
    df["month"] = pd.to_datetime(df["obs_date"])
    df.set_index(["instrument_id", "month"], inplace=True)
    df.sort_index(inplace=True)
    
    # Calculate returns
    df["return"] = df.groupby(level="instrument_id")["nav_eom"].pct_change()
    
    chars_cols = ["size", "value", "momentum", "quality", "investment", "profitability"]
    
    for ac, group in df.groupby("asset_class"):
        valid_rows = group.dropna(subset=chars_cols + ["return"])
        if len(valid_rows) < 300:
            logger.info("ipca_estimation_skipped_small_panel", asset_class=ac, n_obs=len(valid_rows))
            continue
            
        chars = valid_rows[chars_cols]
        returns = valid_rows[["return"]]
        
        logger.info("ipca_fitting", asset_class=ac, n_obs=len(chars))
        try:
            fit = fit_universe(returns, chars)
        except Exception as e:
            logger.warning("ipca_fit_failed", asset_class=ac, exc=str(e))
            continue
            
        # Check drift
        stmt_old = text(
            """
            SELECT gamma_loadings FROM factor_model_fits
            WHERE engine = 'ipca' AND universe_hash = :ac
            ORDER BY fit_date DESC LIMIT 1
            """
        )
        res_old = await db.execute(stmt_old, {"ac": ac})
        row_old = res_old.first()
        if row_old:
            gamma_old = np.array(row_old.gamma_loadings)
            try:
                compute_gamma_drift(gamma_old, fit.gamma)
            except Exception as e:
                logger.warning("ipca_drift_computation_failed", exc=str(e))
                
        # Persist
        fit_id = uuid.uuid4()
        dates_str = [d.isoformat() for d in fit.dates] if fit.dates is not None else []
        factor_returns_json = {
            "dates": dates_str,
            "values": fit.factor_returns.tolist()
        }
        
        stmt_insert = text(
            """
            INSERT INTO factor_model_fits (
                fit_id, engine, fit_date, universe_hash, k_factors,
                gamma_loadings, factor_returns, oos_r_squared, converged, n_iterations
            ) VALUES (
                :fit_id, 'ipca', :fit_date, :ac, :k_factors,
                :gamma, :f_returns, :oos_r2, :converged, :n_iter
            )
            """
        )
        await db.execute(
            stmt_insert,
            {
                "fit_id": fit_id,
                "fit_date": asof,
                "ac": ac,
                "k_factors": fit.K,
                "gamma": json.dumps(fit.gamma.tolist()),
                "f_returns": json.dumps(factor_returns_json),
                "oos_r2": float(fit.oos_r_squared) if fit.oos_r_squared is not None else None,
                "converged": fit.converged,
                "n_iter": fit.n_iterations,
            }
        )
        
    await db.commit()
    logger.info("ipca_estimation_completed")

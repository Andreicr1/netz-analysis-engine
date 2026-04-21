"""IPCA attribution rail."""
from __future__ import annotations

import json
from datetime import date
from uuid import UUID

import numpy as np
import statsmodels.api as sm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from quant_engine.ipca.fit import IPCAFit
from vertical_engines.wealth.attribution.models import AttributionRequest, IPCAResult

logger = structlog.get_logger()


async def load_latest_ipca_fit(
    db: AsyncSession, asset_class: str
) -> IPCAFit | None:
    """Load latest converged IPCA fit for asset class."""
    stmt = text(
        """
        SELECT k_factors, gamma_loadings, factor_returns, oos_r_squared, converged, n_iterations
        FROM factor_model_fits
        WHERE engine = 'ipca' AND universe_hash = :asset_class AND converged = true
        ORDER BY fit_date DESC
        LIMIT 1
        """
    )
    res = await db.execute(stmt, {"asset_class": asset_class})
    row = res.first()
    if not row:
        return None
        
    factor_returns_dict = row.factor_returns
    # Extract factor_returns matrix and dates
    # Assuming factor_returns is stored as {"dates": [...], "values": [[...], ...]}
    dates_str = factor_returns_dict.get("dates", [])
    import pandas as pd
    dates = pd.DatetimeIndex(dates_str) if dates_str else None
    factor_returns = np.array(factor_returns_dict.get("values", []))

    return IPCAFit(
        gamma=np.array(row.gamma_loadings),
        factor_returns=factor_returns,
        K=row.k_factors,
        intercept=False,
        r_squared=0.0,
        oos_r_squared=float(row.oos_r_squared) if row.oos_r_squared is not None else 0.0,
        converged=row.converged,
        n_iterations=row.n_iterations,
        dates=dates,
    )


async def run_ipca_rail(request: AttributionRequest, db: AsyncSession) -> IPCAResult | None:
    """Execute IPCA attribution rail (Option A)."""
    if not request.fund_asset_class:
        return None
        
    fit = await load_latest_ipca_fit(db, request.fund_asset_class)
    if not fit or fit.oos_r_squared is None or fit.oos_r_squared < 0.50:
        return None

    # Fetch monthly returns for fund
    stmt = text(
        """
        SELECT date_trunc('month', nav_date)::date AS month,
               (array_agg(nav ORDER BY nav_date DESC))[1] AS nav_eom
        FROM nav_timeseries
        WHERE instrument_id = :fund_id
          AND nav IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """
    )
    res = await db.execute(stmt, {"fund_id": request.fund_instrument_id})
    rows = res.all()
    if len(rows) < 12:  # require at least 12 months for regression
        return None
        
    import pandas as pd
    fund_returns_df = pd.DataFrame(
        [(r.month, float(r.nav_eom)) for r in rows],
        columns=["month", "nav"]
    )
    fund_returns_df.set_index("month", inplace=True)
    fund_returns_df["return"] = fund_returns_df["nav"].pct_change()
    fund_returns_df.dropna(inplace=True)
    
    if fit.dates is None:
        return None

    factor_df = pd.DataFrame(
        fit.factor_returns.T,
        index=fit.dates.date, # match index type with month
        columns=[f"factor_{i}" for i in range(fit.K)]
    )
    
    # Align fund returns and factor returns
    aligned = pd.concat([fund_returns_df["return"], factor_df], axis=1, join="inner")
    if len(aligned) < 12:
        return None
        
    # Time-series regression: r_fund_t = α + β' f_t + ε_t
    y = aligned["return"].values
    X = aligned[[f"factor_{i}" for i in range(fit.K)]].values
    X_sm = sm.add_constant(X)
    
    try:
        model = sm.OLS(y, X_sm).fit()
        alpha = float(model.params[0])
        beta = model.params[1:]
    except Exception as e:
        logger.warning("ipca_regression_failed", error=str(e))
        return None

    f_t_mean = X.mean(axis=0)
    contribution_per_factor = beta * f_t_mean

    factor_names = ["Size", "Value", "Momentum", "Quality", "Investment", "Profitability"]
    
    return IPCAResult(
        factor_names=factor_names[:fit.K],
        factor_exposures=beta.tolist(),
        factor_returns_contribution=contribution_per_factor.tolist(),
        alpha=alpha,
        confidence=fit.oos_r_squared,
    )

"""IPCA attribution rail."""
from __future__ import annotations

import json
from datetime import date, timedelta
from uuid import UUID

import pandas as pd
import numpy as np
import statsmodels.api as sm
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from quant_engine.ipca.fit import IPCAFit
from vertical_engines.wealth.attribution.models import AttributionRequest, IPCAResult
from vertical_engines.wealth.attribution.holdings_based import resolve_fund_cik, latest_period_for_cik

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
    """Execute IPCA attribution rail (Option B: Instrumented)."""
    if not request.fund_asset_class:
        return None
        
    fit = await load_latest_ipca_fit(db, request.fund_asset_class)
    if not fit or fit.oos_r_squared is None or fit.oos_r_squared < 0.50:
        return None

    # Option B: Get fund CIK and latest holdings
    cik = await resolve_fund_cik(db, request.fund_instrument_id)
    if not cik:
        return None
        
    not_before = request.asof - timedelta(days=int(30.4375 * 9))
    period = await latest_period_for_cik(db, cik, not_before=not_before)
    if not period:
        return None

    # Fetch characteristics for top 10 holdings
    stmt_chars = text(
        """
        WITH top_holdings AS (
            SELECT cusip, pct_of_nav
            FROM sec_nport_holdings
            WHERE cik = :cik AND report_date = :period
              AND pct_of_nav IS NOT NULL AND pct_of_nav > 0
            ORDER BY pct_of_nav DESC
            LIMIT 10
        ),
        mapped_holdings AS (
            SELECT h.cusip, h.pct_of_nav, COALESCE(iu1.instrument_id, iu2.instrument_id) AS instrument_id
            FROM top_holdings h
            LEFT JOIN instruments_universe iu1
              ON iu1.attributes->>'cusip' = h.cusip
            LEFT JOIN instruments_universe iu2
              ON iu2.isin LIKE ('US' || h.cusip || '_')
            WHERE COALESCE(iu1.instrument_id, iu2.instrument_id) IS NOT NULL
        ),
        latest_chars AS (
            SELECT e.instrument_id,
                   e.size_log_mkt_cap AS size,
                   e.book_to_market AS value,
                   e.mom_12_1 AS momentum,
                   e.quality_roa AS quality,
                   e.investment_growth AS investment,
                   e.profitability_gross AS profitability,
                   ROW_NUMBER() OVER(PARTITION BY e.instrument_id ORDER BY e.as_of DESC) as rn
            FROM mapped_holdings m
            JOIN equity_characteristics_monthly e ON e.instrument_id = m.instrument_id
            WHERE e.as_of <= :asof
        )
        SELECT m.pct_of_nav,
               c.size, c.value, c.momentum, c.quality, c.investment, c.profitability
        FROM mapped_holdings m
        JOIN latest_chars c ON c.instrument_id = m.instrument_id AND c.rn = 1
        """
    )
    res_chars = await db.execute(stmt_chars, {"cik": cik, "period": period, "asof": request.asof})
    rows_chars = res_chars.all()
    
    if not rows_chars:
        # Fallback to Option A if no holdings mapped
        return await _run_ipca_rail_option_a(request, db, fit)

    # Compute z_fund (weighted average of characteristics)
    total_weight = sum(float(r.pct_of_nav) for r in rows_chars)
    if total_weight == 0:
        return await _run_ipca_rail_option_a(request, db, fit)
        
    z_fund = np.zeros(6)
    for r in rows_chars:
        w = float(r.pct_of_nav) / total_weight
        z_fund[0] += w * float(r.size or 0.0)
        z_fund[1] += w * float(r.value or 0.0)
        z_fund[2] += w * float(r.momentum or 0.0)
        z_fund[3] += w * float(r.quality or 0.0)
        z_fund[4] += w * float(r.investment or 0.0)
        z_fund[5] += w * float(r.profitability or 0.0)

    # Implied beta = Gamma' * z_fund
    beta = fit.gamma.T @ z_fund
    
    # Calculate returns contribution
    factor_returns_period = fit.factor_returns_for_period(request.period_start, request.period_end)
    f_t_mean = factor_returns_period.mean(axis=1) if factor_returns_period.size > 0 else np.zeros(fit.K)
    contribution_per_factor = beta * f_t_mean
    
    # Estimate alpha using fixed beta
    alpha = await _estimate_alpha_fixed_beta(request, db, fit, beta)
    
    factor_names = ["Size", "Value", "Momentum", "Quality", "Investment", "Profitability"]
    
    return IPCAResult(
        factor_names=factor_names[:fit.K],
        factor_exposures=beta.tolist(),
        factor_returns_contribution=contribution_per_factor.tolist(),
        alpha=alpha,
        confidence=fit.oos_r_squared,
    )

async def _estimate_alpha_fixed_beta(request: AttributionRequest, db: AsyncSession, fit: IPCAFit, beta: np.ndarray) -> float:
    """Estimate alpha as the mean residual: r_fund - beta' * f_t."""
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
    if len(rows) < 12:
        return 0.0
        
    fund_returns_df = pd.DataFrame(
        [(r.month, float(r.nav_eom)) for r in rows],
        columns=["month", "nav"]
    )
    fund_returns_df.set_index("month", inplace=True)
    fund_returns_df["return"] = fund_returns_df["nav"].pct_change()
    fund_returns_df.dropna(inplace=True)
    
    if fit.dates is None:
        return 0.0

    factor_df = pd.DataFrame(
        fit.factor_returns.T,
        index=fit.dates.date, 
        columns=[f"factor_{i}" for i in range(fit.K)]
    )
    
    aligned = pd.concat([fund_returns_df["return"], factor_df], axis=1, join="inner")
    if len(aligned) < 12:
        return 0.0
        
    y = aligned["return"].values
    X = aligned[[f"factor_{i}" for i in range(fit.K)]].values
    
    # alpha = mean(y - X * beta)
    residuals = y - (X @ beta)
    return float(np.mean(residuals))

async def _run_ipca_rail_option_a(request: AttributionRequest, db: AsyncSession, fit: IPCAFit) -> IPCAResult | None:
    """Fallback to time-series regression if holdings data fails."""

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

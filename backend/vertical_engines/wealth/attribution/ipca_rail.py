"""IPCA attribution rail."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
import structlog
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from quant_engine.ipca.fit import IPCAFit
from quant_engine.ipca.preprocessing import rank_transform
from data_providers.identity.resolver import resolve_cik
from vertical_engines.wealth.attribution.holdings_based import (
    latest_period_for_cik,
)
from vertical_engines.wealth.attribution.models import AttributionRequest, IPCAResult

logger = structlog.get_logger()


async def load_latest_ipca_fit(
    db: AsyncSession, asset_class: str
) -> IPCAFit | None:
    """Load latest IPCA fit for asset class.

    Accepts fits that either converged cleanly OR hit max_iter but
    produced positive predictive signal (oos_r² > 0). KP-S 2019
    reports IPCA frequently converges asymptotically without clean
    break in max_iter iterations on equity panels — refusing those
    silently kills the rail in production.
    """
    stmt = text(
        """
        SELECT k_factors, gamma_loadings, factor_returns,
               oos_r_squared, converged, n_iterations
        FROM factor_model_fits
        WHERE engine = 'ipca'
          AND asset_class = :asset_class
          AND (converged = true OR oos_r_squared > 0.0)
        ORDER BY fit_date DESC, created_at DESC
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
    # IPCA validity gate. KP-S 2019 reports realistic out-of-sample R² in
    # the 0.02-0.05 band on equity panels — accept any positive signal.
    # A negative oos_r² means the model predicts worse than the historical
    # mean, in which case the rail abstains and the dispatcher falls through.
    if not fit or fit.oos_r_squared is None or fit.oos_r_squared <= 0.0:
        return None

    # Option B: Get fund CIK and latest holdings
    cik_identity = await resolve_cik(db, request.fund_instrument_id)
    cik = cik_identity.padded
    if not cik:
        return await _run_ipca_rail_option_a(request, db, fit)

    not_before = request.asof - timedelta(days=int(30.4375 * 9))
    period = await latest_period_for_cik(db, cik, not_before=not_before)
    if not period:
        return await _run_ipca_rail_option_a(request, db, fit)

    # --- Reference period: latest cross-section date <= request.asof ---
    stmt_ref = text(
        "SELECT MAX(as_of) AS ref_period FROM equity_characteristics_monthly WHERE as_of <= :asof"
    )
    ref_row = (await db.execute(stmt_ref, {"asof": request.asof})).first()
    ref_period = ref_row.ref_period if ref_row else None
    if ref_period is None:
        return await _run_ipca_rail_option_a(request, db, fit)

    # --- Full cross-section at ref_period (for rank transform) ---
    stmt_cs = text(
        """
        SELECT instrument_id,
               size_log_mkt_cap   AS size,
               book_to_market     AS value,
               mom_12_1           AS momentum,
               quality_roa        AS quality,
               investment_growth  AS investment,
               profitability_gross AS profitability
        FROM equity_characteristics_monthly
        WHERE as_of = :ref_period
        """
    )
    res_cs = await db.execute(stmt_cs, {"ref_period": ref_period})
    rows_cs = res_cs.all()
    if not rows_cs:
        return await _run_ipca_rail_option_a(request, db, fit)

    char_cols = ["size", "value", "momentum", "quality", "investment", "profitability"]
    cs_index = pd.MultiIndex.from_arrays(
        [[str(r.instrument_id) for r in rows_cs], [ref_period] * len(rows_cs)],
        names=["instrument_id", "as_of"],
    )

    def _safe_float(value: Any) -> float:
        """Preserve None as NaN so rank_transform can skip it.

        Coercing missing characteristics to 0.0 before ranking would
        inject a spurious sentinel value into the cross-section: any
        instrument with NULL chars would land at the bottom of every
        rank, shifting every other instrument's percentile upward and
        biasing z_fund / beta cross-sectionally — even for holdings
        with complete data. The rank_transform helper's own contract
        is 'NaNs allowed (skipped by rank)'; we honour that here.
        """
        return float("nan") if value is None else float(value)

    cs_df = pd.DataFrame(
        [{c: _safe_float(getattr(r, c)) for c in char_cols} for r in rows_cs],
        index=cs_index,
    )
    ranked_cs = rank_transform(cs_df)

    # --- Top-10 holdings + instrument_id mapping ---
    cik_candidates = cik_identity.candidates()
    stmt_holdings = text(
        """
        WITH top_holdings AS (
            SELECT cusip, pct_of_nav
            FROM sec_nport_holdings
            WHERE cik IN :candidates AND report_date = :period
              AND pct_of_nav IS NOT NULL AND pct_of_nav > 0
            ORDER BY pct_of_nav DESC
            LIMIT 10
        )
        SELECT h.pct_of_nav, COALESCE(iu1.instrument_id, iu2.instrument_id) AS instrument_id
        FROM top_holdings h
        LEFT JOIN instruments_universe iu1
          ON iu1.attributes->>'cusip' = h.cusip
        LEFT JOIN instruments_universe iu2
          ON iu2.isin LIKE ('US' || h.cusip || '_')
        WHERE COALESCE(iu1.instrument_id, iu2.instrument_id) IS NOT NULL
        """
    ).bindparams(bindparam("candidates", expanding=True))
    res_h = await db.execute(stmt_holdings, {"candidates": list(cik_candidates), "period": period})
    rows_h = res_h.all()
    if not rows_h:
        return await _run_ipca_rail_option_a(request, db, fit)

    # Inner-join holdings against ranked cross-section. Sum (not overwrite)
    # weights when multiple holdings map to the same instrument_id — happens
    # when dual share classes share an issuer-level instrument, when the
    # instruments_universe has both 8-char and 9-char CUSIPs for the same
    # security, or when N-PORT splits a position across multiple rows.
    # A dict comprehension would silently drop earlier rows and underweight
    # the instrument in z_fund / factor exposures.
    holdings_ids: dict[str, float] = {}
    for r in rows_h:
        iid = str(r.instrument_id)
        holdings_ids[iid] = holdings_ids.get(iid, 0.0) + float(r.pct_of_nav)
    matched = ranked_cs.loc[ranked_cs.index.get_level_values(0).isin(holdings_ids)]
    if matched.empty:
        return await _run_ipca_rail_option_a(request, db, fit)

    # Compute z_fund (weighted average of ranked characteristics).
    # rank_transform preserves NaN for instruments with NULL chars in the
    # source panel; here we map any residual NaN to 0.0 (the midpoint of
    # the [-0.5, +0.5] ranked space, i.e. cross-sectional median) so a
    # holding with one missing char is treated as having neutral exposure
    # on that factor rather than poisoning the entire weighted average
    # with NaN. Holdings with all chars NaN still contribute zero tilt
    # but retain their pct_of_nav weight.
    matched = matched.fillna(0.0)
    weights = np.array([holdings_ids[iid] for iid in matched.index.get_level_values(0)])
    total_weight = weights.sum()
    if total_weight == 0:
        return await _run_ipca_rail_option_a(request, db, fit)

    z_fund = (matched.values * (weights / total_weight)[:, None]).sum(axis=0)

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
    """Estimate alpha as the mean residual: r_fund - beta' * f_t.

    beta is in ranked-chars space (Gamma.T @ ranked_z_fund). The equation
    still holds because factor_returns from the fit are also estimated in
    ranked-chars space — units cancel in the dot product.
    """
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
    fund_returns_df.index = pd.to_datetime(fund_returns_df.index).to_period("M")
    fund_returns_df = fund_returns_df[~fund_returns_df.index.duplicated(keep="last")]

    if fit.dates is None:
        return 0.0

    factor_df = pd.DataFrame(
        fit.factor_returns.T,
        index=pd.to_datetime(fit.dates).to_period("M"),
        columns=[f"factor_{i}" for i in range(fit.K)],
    )
    factor_df = factor_df[~factor_df.index.duplicated(keep="last")]

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
    fund_returns_df.index = pd.to_datetime(fund_returns_df.index).to_period("M")
    fund_returns_df = fund_returns_df[~fund_returns_df.index.duplicated(keep="last")]

    if fit.dates is None:
        return None

    factor_df = pd.DataFrame(
        fit.factor_returns.T,
        index=pd.to_datetime(fit.dates).to_period("M"),
        columns=[f"factor_{i}" for i in range(fit.K)],
    )
    factor_df = factor_df[~factor_df.index.duplicated(keep="last")]

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

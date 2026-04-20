"""Risk calculation worker — computes rolling risk metrics for all active funds.

Usage:
    python -m app.workers.risk_calc

Computes CVaR, VaR, returns, volatility, drawdown, and Sharpe ratio
for all active funds and stores results in fund_risk_metrics.
"""

import asyncio
import json
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import redis.asyncio as aioredis
import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.core.jobs.tracker import get_redis_pool
from app.core.tenancy.middleware import set_rls_context
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.models.macro import MacroData
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.risk import FundRiskMetrics
from quant_engine.alternatives_analytics_service import AltAnalyticsConfig, compute_alt_analytics
from quant_engine.cvar_service import compute_cvar_from_returns
from quant_engine.drift_service import DtwDriftResult, DtwDriftStatus, compute_dtw_drift_batch
from quant_engine.fixed_income_analytics_service import FIRegressionConfig, compute_fi_analytics
from quant_engine.garch_service import fit_garch
from quant_engine.return_statistics_service import (
    compute_sharpe_ratio,
    compute_sortino_ratio,
)
from quant_engine.scoring_components import robust_sharpe as _robust_sharpe_mod
from quant_engine.scoring_service import compute_fund_score
from quant_engine.talib_momentum_service import (
    compute_flow_momentum,
    compute_momentum_signals_talib,
    normalize_flow_momentum,
)

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class _FundSnapshot:
    """Scalar snapshot of an Instrument row — immune to ORM expire/rollback.

    SQLAlchemy rollback() expires ALL identity-map objects regardless of
    expire_on_commit.  If a batch upsert fails and triggers rollback,
    subsequent access to ORM attributes would attempt an async reload
    outside the greenlet context (MissingGreenlet).  By extracting scalars
    immediately after the query, the batch loop operates on plain data.
    """

    instrument_id: uuid.UUID
    ticker: str | None
    asset_class: str
    attributes: dict


RISK_CALC_LOCK_ID = 900_007
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_FALLBACK = 0.04  # Fallback ~4% if FRED DFF unavailable

MIN_STRESS_OBS = 10  # Minimum stress observations for conditional CVaR

# Minimum annualized volatility for Sharpe/Sortino to be meaningful.
# Funds below this threshold have stale or frozen NAV data (Yahoo Finance
# returns flat prices for closed/merged/liquidated funds). With near-zero
# vol, Sharpe = excess_return / epsilon diverges to ±infinity.
# 1% annualized vol threshold — below this indicates stale Yahoo Finance NAV,
# not a legitimate low-vol fund (lowest confirmed legitimate: SOUCX at 3.4%).
# Diagnosed 2026-03-30: 15 funds with flat NAV producing Sharpe = -9999.
MIN_ANNUALIZED_VOL = 0.01

# Implausible daily return threshold. Any |return_1d| above this value is
# rejected at fetch-time from all NAV series consumed by the risk worker
# (base metrics, regime-conditional CVaR, DTW drift). A 50% single-day loss
# on an unleveraged fund is physically impossible; on a 3x-leveraged product
# it requires the underlying to fall >16.7% in one session (an event that
# has occurred only a handful of times in market history — e.g. Black Monday
# 1987, COVID 2020-03-16). Any return beyond this cap is almost always a
# corporate-action / distribution / reverse-split not adjusted by the NAV
# ingestion worker, and propagating it would contaminate Sharpe, volatility,
# CVaR, drawdown, manager_score, and peer percentile rankings across the
# entire cross-section.
#
# Diagnosed 2026-04-08: 7 funds with unadjusted corporate-action ghosts
# (CHNTX, RYSHX, DSMLX, SFPIX, MRVNX, MMTLX, MMTQX) producing cvar_95_conditional
# values down to -188% and annualized vol up to 406%. Real 2x-leveraged
# single-stock ETFs (MSTZ/MSTU on MSTR) are correctly preserved because
# their legitimate extreme days (~70%) are explainable by underlying rallies
# of ~35% and are defensible against prospectus disclosures.
MAX_DAILY_RETURN_ABS = 0.5


async def get_risk_free_rate(db: AsyncSession) -> float:
    """Get latest Fed Funds Rate from macro_data, fallback to 4%.

    FRED DFF is in percent (e.g., 5.25), so divide by 100 for decimal.
    """
    stmt = (
        select(MacroData.value)
        .where(MacroData.series_id == "DFF")
        .order_by(MacroData.obs_date.desc())
        .limit(1)
    )
    result = (await db.execute(stmt)).scalar_one_or_none()
    if result is not None:
        rate = float(result) / 100  # FRED returns percent
        logger.debug("Risk-free rate from FRED DFF", rate=rate)
        return rate
    logger.info("FRED DFF unavailable, using fallback risk-free rate", rate=RISK_FREE_RATE_FALLBACK)
    return RISK_FREE_RATE_FALLBACK
WINDOW_CONFIGS = {
    "1m": 21,
    "3m": 63,
    "6m": 126,
    "12m": 252,
}


def _compute_return(returns: np.ndarray, days: int) -> float | None:
    """Compute cumulative return over last N trading days."""
    if len(returns) < days:
        return None
    window = returns[-days:]
    return float(np.prod(1 + window) - 1)


def _compute_annualized_return(returns: np.ndarray, years: int) -> float | None:
    """Compute annualized return over N years."""
    days = years * TRADING_DAYS_PER_YEAR
    if len(returns) < days:
        return None
    window = returns[-days:]
    total = float(np.prod(1 + window))
    if total <= 0:
        # Fund lost 100%+ over the period — annualization undefined
        return -1.0
    return float(total ** (1 / years) - 1)


def _compute_volatility(returns: np.ndarray, days: int) -> float | None:
    """Compute annualized volatility over last N trading days."""
    if len(returns) < days:
        return None
    window = returns[-days:]
    return float(np.std(window, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))


def _compute_max_drawdown(returns: np.ndarray, days: int) -> float | None:
    """Compute maximum drawdown over last N trading days."""
    if len(returns) < days:
        return None
    window = returns[-days:]
    cum = np.cumprod(1 + window)
    running_max = np.maximum.accumulate(cum)
    drawdowns = (cum - running_max) / running_max
    return float(np.min(drawdowns))


def _compute_sharpe(returns: np.ndarray, days: int, risk_free_rate: float = 0.04) -> float | None:
    """Window-slicing adapter around the canonical Sharpe helper.

    Preserves the historical ``(returns, days, rf)`` signature used
    throughout the worker while delegating the actual math to
    :func:`quant_engine.return_statistics_service.compute_sharpe_ratio`
    — the single source of truth shared with the screener (S4-P0).
    """
    if len(returns) < days:
        return None
    return compute_sharpe_ratio(
        returns[-days:],
        risk_free_rate=risk_free_rate,
        trading_days_per_year=TRADING_DAYS_PER_YEAR,
        min_annualized_vol=MIN_ANNUALIZED_VOL,
    )


def _compute_sortino(returns: np.ndarray, days: int, risk_free_rate: float = 0.04) -> float | None:
    """Window-slicing adapter around the canonical Sortino helper."""
    if len(returns) < days:
        return None
    return compute_sortino_ratio(
        returns[-days:],
        risk_free_rate=risk_free_rate,
        trading_days_per_year=TRADING_DAYS_PER_YEAR,
        min_annualized_vol=MIN_ANNUALIZED_VOL,
    )


async def _batch_resolve_return_types(
    db: AsyncSession,
    fund_ids: list[uuid.UUID],
    start_date: date,
    as_of_date: date,
) -> dict[str, str]:
    """Batch-fetch distinct return_type values for all fund IDs in a single query.

    Replaces per-fund calls to the former _resolve_return_type_filter, reducing
    N queries to 1. Returns a dict mapping fund_id (str) → 'log' or 'arithmetic'.

    Funds that have any 'log' rows in the window are mapped to 'log'.
    Funds with only 'arithmetic' rows are mapped to 'arithmetic' with a warning.
    Funds absent from the result (no data at all) default to 'log'.
    """
    if not fund_ids:
        return {}

    stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.return_type)
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= as_of_date,
            NavTimeseries.return_1d.is_not(None),
        )
        .distinct()
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Accumulate all return_types seen per fund
    types_by_fund: dict[str, set[str]] = {}
    for row_instrument_id, return_type in rows:
        fid = str(row_instrument_id)
        types_by_fund.setdefault(fid, set()).add(return_type)

    resolved: dict[str, str] = {}
    for fid, types_present in types_by_fund.items():
        if "log" in types_present:
            resolved[fid] = "log"
        else:
            # Only arithmetic rows found — fund has not been migrated yet
            logger.warning(
                "Fund has only arithmetic returns; log returns preferred for CVaR accuracy",
                fund_id=fid,
            )
            resolved[fid] = "arithmetic"

    return resolved


async def _batch_fetch_nav_returns(
    db: AsyncSession,
    fund_ids: list[uuid.UUID],
    return_type_by_fund: dict[str, str],
    start_date: date,
    as_of_date: date,
) -> tuple[dict[str, list[float]], dict[str, int]]:
    """Batch-fetch NAV daily returns for all fund IDs in at most 2 queries.

    Replaces the per-fund SELECT inside compute_fund_risk_metrics, reducing
    N queries to at most 2 (one per return_type group). Returns a tuple of:
    - dict mapping fund_id (str) → ordered list of float returns (ascending by nav_date)
    - dict mapping fund_id (str) → count of rejected implausible returns
    """
    if not fund_ids:
        return {}, {}

    # Partition fund_ids by their resolved return_type
    log_fund_ids = [fid for fid in fund_ids if return_type_by_fund.get(str(fid), "log") == "log"]
    arith_fund_ids = [fid for fid in fund_ids if return_type_by_fund.get(str(fid), "log") == "arithmetic"]

    raw_by_fund: dict[str, list[float]] = {}
    rejected_by_fund: dict[str, int] = {}

    for type_label, typed_ids in [("log", log_fund_ids), ("arithmetic", arith_fund_ids)]:
        if not typed_ids:
            continue

        stmt = (
            select(NavTimeseries.instrument_id, NavTimeseries.return_1d)
            .where(
                NavTimeseries.instrument_id.in_(typed_ids),
                NavTimeseries.nav_date >= start_date,
                NavTimeseries.nav_date <= as_of_date,
                NavTimeseries.return_1d.is_not(None),
                NavTimeseries.return_type == type_label,
            )
            .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
        )
        result = await db.execute(stmt)
        for row_instrument_id, return_1d in result.all():
            fid = str(row_instrument_id)
            r = float(return_1d)
            if abs(r) > MAX_DAILY_RETURN_ABS:
                rejected_by_fund[fid] = rejected_by_fund.get(fid, 0) + 1
                continue
            raw_by_fund.setdefault(fid, []).append(r)

    if rejected_by_fund:
        logger.warning(
            "nav_returns_rejected_implausible_daily",
            affected_funds=len(rejected_by_fund),
            total_rejected_obs=sum(rejected_by_fund.values()),
            threshold=MAX_DAILY_RETURN_ABS,
            sample_fund_ids=list(rejected_by_fund.keys())[:5],
        )

    return raw_by_fund, rejected_by_fund


async def _fetch_stress_dates(
    db: AsyncSession,
    start_date: date,
    as_of_date: date,
) -> frozenset[date]:
    """Fetch dates classified as RISK_OFF or CRISIS from macro_regime_history.

    regime_fit worker persists the full HMM-classified regime series daily.
    If macro_regime_history is empty (first run before regime_fit executes),
    returns empty frozenset — caller handles this via MIN_STRESS_OBS guard.

    macro_regime_history is a global table — no org_id, no RLS.
    """
    result = await db.execute(
        text("""
            SELECT regime_date
            FROM macro_regime_history
            WHERE regime_date >= :start_date
              AND regime_date <= :as_of_date
              AND classified_regime IN ('RISK_OFF', 'CRISIS')
            ORDER BY regime_date
        """),
        {"start_date": start_date, "as_of_date": as_of_date},
    )
    return frozenset(row[0] for row in result.all())


async def _batch_fetch_dated_returns(
    db: AsyncSession,
    fund_ids: list[uuid.UUID],
    return_type_by_fund: dict[str, str],
    start_date: date,
    as_of_date: date,
) -> dict[str, list[tuple[date, float]]]:
    """Batch-fetch NAV returns with dates for regime-conditional CVaR.

    Same logic as _batch_fetch_nav_returns but includes nav_date in output
    for alignment with VIX stress dates.
    """
    if not fund_ids:
        return {}

    log_fund_ids = [fid for fid in fund_ids if return_type_by_fund.get(str(fid), "log") == "log"]
    arith_fund_ids = [fid for fid in fund_ids if return_type_by_fund.get(str(fid), "log") == "arithmetic"]

    raw_by_fund: dict[str, list[tuple[date, float]]] = {}
    rejected_by_fund: dict[str, int] = {}

    for type_label, typed_ids in [("log", log_fund_ids), ("arithmetic", arith_fund_ids)]:
        if not typed_ids:
            continue

        stmt = (
            select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
            .where(
                NavTimeseries.instrument_id.in_(typed_ids),
                NavTimeseries.nav_date >= start_date,
                NavTimeseries.nav_date <= as_of_date,
                NavTimeseries.return_1d.is_not(None),
                NavTimeseries.return_type == type_label,
            )
            .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
        )
        result = await db.execute(stmt)
        for row_instrument_id, nav_date, return_1d in result.all():
            fid = str(row_instrument_id)
            r = float(return_1d)
            if abs(r) > MAX_DAILY_RETURN_ABS:
                rejected_by_fund[fid] = rejected_by_fund.get(fid, 0) + 1
                continue
            raw_by_fund.setdefault(fid, []).append((nav_date, r))

    if rejected_by_fund:
        logger.warning(
            "dated_nav_returns_rejected_implausible_daily",
            affected_funds=len(rejected_by_fund),
            total_rejected_obs=sum(rejected_by_fund.values()),
            threshold=MAX_DAILY_RETURN_ABS,
            sample_fund_ids=list(rejected_by_fund.keys())[:5],
        )

    return raw_by_fund


async def _batch_fetch_macro_yield_changes(
    db: AsyncSession,
    start_date: date,
    as_of_date: date,
) -> dict[str, list[tuple[date, float]]]:
    """Fetch daily changes in Treasury yields and credit spreads from macro_data.

    Returns dict mapping series_id -> list of (obs_date, daily_change).
    Series: DGS10 (duration regression), BAA10Y (credit beta regression).

    FRED yields are in percent (e.g. 4.25). We convert to decimal changes
    (0.0425) before returning for regression use.
    """
    series_ids = ["DGS10", "BAA10Y"]

    stmt = (
        select(MacroData.series_id, MacroData.obs_date, MacroData.value)
        .where(
            MacroData.series_id.in_(series_ids),
            MacroData.obs_date >= start_date,
            MacroData.obs_date <= as_of_date,
            MacroData.value.is_not(None),
        )
        .order_by(MacroData.series_id, MacroData.obs_date)
    )
    result = await db.execute(stmt)

    # Group raw levels by series
    raw_by_series: dict[str, list[tuple[date, float]]] = {}
    for sid, obs_date, value in result.all():
        raw_by_series.setdefault(sid, []).append((obs_date, float(value)))

    # Compute daily changes: delta_Y(t) = Y(t) - Y(t-1)
    # Convert from percent to decimal (4.25 -> 0.0425) then diff
    changes_by_series: dict[str, list[tuple[date, float]]] = {}
    for sid, observations in raw_by_series.items():
        changes: list[tuple[date, float]] = []
        for i in range(1, len(observations)):
            prev_date, prev_val = observations[i - 1]
            curr_date, curr_val = observations[i]
            # Forward-fill gap guard: skip if gap > 5 business days
            if (curr_date - prev_date).days > 7:
                continue
            # Convert percent to decimal change
            delta = (curr_val - prev_val) / 100.0
            changes.append((curr_date, delta))
        changes_by_series[sid] = changes

    for sid in series_ids:
        count = len(changes_by_series.get(sid, []))
        logger.info("macro_yield_changes_fetched", series_id=sid, n_changes=count)

    return changes_by_series


async def _batch_fetch_nav_prices(
    db: AsyncSession,
    fund_ids: list[uuid.UUID],
    as_of_date: date,
    lookback_days: int = 80,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Batch-fetch latest NAV prices and AUM for momentum computation.

    Returns dict mapping fund_id (str) -> (nav_prices, aum_values) as numpy arrays.
    Each array is trimmed to the last 50 observations (enough for RSI(14) + BBANDS(20)).
    """
    start_date = as_of_date - timedelta(days=lookback_days)
    stmt = (
        select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav,
            NavTimeseries.aum_usd,
        )
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= as_of_date,
            NavTimeseries.nav.is_not(None),
        )
        .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
    )
    result = await db.execute(stmt)

    by_fund: dict[str, tuple[list[float], list[float]]] = {}
    for row_id, nav, aum in result.all():
        fid = str(row_id)
        if fid not in by_fund:
            by_fund[fid] = ([], [])
        by_fund[fid][0].append(float(nav))
        by_fund[fid][1].append(float(aum) if aum is not None else 0.0)

    return {
        fid: (np.array(navs[-50:]), np.array(aums[-50:]))
        for fid, (navs, aums) in by_fund.items()
    }


def _compute_momentum_from_nav(
    close: np.ndarray,
    aum: np.ndarray,
) -> dict[str, float | None]:
    """Compute momentum signals from pre-fetched NAV prices and AUM.

    Pure computation — no DB access.
    """
    if len(close) < 30:
        return {
            "rsi_14": None,
            "bb_position": None,
            "nav_momentum_score": None,
            "flow_momentum_score": None,
            "blended_momentum_score": None,
        }

    signals = compute_momentum_signals_talib(close)
    nav_score = signals.get("momentum_score") or None

    rsi_val = signals.get("rsi_norm")
    bb_val = signals.get("bb_pos")

    result: dict[str, float | None] = {
        "rsi_14": round(rsi_val * 100, 2) if rsi_val is not None else None,
        "bb_position": round(bb_val * 100, 2) if bb_val is not None else None,
        "nav_momentum_score": round(nav_score, 2) if nav_score is not None else None,
    }

    if aum.any():
        # Low-pass filter: 63-day EMA (~3 months) dampens noise from
        # dividends, splits, merges, and performance fee payouts that
        # distort the AUM-minus-NAV flow proxy.
        aum_smooth = _ema_smooth(aum, span=63) if len(aum) >= 63 else aum
        slope = compute_flow_momentum(close, aum_smooth)
        flow_score = normalize_flow_momentum(slope)
        result["flow_momentum_score"] = round(flow_score, 2)
        if nav_score is not None:
            result["blended_momentum_score"] = round(0.5 * nav_score + 0.5 * flow_score, 2)
        else:
            result["blended_momentum_score"] = round(flow_score, 2)
    else:
        result["flow_momentum_score"] = None
        result["blended_momentum_score"] = round(nav_score, 2) if nav_score is not None else None

    return result


def _compute_metrics_from_returns(
    fund: "Instrument | _FundSnapshot",
    returns_raw: list[float],
    as_of_date: date,
    risk_free_rate: float = 0.04,
    rejected_count: int = 0,
) -> dict | None:
    """Compute all risk metrics for a single fund from pre-fetched returns.

    Pure computation — no DB access. The caller supplies the pre-fetched,
    return-type-filtered return series. This is the inner loop body for
    run_risk_calc after the batch-fetch refactor.
    """
    if len(returns_raw) < 21:  # Need at least 1 month of data
        logger.info("Insufficient data for risk calc", fund_id=str(fund.instrument_id), points=len(returns_raw))
        return None

    returns = np.array(returns_raw)
    metrics: dict = {"instrument_id": fund.instrument_id, "calc_date": as_of_date}

    # CVaR and VaR for each window
    for label, days in WINDOW_CONFIGS.items():
        if len(returns) >= days:
            window = returns[-days:]
            cvar, var = compute_cvar_from_returns(window, confidence=0.95)
            metrics[f"cvar_95_{label}"] = round(cvar, 6)
            metrics[f"var_95_{label}"] = round(var, 6)

    # Returns
    metrics["return_1m"] = _round_or_none(_compute_return(returns, 21))
    metrics["return_3m"] = _round_or_none(_compute_return(returns, 63))
    metrics["return_6m"] = _round_or_none(_compute_return(returns, 126))
    metrics["return_1y"] = _round_or_none(_compute_return(returns, 252))
    metrics["return_3y_ann"] = _round_or_none(_compute_annualized_return(returns, 3))
    metrics["return_5y_ann"] = _round_or_none(_compute_annualized_return(returns, 5))
    metrics["return_10y_ann"] = _round_or_none(_compute_annualized_return(returns, 10))

    # Volatility
    metrics["volatility_1y"] = _round_or_none(_compute_volatility(returns, 252))

    # Drawdown
    metrics["max_drawdown_1y"] = _round_or_none(_compute_max_drawdown(returns, 252))
    metrics["max_drawdown_3y"] = _round_or_none(_compute_max_drawdown(returns, 3 * 252))

    # Sharpe & Sortino (using live risk-free rate from FRED DFF)
    metrics["sharpe_1y"] = _round_or_none(_compute_sharpe(returns, 252, risk_free_rate))
    metrics["sharpe_3y"] = _round_or_none(_compute_sharpe(returns, 3 * 252, risk_free_rate))
    metrics["sortino_1y"] = _round_or_none(_compute_sortino(returns, 252, risk_free_rate))

    # Robust Sharpe (Cornish-Fisher adjusted + Opdyke 95% CI). Populated
    # ALWAYS per PR-Q1 — read by scoring_service only when flag is ON.
    # Uses daily returns over the 3y window when available, else the full
    # series, with periods_per_year=252 to match the daily sharpe_1y scale.
    cf_window = returns[-(3 * 252):] if len(returns) >= 3 * 252 else returns
    cf_result = _robust_sharpe_mod.robust_sharpe(
        cf_window,
        rf_rate=risk_free_rate / 252.0,
        periods_per_year=252,
    )
    metrics["sharpe_cf"] = _round_or_none(cf_result.sharpe_cornish_fisher)
    metrics["sharpe_cf_skew"] = _round_or_none(cf_result.skewness)
    metrics["sharpe_cf_kurt"] = _round_or_none(cf_result.excess_kurtosis)
    metrics["sharpe_cf_ci_lower"] = _round_or_none(cf_result.ci_lower_95)
    metrics["sharpe_cf_ci_upper"] = _round_or_none(cf_result.ci_upper_95)

    # GARCH(1,1) conditional volatility (BL-11)
    # Fallback: EWMA(λ=0.94) preserves volatility clustering without
    # iterative convergence. Avoids mixing conditional (GARCH) with
    # static (σ_1y) methodologies across the dashboard.
    garch_result = fit_garch(returns)
    if garch_result is not None and garch_result.converged and garch_result.volatility_garch is not None:
        metrics["volatility_garch"] = round(garch_result.volatility_garch, 6)
        metrics["vol_model"] = garch_result.vol_model
    else:
        ewma_vol = _ewma_volatility(returns, lam=0.94)
        metrics["volatility_garch"] = ewma_vol
        metrics["vol_model"] = "EWMA_0.94" if ewma_vol is not None else None

    if rejected_count > 0:
        metrics["data_quality_flags"] = {"return_rejected_count": rejected_count}
    else:
        metrics["data_quality_flags"] = {}

    # EVT Extreme Risk (PR-Q6)
    # Uses full history (up to 10y) for stable GPD fit of the loss tail.
    # Surfaces cvar_99_evt, cvar_999_evt, and evt_xi_shape.
    from quant_engine.evt.pot_gpd import extreme_var_evt

    evt_res = extreme_var_evt(returns, quantiles=(0.99, 0.999))
    metrics["cvar_99_evt"] = _round_or_none(evt_res.cvar_99)
    metrics["cvar_999_evt"] = _round_or_none(evt_res.cvar_999)
    metrics["evt_xi_shape"] = _round_or_none(evt_res.fit.xi)

    return metrics


async def compute_fund_risk_metrics(
    db: AsyncSession,
    fund: Instrument,
    as_of_date: date | None = None,
    risk_free_rate: float = 0.04,
) -> dict | None:
    """Compute all risk metrics for a single fund.

    Compatibility shim used outside run_risk_calc (e.g. on-demand recalc for
    a single fund). For bulk processing use the batch path in run_risk_calc.
    """
    if as_of_date is None:
        as_of_date = date.today()

    start_date = as_of_date - timedelta(days=3 * 365 + 30)

    return_type_map = await _batch_resolve_return_types(db, [fund.instrument_id], start_date, as_of_date)
    nav_map, rejected_map = await _batch_fetch_nav_returns(db, [fund.instrument_id], return_type_map, start_date, as_of_date)
    raw = nav_map.get(str(fund.instrument_id), [])
    rejected = rejected_map.get(str(fund.instrument_id), 0)
    return _compute_metrics_from_returns(fund, raw, as_of_date, risk_free_rate, rejected_count=rejected)


_NUMERIC_10_6_MAX = 9999.999999  # Numeric(10,6) max absolute value


def _ema_smooth(series: np.ndarray, span: int = 63) -> np.ndarray:
    """Exponential Moving Average low-pass filter.

    Dampens high-frequency noise (dividends, splits, merges) in AUM series
    before computing flow momentum. span=63 ≈ 3-month rolling window.
    """
    alpha = 2.0 / (span + 1)
    result = np.empty_like(series, dtype=float)
    result[0] = series[0]
    for i in range(1, len(series)):
        result[i] = alpha * series[i] + (1 - alpha) * result[i - 1]
    return result


def _ewma_volatility(returns: np.ndarray, lam: float = 0.94) -> float | None:
    """EWMA (RiskMetrics) conditional volatility.

    σ²_t = λ·σ²_{t-1} + (1-λ)·r²_{t-1}

    Preserves volatility clustering like GARCH but without iterative MLE.
    Used as fallback when GARCH(1,1) fails to converge.
    λ=0.94 is the J.P. Morgan RiskMetrics standard for daily data.

    Returns annualized volatility (×√252) or None if insufficient data.
    """
    if len(returns) < 20:
        return None

    variance = float(np.var(returns))  # seed with unconditional variance
    for r in returns:
        variance = lam * variance + (1 - lam) * (r ** 2)

    ewma_vol = float(np.sqrt(variance) * np.sqrt(252))
    return round(ewma_vol, 6)


def _round_or_none(value: float | None, decimals: int = 6) -> float | None:
    if value is None:
        return None
    if not np.isfinite(value):
        return None
    clamped = max(-_NUMERIC_10_6_MAX, min(_NUMERIC_10_6_MAX, value))
    return round(clamped, decimals)


async def _fetch_block_returns_batch(
    db: AsyncSession,
    fund_ids: list["uuid.UUID"],
    as_of_date: date,
    window_days: int = 63,
) -> dict[str, np.ndarray]:
    """Batch-fetch returns for all given fund IDs in a single query.

    Fetches both return_type and return_1d so each fund's series uses only
    rows of a single return type. Log returns are preferred; if a fund has no
    log-type rows, its arithmetic rows are used with a warning logged. This
    prevents silent mixing of log and arithmetic returns within any fund's
    series, which would corrupt DTW drift calculations.

    Returns a dict mapping fund_id (str) → numpy array of the last `window_days`
    daily returns ordered by nav_date ascending. Funds with no data are omitted.
    """
    if not fund_ids:
        return {}

    start_date = as_of_date - timedelta(days=window_days * 2)  # extra buffer for weekends
    stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.return_1d, NavTimeseries.return_type)
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= as_of_date,
            NavTimeseries.return_1d.is_not(None),
        )
        .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
    )
    result = await db.execute(stmt)
    rows = result.all()

    # Group rows by fund_id; track which return types are present per fund.
    # Reject any |return_1d| > MAX_DAILY_RETURN_ABS (see constant docstring).
    raw_by_fund: dict[str, dict[str, list[float]]] = {}
    rejected_by_fund: dict[str, int] = {}
    for row_instrument_id, return_1d, return_type in rows:
        fid = str(row_instrument_id)
        r = float(return_1d)
        if abs(r) > MAX_DAILY_RETURN_ABS:
            rejected_by_fund[fid] = rejected_by_fund.get(fid, 0) + 1
            continue
        if fid not in raw_by_fund:
            raw_by_fund[fid] = {"log": [], "arithmetic": []}
        rtype = return_type if return_type in ("log", "arithmetic") else "arithmetic"
        raw_by_fund[fid][rtype].append(r)

    if rejected_by_fund:
        logger.warning(
            "block_returns_rejected_implausible_daily",
            affected_funds=len(rejected_by_fund),
            total_rejected_obs=sum(rejected_by_fund.values()),
            threshold=MAX_DAILY_RETURN_ABS,
            sample_fund_ids=list(rejected_by_fund.keys())[:5],
        )

    # Select the preferred return type per fund (log > arithmetic)
    filtered: dict[str, list[float]] = {}
    for fid, type_buckets in raw_by_fund.items():
        if type_buckets["log"]:
            filtered[fid] = type_buckets["log"]
        else:
            logger.warning(
                "Fund has only arithmetic returns in batch fetch; log returns preferred",
                fund_id=fid,
            )
            filtered[fid] = type_buckets["arithmetic"]

    # Trim each fund's series to the last `window_days` points
    return {fid: np.array(vals[-window_days:], dtype=float) for fid, vals in filtered.items()}


async def _compute_block_dtw_scores(
    db: AsyncSession,
    funds_with_metrics: list[tuple["Instrument", dict]],
    as_of_date: date,
    dtw_window: int = 63,
    block_id_map: dict[str, str | None] | None = None,
) -> dict[str, DtwDriftResult]:
    """Compute DTW drift scores for all funds, grouped by block.

    Each fund is compared against the equal-weight average of all fund returns
    in the same block. If a block has fewer than 2 funds, returns a degraded result.

    block_id_map: maps instrument_id (str) → block_id from instruments_org.

    Returns a dict mapping fund_id (str) → DtwDriftResult.
    """
    if block_id_map is None:
        block_id_map = {}

    # Group funds by block_id (looked up from instruments_org via block_id_map)
    block_funds: dict[str | None, list[tuple[Instrument, dict]]] = defaultdict(list)
    for fund, metrics in funds_with_metrics:
        bid = block_id_map.get(str(fund.instrument_id))
        block_funds[bid].append((fund, metrics))

    dtw_scores: dict[str, DtwDriftResult] = {}

    for block_id, block_fund_list in block_funds.items():
        if len(block_fund_list) < 2:
            # Can't compute meaningful drift vs self — degraded, not fake zero
            for fund, _ in block_fund_list:
                dtw_scores[str(fund.instrument_id)] = DtwDriftResult(
                    score=None,
                    status=DtwDriftStatus.degraded,
                    reason="single fund in block — no peer comparison possible",
                )
            continue

        # Batch-fetch returns for all funds in this block — single query, no N+1
        block_fund_ids = [fund.instrument_id for fund, _ in block_fund_list]
        returns_by_fund = await _fetch_block_returns_batch(
            db, block_fund_ids, as_of_date, window_days=dtw_window,
        )

        fund_return_arrays: list[np.ndarray] = []
        fund_ids: list[str] = []
        for fund, _ in block_fund_list:
            fid = str(fund.instrument_id)
            arr = returns_by_fund.get(fid, np.array([], dtype=float))
            fund_return_arrays.append(arr)
            fund_ids.append(fid)

        # Pad/truncate arrays to same length (use min length)
        min_len = min(len(a) for a in fund_return_arrays)
        if min_len < 10:
            # Insufficient data for DTW
            for fid in fund_ids:
                dtw_scores[fid] = DtwDriftResult(
                    score=None,
                    status=DtwDriftStatus.degraded,
                    reason=f"insufficient data for DTW: {min_len} points (min 10)",
                )
            continue

        # Build returns matrix (n_funds × min_len)
        matrix = np.vstack([a[-min_len:] for a in fund_return_arrays])

        # Block benchmark = equal-weight average of all funds in block
        benchmark = matrix.mean(axis=0)

        # Batch DTW computation
        results = compute_dtw_drift_batch(matrix, benchmark, window=min_len)
        for fid, result in zip(fund_ids, results, strict=False):
            dtw_scores[fid] = result

        logger.debug(
            "DTW drift computed for block",
            block_id=block_id,
            n_funds=len(fund_ids),
            window=min_len,
        )

    return dtw_scores


DTW_SUB_BATCH_SIZE = 200
DTW_LARGE_GROUP_THRESHOLD = 500


async def _compute_global_dtw_scores(
    db: AsyncSession,
    computed: "list[tuple[Instrument | _FundSnapshot, dict]]",
    as_of_date: date,
    strategy_map: dict[str, str | None],
    dtw_window: int = 252,
) -> dict[str, DtwDriftResult]:
    """Compute DTW drift scores grouped by strategy_label (global).

    Instead of allocation blocks (org-scoped), groups funds by their
    strategy_label from mv_unified_funds. Each strategy group uses its
    equal-weight average as the benchmark.

    Funds with no strategy_label are grouped under "__unclassified__".
    Groups with < 2 funds get degraded status (no peer comparison possible).
    Groups with > 500 funds are split into sub-batches of 200, using the
    full group mean as benchmark for all sub-batches.
    """
    # Group funds by strategy_label
    strategy_funds: dict[str, list[tuple[_FundSnapshot, dict]]] = defaultdict(list)
    for fund, metrics in computed:
        fid_str = str(fund.instrument_id)
        strategy = strategy_map.get(fid_str) or "__unclassified__"
        strategy_funds[strategy].append((fund, metrics))

    dtw_scores: dict[str, DtwDriftResult] = {}

    for strategy, group in strategy_funds.items():
        if len(group) < 2:
            for fund, _ in group:
                dtw_scores[str(fund.instrument_id)] = DtwDriftResult(
                    score=None,
                    status=DtwDriftStatus.degraded,
                    reason=f"single fund in strategy '{strategy}' — no peer comparison possible",
                )
            continue

        # Batch-fetch returns for all funds in this strategy group
        group_fund_ids = [fund.instrument_id for fund, _ in group]
        returns_by_fund = await _fetch_block_returns_batch(
            db, group_fund_ids, as_of_date, window_days=dtw_window,
        )

        # Build arrays for all funds with data
        fund_return_arrays: list[np.ndarray] = []
        fund_ids: list[str] = []
        for fund, _ in group:
            fid = str(fund.instrument_id)
            arr = returns_by_fund.get(fid, np.array([], dtype=float))
            if len(arr) >= 10:
                fund_return_arrays.append(arr)
                fund_ids.append(fid)
            else:
                dtw_scores[fid] = DtwDriftResult(
                    score=None,
                    status=DtwDriftStatus.degraded,
                    reason=f"insufficient data for DTW: {len(arr)} points (min 10)",
                )

        if len(fund_ids) < 2:
            for fid in fund_ids:
                dtw_scores[fid] = DtwDriftResult(
                    score=None,
                    status=DtwDriftStatus.degraded,
                    reason=f"< 2 funds with data in strategy '{strategy}'",
                )
            continue

        # Align to common length
        min_len = min(len(a) for a in fund_return_arrays)
        if min_len < 10:
            for fid in fund_ids:
                dtw_scores[fid] = DtwDriftResult(
                    score=None,
                    status=DtwDriftStatus.degraded,
                    reason=f"insufficient common window: {min_len} points",
                )
            continue

        matrix = np.vstack([a[-min_len:] for a in fund_return_arrays])
        benchmark = matrix.mean(axis=0)

        if len(fund_ids) > DTW_LARGE_GROUP_THRESHOLD:
            # Sub-batch processing for large groups
            for sb_start in range(0, len(fund_ids), DTW_SUB_BATCH_SIZE):
                sb_ids = fund_ids[sb_start:sb_start + DTW_SUB_BATCH_SIZE]
                sb_matrix = matrix[sb_start:sb_start + DTW_SUB_BATCH_SIZE]
                results = compute_dtw_drift_batch(sb_matrix, benchmark, window=min_len)
                for fid, result in zip(sb_ids, results, strict=False):
                    dtw_scores[fid] = result
        else:
            results = compute_dtw_drift_batch(matrix, benchmark, window=min_len)
            for fid, result in zip(fund_ids, results, strict=False):
                dtw_scores[fid] = result

        logger.debug(
            "DTW drift computed for strategy",
            strategy=strategy,
            n_funds=len(fund_ids),
            window=min_len,
        )

    return dtw_scores


async def _write_risk_cache(
    org_id: "uuid.UUID",
    eval_date: date,
    computed: list[tuple["Instrument", dict]],
) -> None:
    """Write risk/scoring cache to Redis for fast dashboard reads."""
    try:
        r = aioredis.Redis(connection_pool=get_redis_pool())
        try:
            pipe = r.pipeline()

            # Cache 1: correlation refresh marker
            correlation_key = f"correlation:{org_id!s}:{eval_date.isoformat()}"
            correlation_value = json.dumps({
                "status": "refreshed",
                "funds_computed": len(computed),
                "calc_date": eval_date.isoformat(),
            })
            pipe.set(correlation_key, correlation_value, ex=86400)

            # Cache 2: scoring leaderboard (top 50 by sharpe_1y)
            leaderboard = []
            for fund, metrics in computed:
                leaderboard.append({
                    "fund_id": str(fund.instrument_id),
                    "ticker": fund.ticker,
                    "sharpe_1y": metrics.get("sharpe_1y"),
                    "return_1y": metrics.get("return_1y"),
                    "volatility_1y": metrics.get("volatility_1y"),
                    "blended_momentum_score": metrics.get("blended_momentum_score"),
                })
            leaderboard.sort(
                key=lambda x: (x["sharpe_1y"] is not None, x["sharpe_1y"] or 0),
                reverse=True,
            )
            leaderboard_key = f"scoring:leaderboard:{org_id!s}"
            pipe.set(leaderboard_key, json.dumps(leaderboard[:50]), ex=86400)

            await pipe.execute()
            logger.info(
                "Risk cache written",
                org_id=str(org_id),
                leaderboard_size=min(len(leaderboard), 50),
            )
        finally:
            await r.aclose()
    except Exception:
        logger.warning("Failed to write risk cache to Redis — continuing without cache")


async def _fetch_latest_macro_value(
    db: AsyncSession, series_id: str, as_of_date: date,
) -> float | None:
    """Fetch the latest value for a macro_data series on or before as_of_date."""
    result = await db.execute(
        text("""
            SELECT value FROM macro_data
            WHERE series_id = :series_id AND obs_date <= :as_of
            ORDER BY obs_date DESC
            LIMIT 1
        """),
        {"series_id": series_id, "as_of": as_of_date},
    )
    row = result.scalar_one_or_none()
    return float(row) if row is not None else None


async def _batch_fetch_mmf_data(
    db: AsyncSession,
    computed: list[tuple],
    cash_fund_ids: set[str],
) -> dict[str, dict]:
    """Batch fetch MMF metadata (WAM, liquidity, NAV) from sec_money_market_funds.

    Links instruments_universe → sec_money_market_funds via attributes->>'series_id'.
    Returns {instrument_id_str: {column_name: value}}.
    """
    # Collect series_id → instrument_id mapping for cash funds
    series_to_fund: dict[str, str] = {}
    for fund, _ in computed:
        fid = str(fund.instrument_id)
        if fid in cash_fund_ids:
            sid = (fund.attributes or {}).get("series_id")
            if sid:
                series_to_fund[sid] = fid

    if not series_to_fund:
        return {}

    series_ids = list(series_to_fund.keys())
    result = await db.execute(
        text("""
            SELECT series_id, weighted_avg_maturity, pct_weekly_liquid_latest,
                   stable_nav_price, seeks_stable_nav, net_assets
            FROM sec_money_market_funds
            WHERE series_id = ANY(:series_ids)
        """),
        {"series_ids": series_ids},
    )
    rows = result.mappings().all()

    out: dict[str, dict] = {}
    for row in rows:
        fid = series_to_fund.get(row["series_id"])
        if fid:
            out[fid] = {
                "weighted_avg_maturity": row["weighted_avg_maturity"],
                "pct_weekly_liquid_latest": float(row["pct_weekly_liquid_latest"]) if row["pct_weekly_liquid_latest"] is not None else None,
                "stable_nav_price": float(row["stable_nav_price"]) if row["stable_nav_price"] is not None else None,
                "seeks_stable_nav": row["seeks_stable_nav"],
                "net_assets": float(row["net_assets"]) if row["net_assets"] is not None else None,
            }
    return out


async def _batch_fetch_mmf_yields(
    db: AsyncSession,
    computed: list[tuple],
    cash_fund_ids: set[str],
) -> dict[str, dict]:
    """Batch fetch latest 7-day net yield from sec_mmf_metrics.

    Links via series_id (same as _batch_fetch_mmf_data). Uses the most
    recent metric_date for each series_id.
    Returns {instrument_id_str: {"seven_day_net_yield": float | None}}.
    """
    series_to_fund: dict[str, str] = {}
    for fund, _ in computed:
        fid = str(fund.instrument_id)
        if fid in cash_fund_ids:
            sid = (fund.attributes or {}).get("series_id")
            if sid:
                series_to_fund[sid] = fid

    if not series_to_fund:
        return {}

    series_ids = list(series_to_fund.keys())
    result = await db.execute(
        text("""
            SELECT DISTINCT ON (series_id)
                series_id, seven_day_net_yield
            FROM sec_mmf_metrics
            WHERE series_id = ANY(:series_ids)
            ORDER BY series_id, metric_date DESC
        """),
        {"series_ids": series_ids},
    )
    rows = result.mappings().all()

    out: dict[str, dict] = {}
    for row in rows:
        fid = series_to_fund.get(row["series_id"])
        if fid:
            out[fid] = {
                "seven_day_net_yield": float(row["seven_day_net_yield"]) if row["seven_day_net_yield"] is not None else None,
            }
    return out


async def _fetch_benchmark_dated_returns(
    db: AsyncSession,
    block_id: str,
    start_date: date,
    as_of_date: date,
) -> list[tuple[date, float]]:
    """Fetch daily returns for a benchmark (e.g. SPY via na_equity_large).

    Returns list of (nav_date, return_1d) tuples from benchmark_nav.
    """
    result = await db.execute(
        text("""
            SELECT nav_date, return_1d FROM benchmark_nav
            WHERE block_id = :block_id
              AND nav_date >= :start_date AND nav_date <= :as_of
              AND return_1d IS NOT NULL
            ORDER BY nav_date
        """),
        {"block_id": block_id, "start_date": start_date, "as_of": as_of_date},
    )
    return [(row[0], float(row[1])) for row in result.all()]


async def _fetch_monthly_cpi_changes(
    db: AsyncSession,
    start_date: date,
    as_of_date: date,
) -> list[tuple[date, float]]:
    """Fetch monthly CPI changes from macro_data (CPIAUCSL).

    CPI is an index level (e.g. 310.5). We compute month-over-month
    percentage change: delta = (CPI_t - CPI_{t-1}) / CPI_{t-1}.
    Returns list of (obs_date, pct_change) tuples.
    """
    result = await db.execute(
        text("""
            SELECT obs_date, value FROM macro_data
            WHERE series_id = 'CPIAUCSL'
              AND obs_date >= :start_date AND obs_date <= :as_of
              AND value IS NOT NULL
            ORDER BY obs_date
        """),
        {"start_date": start_date, "as_of": as_of_date},
    )
    raw = [(row[0], float(row[1])) for row in result.all()]
    if len(raw) < 2:
        return []
    changes: list[tuple[date, float]] = []
    for i in range(1, len(raw)):
        prev_val = raw[i - 1][1]
        if prev_val > 0:
            delta = (raw[i][1] - prev_val) / prev_val
            changes.append((raw[i][0], delta))
    return changes


# ── Alternatives profile resolution ──────────────────────────────
_BLOCK_TO_ALT_PROFILE: dict[str, str] = {
    "alt_real_estate": "reit",
    "alt_commodities": "commodity",
    "alt_gold": "gold",
    "alt_hedge_fund": "hedge",
    "alt_managed_futures": "cta",
}


def _resolve_alt_profile(block_id: str | None) -> str:
    """Resolve alt profile from block_id. Used in org-scoped worker."""
    if not block_id:
        return "generic_alt"
    return _BLOCK_TO_ALT_PROFILE.get(block_id, "generic_alt")


def _resolve_alt_profile_from_strategy(strategy_label: str | None) -> str:
    """Resolve alt profile from strategy_label via block_mapping.

    Used in GLOBAL worker where block_id is NOT available.
    """
    if not strategy_label:
        return "generic_alt"
    from vertical_engines.wealth.model_portfolio.block_mapping import blocks_for_strategy_label
    blocks = blocks_for_strategy_label(strategy_label)
    for b in blocks:
        if b in _BLOCK_TO_ALT_PROFILE:
            return _BLOCK_TO_ALT_PROFILE[b]
    return "generic_alt"


class _MetricsAdapter:
    """Adapter to expose a metrics dict as the RiskMetrics protocol for scoring."""

    def __init__(self, m: dict):
        self._m = m

    def __getattr__(self, name: str):
        return self._m.get(name)


def _score_metrics(
    metrics: dict,
    scoring_config: dict | None = None,
    expense_ratio_pct: float | None = None,
    asset_class: str = "equity",
    block_id: str | None = None,
    strategy_label: str | None = None,
) -> None:
    """Compute manager_score and score_components from base metrics in-place."""
    adapter = _MetricsAdapter(metrics)
    flows = float(metrics.get("blended_momentum_score") or 50.0)

    fi_adapter = _MetricsAdapter(metrics) if asset_class == "fixed_income" else None

    # Only dispatch to cash scoring if the fund has actual MMF data.
    # Cash-classified funds without sec_money_market_funds data (ultra-short
    # ETFs, cash management MFs) have all 5 MMF metrics as NULL, which
    # penalty-defaults every component to ~40.  Fall back to equity scoring
    # for these — they have valid NAV-based metrics (Sharpe, drawdown, etc.).
    _has_mmf_data = asset_class == "cash" and any(
        metrics.get(k) is not None
        for k in ("seven_day_net_yield", "nav_per_share_mmf", "pct_weekly_liquid")
    )
    cash_adapter = _MetricsAdapter(metrics) if _has_mmf_data else None

    alt_adapter = _MetricsAdapter(metrics) if asset_class == "alternatives" else None

    # Resolve alt profile: org worker uses block_id, global uses strategy_label
    alt_profile: str | None = None
    if asset_class == "alternatives":
        if block_id:
            alt_profile = _resolve_alt_profile(block_id)
        else:
            alt_profile = _resolve_alt_profile_from_strategy(strategy_label)

    score_val, components = compute_fund_score(
        adapter,
        flows_momentum_score=flows,
        config=scoring_config,
        expense_ratio_pct=expense_ratio_pct,
        asset_class=asset_class,
        fi_metrics=fi_adapter,
        cash_metrics=cash_adapter,
        alt_metrics=alt_adapter,
        alt_profile=alt_profile,
    )
    metrics["manager_score"] = round(score_val, 2)
    # Store alt_profile in score_components for frontend rendering
    if alt_profile:
        components["_alt_profile"] = alt_profile
    metrics["score_components"] = components


REGIME_DETECTION_LOCK_ID = 900_130


async def run_global_regime_detection(eval_date: date | None = None) -> None:
    """Compute global regime and persist to macro_regime_snapshot.

    Called AFTER macro_ingestion, BEFORE risk_calc.
    Uses advisory lock 900_130 (convention: 900_XXX where XXX = migration number).
    """
    from app.domains.wealth.models.allocation import MacroRegimeSnapshot
    from quant_engine.regime_service import build_regime_inputs, classify_regime_multi_signal
    from quant_engine.taa_band_service import extract_stress_score

    target_date = eval_date or date.today()

    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({REGIME_DETECTION_LOCK_ID})"),
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("regime_detection_skipped", reason="another instance running")
            return

        try:
            inputs = await build_regime_inputs(db, as_of_date=target_date)
            regime, reasons, structured_signals = classify_regime_multi_signal(**inputs)
            stress_score = extract_stress_score(reasons)
            logger.info(
                "global_regime_classified",
                regime=regime,
                stress_score=stress_score,
                as_of_date=str(target_date),
            )

            upsert_stmt = pg_insert(MacroRegimeSnapshot).values(
                as_of_date=target_date,
                raw_regime=regime,
                stress_score=stress_score,
                signal_details=reasons,
                signal_breakdown=structured_signals,
            )
            upsert_stmt = upsert_stmt.on_conflict_do_update(
                index_elements=["as_of_date"],
                set_={
                    "raw_regime": upsert_stmt.excluded.raw_regime,
                    "stress_score": upsert_stmt.excluded.stress_score,
                    "signal_details": upsert_stmt.excluded.signal_details,
                    "signal_breakdown": upsert_stmt.excluded.signal_breakdown,
                },
            )
            await db.execute(upsert_stmt)
            await db.commit()
            logger.info("global_regime_snapshot_persisted", as_of_date=str(target_date))
        finally:
            await db.execute(text(f"SELECT pg_advisory_unlock({REGIME_DETECTION_LOCK_ID})"))


async def _compute_and_persist_taa_state(
    db: AsyncSession,
    org_id: uuid.UUID,
    eval_date: date,
) -> None:
    """Compute regime detection + EMA smoothing → upsert taa_regime_state.

    Called after risk metrics commit. Regime detection is done once;
    EMA smoothing + effective band computation is per-profile because
    each profile has different IPS bounds from StrategicAllocation.
    """
    from app.core.config.config_service import ConfigService
    from app.domains.wealth.models.allocation import (
        MacroRegimeSnapshot,
        StrategicAllocation,
        TaaRegimeState,
    )
    from app.domains.wealth.models.block import AllocationBlock
    from quant_engine.regime_service import build_regime_inputs, classify_regime_multi_signal
    from quant_engine.taa_band_service import (
        compute_effective_band,
        extract_stress_score,
        get_regime_centers_for_regime,
        smooth_regime_centers,
    )

    # ── 1. Read global regime snapshot (computed by regime_detection worker) ──
    snapshot_stmt = (
        select(MacroRegimeSnapshot)
        .where(MacroRegimeSnapshot.as_of_date <= eval_date)
        .order_by(MacroRegimeSnapshot.as_of_date.desc())
        .limit(1)
    )
    snapshot_result = await db.execute(snapshot_stmt)
    snapshot = snapshot_result.scalar_one_or_none()

    if snapshot is None:
        logger.warning(
            "taa_no_regime_snapshot — regime_detection worker may not have run. "
            "Falling back to inline classification.",
        )
        # Graceful fallback: compute inline (same as before)
        inputs = await build_regime_inputs(db, as_of_date=eval_date)
        regime, reasons, _ = classify_regime_multi_signal(**inputs)
        stress_score = extract_stress_score(reasons)
    else:
        regime = snapshot.raw_regime
        stress_score = float(snapshot.stress_score) if snapshot.stress_score is not None else None
        reasons = snapshot.signal_details or {}
        logger.info(
            "taa_using_global_snapshot",
            regime=regime,
            stress_score=stress_score,
            snapshot_date=str(snapshot.as_of_date),
        )

    # ── 2. Load TAA config ──
    config_svc = ConfigService(db)
    taa_cfg_result = await config_svc.get("liquid_funds", "taa_bands", str(org_id))
    taa_config = taa_cfg_result.value if taa_cfg_result else None

    # Get raw centers for this regime
    raw_centers = get_regime_centers_for_regime(regime, taa_config)

    # ── 3. Load transition config ──
    transition = (taa_config or {}).get("transition", {})
    halflife = int(transition.get("ema_halflife_days", 5))
    max_shift = float(transition.get("max_daily_shift_pct", 0.03))
    min_confidence = float(transition.get("min_confidence_to_act", 0.60))

    # ── 4. Find all active profiles for this org ──
    profiles_result = await db.execute(
        select(StrategicAllocation.profile)
        .distinct()
        .where(
            StrategicAllocation.effective_from <= eval_date,
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to > eval_date),
        )
    )
    profiles = [row[0] for row in profiles_result.all()]

    if not profiles:
        logger.info("taa_no_active_profiles — skipping regime state persistence")
        return

    # ── 5. Fetch block → asset_class mapping (once) ──
    block_ac_result = await db.execute(
        select(AllocationBlock.block_id, AllocationBlock.asset_class)
    )
    block_asset_classes = {bid: ac for bid, ac in block_ac_result.all()}

    # ── 6. Per-profile: smooth + compute bands + upsert ──
    for prof in profiles:
        # Fetch previous smoothed state for EMA
        prev_stmt = (
            select(TaaRegimeState)
            .where(
                TaaRegimeState.profile == prof,
                TaaRegimeState.as_of_date < eval_date,
            )
            .order_by(TaaRegimeState.as_of_date.desc())
            .limit(1)
        )
        prev_result = await db.execute(prev_stmt)
        prev_row = prev_result.scalar_one_or_none()
        prev_smoothed = prev_row.smoothed_centers if prev_row else None

        # Confidence gating: if stress score delta is below threshold,
        # hold previous smoothed centers (no regime shift enacted).
        confidence_gated = False
        if prev_row is not None and stress_score is not None:
            prev_stress = float(prev_row.stress_score) if prev_row.stress_score is not None else None
            if prev_stress is not None:
                stress_delta = abs(stress_score - prev_stress)
                if stress_delta < min_confidence:
                    confidence_gated = True
                    logger.info(
                        "taa_confidence_gated",
                        profile=prof,
                        stress_delta=round(stress_delta, 2),
                        threshold=min_confidence,
                        action="holding_previous_centers",
                    )

        # EMA smooth (or hold if gated)
        if confidence_gated and prev_smoothed is not None:
            smoothed = dict(prev_smoothed)
        else:
            smoothed = smooth_regime_centers(
                raw_centers, prev_smoothed,
                halflife_days=halflife,
                max_daily_shift=max_shift,
            )

        # Compute transition velocity
        velocity: dict[str, float] = {}
        if prev_smoothed and isinstance(prev_smoothed, dict):
            for ac, current in smoothed.items():
                prev = prev_smoothed.get(ac)
                if prev is not None:
                    velocity[ac] = round(current - prev, 6)

        # Fetch IPS bounds for this profile
        alloc_stmt = (
            select(StrategicAllocation)
            .where(
                StrategicAllocation.profile == prof,
                StrategicAllocation.effective_from <= eval_date,
                (StrategicAllocation.effective_to.is_(None))
                | (StrategicAllocation.effective_to > eval_date),
            )
        )
        alloc_result = await db.execute(alloc_stmt)
        allocs = alloc_result.scalars().all()

        # Get regime half widths
        regime_bands = (taa_config or {}).get("regime_bands", {})
        regime_cfg = regime_bands.get(regime, regime_bands.get("RISK_ON", {}))
        half_widths: dict[str, float] = {
            ac: cfg.get("half_width", 0.05)
            for ac, cfg in regime_cfg.items()
            if isinstance(cfg, dict) and "half_width" in cfg
        }

        # Compute effective bands per block
        effective_bands: dict[str, dict[str, float]] = {}
        for a in allocs:
            ac = block_asset_classes.get(a.block_id)
            if ac is None or ac not in smoothed:
                continue
            # Disaggregate: compute this block's share of asset-class center
            class_total = sum(
                float(aa.target_weight) for aa in allocs
                if block_asset_classes.get(aa.block_id) == ac
            )
            if class_total <= 0:
                continue
            block_ratio = float(a.target_weight) / class_total
            block_center = smoothed[ac] * block_ratio
            block_half = half_widths.get(ac, 0.05) * block_ratio

            # PR-A26.2 — ``min_weight/max_weight`` columns dropped; read the
            # approved drift band. NULL (pre-approval) falls back to [0, 1].
            _min_w = float(a.drift_min) if a.drift_min is not None else 0.0
            _max_w = float(a.drift_max) if a.drift_max is not None else 1.0
            eff_min, eff_max = compute_effective_band(
                _min_w, _max_w,
                block_center, block_half,
            )
            effective_bands[a.block_id] = {
                "min": round(eff_min, 6),
                "max": round(eff_max, 6),
                "center": round(block_center, 6),
            }

        # Upsert taa_regime_state
        from sqlalchemy.dialects.postgresql import insert as pg_insert_fn
        upsert = pg_insert_fn(TaaRegimeState).values(
            organization_id=org_id,
            profile=prof,
            as_of_date=eval_date,
            raw_regime=regime,
            stress_score=stress_score,
            smoothed_centers=smoothed,
            effective_bands=effective_bands,
            transition_velocity=velocity or None,
        )
        upsert = upsert.on_conflict_do_update(
            constraint="uq_taa_regime_state_org_profile_date",
            set_={
                "raw_regime": upsert.excluded.raw_regime,
                "stress_score": upsert.excluded.stress_score,
                "smoothed_centers": upsert.excluded.smoothed_centers,
                "effective_bands": upsert.excluded.effective_bands,
                "transition_velocity": upsert.excluded.transition_velocity,
            },
        )
        await db.execute(upsert)

        # ── Audit: log TAA state transitions ──
        prev_regime = prev_row.raw_regime if prev_row else None
        regime_changed = prev_regime is not None and prev_regime != regime
        if regime_changed or prev_row is None:
            from app.core.db.audit import write_audit_event

            await write_audit_event(
                db,
                action="taa_regime_transition" if regime_changed else "taa_regime_initialized",
                entity_type="TaaRegimeState",
                entity_id=f"{prof}:{eval_date}",
                organization_id=org_id,
                before={
                    "raw_regime": prev_regime,
                    "stress_score": float(prev_row.stress_score) if prev_row and prev_row.stress_score else None,
                    "smoothed_centers": dict(prev_row.smoothed_centers) if prev_row and prev_row.smoothed_centers else None,
                } if prev_row else None,
                after={
                    "raw_regime": regime,
                    "stress_score": stress_score,
                    "smoothed_centers": smoothed,
                    "effective_bands": effective_bands,
                    "transition_velocity": velocity or None,
                    "confidence_gated": confidence_gated,
                },
            )

    await db.commit()
    logger.info(
        "taa_regime_state_persisted",
        regime=regime,
        stress_score=stress_score,
        profiles=profiles,
        eval_date=str(eval_date),
    )


async def run_risk_calc(org_id: "uuid.UUID", as_of_date: date | None = None) -> dict[str, int]:
    """Compute risk metrics for all active funds with NAV data."""
    logger.info("Starting risk calculation", as_of_date=str(as_of_date))
    results: dict[str, int] = {}

    async with async_session() as db:
        await set_rls_context(db, org_id)
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({RISK_CALC_LOCK_ID})"),
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("worker_skipped", reason="another instance running")
            return {"status": "skipped", "reason": "risk calculation already running"}
        try:
            # Fetch live risk-free rate from FRED DFF (once for all funds)
            rfr = await get_risk_free_rate(db)
            logger.info("Risk-free rate for this run", rate=rfr)

            # Load scoring config from ConfigService (once for all funds)
            from app.core.config.config_service import ConfigService

            config_svc = ConfigService(db)
            scoring_result = await config_svc.get("liquid_funds", "scoring", str(org_id))
            scoring_config = scoring_result.value if scoring_result else None
            logger.info("Scoring config loaded", source=getattr(scoring_result, "source", "unknown"))

            stmt = (
                select(Instrument)
                .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
                .where(
                    InstrumentOrg.organization_id == org_id,
                    Instrument.is_active == True,
                    Instrument.ticker.is_not(None),
                    Instrument.instrument_type == "fund",
                )
            )
            result = await db.execute(stmt)
            funds = result.scalars().all()

            # Fetch block_id mapping from instruments_org
            block_id_stmt = (
                select(InstrumentOrg.instrument_id, InstrumentOrg.block_id)
                .where(InstrumentOrg.organization_id == org_id)
            )
            block_id_result = await db.execute(block_id_stmt)
            block_id_map: dict[str, str | None] = {
                str(iid): bid for iid, bid in block_id_result.all()
            }

            logger.info("Funds to process", count=len(funds))

            eval_date = as_of_date or date.today()
            # 10 years + 60-day buffer — supports 5Y/10Y annualized returns
            start_date = eval_date - timedelta(days=10 * 365 + 60)

            all_fund_ids = [fund.instrument_id for fund in funds]

            # Batch 1: resolve return_type for every fund — 1 query instead of N
            return_type_by_fund = await _batch_resolve_return_types(
                db, all_fund_ids, start_date, eval_date,
            )
            logger.info("Return types resolved", n_funds=len(return_type_by_fund))

            # Batch 2: fetch all NAV returns — at most 2 queries instead of N
            nav_returns_by_fund, rejected_by_fund = await _batch_fetch_nav_returns(
                db, all_fund_ids, return_type_by_fund, start_date, eval_date,
            )
            logger.info("NAV returns batch-fetched", n_funds=len(nav_returns_by_fund))

            # Pass 1: compute standard risk metrics from pre-fetched data — no DB queries in loop
            computed: list[tuple[Instrument, dict]] = []
            for fund in funds:
                fid_str = str(fund.instrument_id)
                returns_raw = nav_returns_by_fund.get(fid_str, [])
                rejected_count = rejected_by_fund.get(fid_str, 0)
                metrics = _compute_metrics_from_returns(fund, returns_raw, eval_date, risk_free_rate=rfr, rejected_count=rejected_count)
                if metrics is None:
                    results[fund.ticker or fid_str] = 0
                    continue
                computed.append((fund, metrics))

            # Pass 1.5: compute momentum signals from NAV prices (single batch query)
            nav_price_map = await _batch_fetch_nav_prices(db, all_fund_ids, eval_date)
            logger.info("NAV prices batch-fetched for momentum", n_funds=len(nav_price_map))

            for fund, metrics in computed:
                fid_str = str(fund.instrument_id)
                nav_data = nav_price_map.get(fid_str)
                if nav_data is None:
                    metrics.update({
                        "rsi_14": None,
                        "bb_position": None,
                        "nav_momentum_score": None,
                        "flow_momentum_score": None,
                        "blended_momentum_score": None,
                    })
                    continue
                close, aum = nav_data
                momentum = _compute_momentum_from_nav(close, aum)
                metrics.update(momentum)

            # Pass 1.6: compute regime-conditional CVaR (BL-9)
            # Reads HMM-classified RISK_OFF/CRISIS dates from macro_regime_history.
            stress_dates = await _fetch_stress_dates(db, start_date, eval_date)
            logger.info("Regime stress dates fetched", n_stress_dates=len(stress_dates))

            if stress_dates:
                dated_returns_by_fund = await _batch_fetch_dated_returns(
                    db, all_fund_ids, return_type_by_fund, start_date, eval_date,
                )
                for fund, metrics in computed:
                    fid_str = str(fund.instrument_id)
                    dated_returns = dated_returns_by_fund.get(fid_str, [])
                    stress_returns = [r for d, r in dated_returns if d in stress_dates]
                    if len(stress_returns) >= MIN_STRESS_OBS:
                        cvar_cond, _ = compute_cvar_from_returns(
                            np.array(stress_returns), confidence=0.95,
                        )
                        metrics["cvar_95_conditional"] = round(cvar_cond, 6)
                    else:
                        metrics["cvar_95_conditional"] = None
            else:
                logger.warning("No regime stress dates in lookback — cvar_95_conditional will be NULL")
                for _, metrics in computed:
                    metrics["cvar_95_conditional"] = None

            # Pass 1.7: FI analytics (empirical duration, credit beta) for fixed_income funds
            fi_fund_ids = {str(f.instrument_id) for f, _ in computed if f.asset_class == "fixed_income"}
            cash_fund_ids = {str(f.instrument_id) for f, _ in computed if f.asset_class == "cash"}
            if fi_fund_ids:
                fi_config = FIRegressionConfig()
                yield_changes = await _batch_fetch_macro_yield_changes(db, start_date, eval_date)
                # Reuse dated_returns if already fetched for CVaR, else fetch now
                if not stress_dates:
                    dated_returns_by_fund = await _batch_fetch_dated_returns(
                        db, all_fund_ids, return_type_by_fund, start_date, eval_date,
                    )
                for fund, metrics in computed:
                    fid_str = str(fund.instrument_id)
                    if fid_str not in fi_fund_ids:
                        continue
                    metrics["scoring_model"] = "fixed_income"
                    fund_dated_returns = dated_returns_by_fund.get(fid_str, [])
                    if not fund_dated_returns:
                        continue
                    fi_result = compute_fi_analytics(
                        fund_dated_returns=fund_dated_returns,
                        treasury_yield_changes=yield_changes.get("DGS10", []),
                        credit_spread_changes=yield_changes.get("BAA10Y", []),
                        max_drawdown_1y=metrics.get("max_drawdown_1y"),
                        config=fi_config,
                    )
                    metrics["empirical_duration"] = round(fi_result.empirical_duration, 4) if fi_result.empirical_duration is not None else None
                    metrics["empirical_duration_r2"] = round(fi_result.duration_r_squared, 4) if fi_result.duration_r_squared is not None else None
                    metrics["credit_beta"] = round(fi_result.credit_beta, 4) if fi_result.credit_beta is not None else None
                    metrics["credit_beta_r2"] = round(fi_result.credit_beta_r_squared, 4) if fi_result.credit_beta_r_squared is not None else None
                    metrics["yield_proxy_12m"] = round(fi_result.yield_proxy_12m, 6) if fi_result.yield_proxy_12m is not None else None
                    metrics["duration_adj_drawdown_1y"] = round(fi_result.duration_adj_drawdown, 6) if fi_result.duration_adj_drawdown is not None else None
                logger.info("fi_analytics_computed", fi_funds=len(fi_fund_ids))

            # Pass 1.75: Cash/MMF analytics from sec_money_market_funds + sec_mmf_metrics + FRED DFF
            if cash_fund_ids:
                # Batch fetch: latest DFF from macro_data
                fed_funds_rate = await _fetch_latest_macro_value(db, "DFF", eval_date)
                # Batch fetch: MMF metadata (WAM, liquidity, NAV) from sec_money_market_funds
                mmf_data = await _batch_fetch_mmf_data(db, computed, cash_fund_ids)
                # Batch fetch: latest 7-day net yield from sec_mmf_metrics
                mmf_yields = await _batch_fetch_mmf_yields(db, computed, cash_fund_ids)

                for fund, metrics in computed:
                    fid_str = str(fund.instrument_id)
                    if fid_str not in cash_fund_ids:
                        continue
                    metrics["scoring_model"] = "cash"
                    mmf_info = mmf_data.get(fid_str, {})
                    yield_info = mmf_yields.get(fid_str, {})
                    metrics["seven_day_net_yield"] = yield_info.get("seven_day_net_yield")
                    metrics["fed_funds_rate_at_calc"] = fed_funds_rate
                    metrics["nav_per_share_mmf"] = mmf_info.get("stable_nav_price") or mmf_info.get("nav_per_share")
                    metrics["pct_weekly_liquid"] = mmf_info.get("pct_weekly_liquid_latest")
                    metrics["weighted_avg_maturity_days"] = mmf_info.get("weighted_avg_maturity")
                logger.info("cash_analytics_computed", cash_funds=len(cash_fund_ids))

            # Pass 1.78: Alternatives analytics (correlation, capture, crisis alpha, inflation beta)
            alt_fund_ids = {str(f.instrument_id) for f, _ in computed if f.asset_class == "alternatives"}
            if alt_fund_ids:
                alt_config = AltAnalyticsConfig()
                # Fetch SPY benchmark returns (via na_equity_large block)
                spy_returns = await _fetch_benchmark_dated_returns(db, "na_equity_large", start_date, eval_date)
                # Fetch monthly CPI changes for inflation beta regression
                cpi_changes = await _fetch_monthly_cpi_changes(db, start_date, eval_date)
                # Reuse dated_returns if already fetched, else fetch now
                if not stress_dates and not fi_fund_ids:
                    dated_returns_by_fund = await _batch_fetch_dated_returns(
                        db, all_fund_ids, return_type_by_fund, start_date, eval_date,
                    )
                for fund, metrics in computed:
                    fid_str = str(fund.instrument_id)
                    if fid_str not in alt_fund_ids:
                        continue
                    metrics["scoring_model"] = "alternatives"
                    fund_dated_returns = dated_returns_by_fund.get(fid_str, [])
                    if not fund_dated_returns:
                        continue
                    alt_result = compute_alt_analytics(
                        fund_dated_returns=fund_dated_returns,
                        benchmark_dated_returns=spy_returns,
                        cpi_monthly_changes=cpi_changes,
                        return_3y_ann=metrics.get("return_3y_ann"),
                        max_drawdown_3y=metrics.get("max_drawdown_3y"),
                        config=alt_config,
                    )
                    metrics["equity_correlation_252d"] = round(alt_result.equity_correlation_252d, 4) if alt_result.equity_correlation_252d is not None else None
                    metrics["downside_capture_1y"] = round(alt_result.downside_capture_1y, 4) if alt_result.downside_capture_1y is not None else None
                    metrics["upside_capture_1y"] = round(alt_result.upside_capture_1y, 4) if alt_result.upside_capture_1y is not None else None
                    metrics["crisis_alpha_score"] = round(alt_result.crisis_alpha_score, 6) if alt_result.crisis_alpha_score is not None else None
                    metrics["calmar_ratio_3y"] = round(alt_result.calmar_ratio_3y, 4) if alt_result.calmar_ratio_3y is not None else None
                    metrics["inflation_beta"] = round(alt_result.inflation_beta, 4) if alt_result.inflation_beta is not None else None
                    metrics["inflation_beta_r2"] = round(alt_result.inflation_beta_r2, 4) if alt_result.inflation_beta_r2 is not None else None
                logger.info("alt_analytics_computed", alt_funds=len(alt_fund_ids))

            # Assign scoring_model = "equity" for funds not covered by FI, Cash, or Alternatives
            for fund, metrics in computed:
                if "scoring_model" not in metrics:
                    metrics["scoring_model"] = "equity"

            # Pass 1.8: compute manager_score from base metrics + momentum + config
            for fund, metrics in computed:
                er = (fund.attributes or {}).get("expense_ratio_pct")
                bid = block_id_map.get(str(fund.instrument_id))
                strategy_lbl = (fund.attributes or {}).get("strategy_label")
                _score_metrics(
                    metrics,
                    scoring_config=scoring_config,
                    expense_ratio_pct=float(er) if er is not None else None,
                    asset_class=fund.asset_class or "equity",
                    block_id=bid,
                    strategy_label=strategy_lbl,
                )

            # Pass 2: upsert metrics (DTW drift now handled by global worker)
            try:
                for fund, metrics in computed:
                    metrics["organization_id"] = org_id
                    upsert = pg_insert(FundRiskMetrics).values(**metrics)
                    # Conflict target includes organization_id so this org's
                    # row is the only one updated; the global (NULL) row and
                    # other tenants' rows stay untouched. PG matches the
                    # NULLS NOT DISTINCT unique index from migration 0093.
                    upsert = upsert.on_conflict_do_update(
                        index_elements=["instrument_id", "calc_date", "organization_id"],
                        set_={
                            k: upsert.excluded[k]
                            for k in metrics
                            if k not in ("instrument_id", "calc_date", "organization_id")
                        },
                    )
                    await db.execute(upsert)
                    results[fund.ticker or str(fund.instrument_id)] = 1
                    logger.info("Risk metrics staged", ticker=fund.ticker)

                # Single commit for the entire batch — atomic and WAL-efficient
                await db.commit()
                logger.info("Risk metrics batch committed", funds_staged=len(computed))

                await _write_risk_cache(org_id, eval_date, computed)

                # ── TAA: Compute and persist taa_regime_state ──
                try:
                    await _compute_and_persist_taa_state(db, org_id, eval_date)
                except Exception:
                    logger.exception("taa_regime_state_computation_failed — non-fatal, risk metrics already committed")
            except Exception:
                await db.rollback()
                logger.exception("Risk metrics batch failed — transaction rolled back")
                raise
        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({RISK_CALC_LOCK_ID})"),
                )
            except Exception:
                pass

    total = sum(results.values())
    logger.info("Risk calculation complete", funds_computed=total)
    return results


GLOBAL_RISK_METRICS_LOCK_ID = 900_071
GLOBAL_RISK_BATCH_SIZE = 200


async def run_global_risk_metrics(as_of_date: date | None = None) -> dict[str, int]:
    """Compute base risk metrics for ALL active instruments with NAV.

    Global worker — no org_id, no RLS.
    Writes to fund_risk_metrics with organization_id = NULL.
    Any tenant importing a fund immediately sees pre-computed metrics.

    DTW drift is computed globally by strategy_label (from mv_unified_funds).
    5Y and 10Y annualized returns computed when sufficient NAV history exists.
    """
    logger.info("global_risk_metrics.start", as_of_date=str(as_of_date))
    results: dict[str, int] = {"computed": 0, "skipped": 0, "error": 0}

    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({GLOBAL_RISK_METRICS_LOCK_ID})"),
        )
        if not lock_result.scalar():
            logger.warning("global_risk_metrics.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            rfr = await get_risk_free_rate(db)
            eval_date = as_of_date or date.today()
            start_date = eval_date - timedelta(days=10 * 365 + 60)

            # All active funds with ticker (no org join)
            stmt = (
                select(Instrument)
                .where(
                    Instrument.is_active == True,  # noqa: E712
                    Instrument.ticker.is_not(None),
                    Instrument.instrument_type == "fund",
                )
            )
            result = await db.execute(stmt)
            all_funds_raw = result.scalars().all()
            # Extract scalars from ORM objects BEFORE the batch loop.
            # rollback() expires ALL identity-map objects regardless of
            # expire_on_commit — accessing ORM attrs after a failed batch
            # upsert would trigger MissingGreenlet.  Frozen snapshots are
            # immune to session state changes.
            all_funds: list[_FundSnapshot] = [
                _FundSnapshot(
                    instrument_id=f.instrument_id,
                    ticker=f.ticker,
                    asset_class=f.asset_class or "equity",
                    attributes=dict(f.attributes) if f.attributes else {},
                )
                for f in all_funds_raw
            ]
            del all_funds_raw  # release ORM objects from identity map
            logger.info("global_risk_metrics.funds_found", count=len(all_funds))

            # Process in batches to avoid memory pressure
            for batch_start in range(0, len(all_funds), GLOBAL_RISK_BATCH_SIZE):
                batch = all_funds[batch_start:batch_start + GLOBAL_RISK_BATCH_SIZE]
                batch_ids = [f.instrument_id for f in batch]

                # Batch resolve return types
                return_type_by_fund = await _batch_resolve_return_types(
                    db, batch_ids, start_date, eval_date,
                )

                # Batch fetch returns
                nav_returns_by_fund, rejected_by_fund = await _batch_fetch_nav_returns(
                    db, batch_ids, return_type_by_fund, start_date, eval_date,
                )

                # Pass 1: compute standard metrics
                computed: list[tuple[Instrument, dict]] = []
                for fund in batch:
                    fid_str = str(fund.instrument_id)
                    returns_raw = nav_returns_by_fund.get(fid_str, [])
                    rejected_count = rejected_by_fund.get(fid_str, 0)
                    metrics = _compute_metrics_from_returns(fund, returns_raw, eval_date, risk_free_rate=rfr, rejected_count=rejected_count)
                    if metrics is None:
                        results["skipped"] += 1
                        continue
                    computed.append((fund, metrics))

                # Pass 1.5: momentum signals
                nav_price_map = await _batch_fetch_nav_prices(db, batch_ids, eval_date)
                for fund, metrics in computed:
                    fid_str = str(fund.instrument_id)
                    nav_data = nav_price_map.get(fid_str)
                    if nav_data is None:
                        metrics.update({
                            "rsi_14": None, "bb_position": None,
                            "nav_momentum_score": None,
                            "flow_momentum_score": None,
                            "blended_momentum_score": None,
                        })
                        continue
                    close, aum = nav_data
                    metrics.update(_compute_momentum_from_nav(close, aum))

                # Pass 1.6: regime-conditional CVaR
                stress_dates = await _fetch_stress_dates(db, start_date, eval_date)
                if stress_dates:
                    dated_returns_by_fund = await _batch_fetch_dated_returns(
                        db, batch_ids, return_type_by_fund, start_date, eval_date,
                    )
                    for fund, metrics in computed:
                        fid_str = str(fund.instrument_id)
                        dated_returns = dated_returns_by_fund.get(fid_str, [])
                        stress_returns = [r for d, r in dated_returns if d in stress_dates]
                        if len(stress_returns) >= MIN_STRESS_OBS:
                            cvar_cond, _ = compute_cvar_from_returns(
                                np.array(stress_returns), confidence=0.95,
                            )
                            metrics["cvar_95_conditional"] = round(cvar_cond, 6)
                        else:
                            metrics["cvar_95_conditional"] = None
                else:
                    for _, metrics in computed:
                        metrics["cvar_95_conditional"] = None

                # Pass 1.7: FI analytics for fixed_income funds in this batch
                fi_fund_ids = {str(f.instrument_id) for f, _ in computed if f.asset_class == "fixed_income"}
                cash_fund_ids_g = {str(f.instrument_id) for f, _ in computed if f.asset_class == "cash"}
                if fi_fund_ids:
                    fi_config = FIRegressionConfig()
                    yield_changes = await _batch_fetch_macro_yield_changes(db, start_date, eval_date)
                    # Reuse dated_returns if already fetched for CVaR, else fetch now
                    if not stress_dates:
                        dated_returns_by_fund = await _batch_fetch_dated_returns(
                            db, batch_ids, return_type_by_fund, start_date, eval_date,
                        )
                    for fund, metrics in computed:
                        fid_str = str(fund.instrument_id)
                        if fid_str not in fi_fund_ids:
                            continue
                        metrics["scoring_model"] = "fixed_income"
                        fund_dated_returns = dated_returns_by_fund.get(fid_str, [])
                        if not fund_dated_returns:
                            continue
                        fi_result = compute_fi_analytics(
                            fund_dated_returns=fund_dated_returns,
                            treasury_yield_changes=yield_changes.get("DGS10", []),
                            credit_spread_changes=yield_changes.get("BAA10Y", []),
                            max_drawdown_1y=metrics.get("max_drawdown_1y"),
                            config=fi_config,
                        )
                        metrics["empirical_duration"] = round(fi_result.empirical_duration, 4) if fi_result.empirical_duration is not None else None
                        metrics["empirical_duration_r2"] = round(fi_result.duration_r_squared, 4) if fi_result.duration_r_squared is not None else None
                        metrics["credit_beta"] = round(fi_result.credit_beta, 4) if fi_result.credit_beta is not None else None
                        metrics["credit_beta_r2"] = round(fi_result.credit_beta_r_squared, 4) if fi_result.credit_beta_r_squared is not None else None
                        metrics["yield_proxy_12m"] = round(fi_result.yield_proxy_12m, 6) if fi_result.yield_proxy_12m is not None else None
                        metrics["duration_adj_drawdown_1y"] = round(fi_result.duration_adj_drawdown, 6) if fi_result.duration_adj_drawdown is not None else None
                    logger.info("fi_analytics_computed", fi_funds=len(fi_fund_ids), batch_start=batch_start)

                # Pass 1.75: Cash/MMF analytics for cash funds in this batch
                if cash_fund_ids_g:
                    fed_funds_rate = await _fetch_latest_macro_value(db, "DFF", eval_date)
                    mmf_data = await _batch_fetch_mmf_data(db, computed, cash_fund_ids_g)
                    mmf_yields = await _batch_fetch_mmf_yields(db, computed, cash_fund_ids_g)
                    for fund, metrics in computed:
                        fid_str = str(fund.instrument_id)
                        if fid_str not in cash_fund_ids_g:
                            continue
                        metrics["scoring_model"] = "cash"
                        mmf_info = mmf_data.get(fid_str, {})
                        yield_info = mmf_yields.get(fid_str, {})
                        metrics["seven_day_net_yield"] = yield_info.get("seven_day_net_yield")
                        metrics["fed_funds_rate_at_calc"] = fed_funds_rate
                        metrics["nav_per_share_mmf"] = mmf_info.get("stable_nav_price") or mmf_info.get("nav_per_share")
                        metrics["pct_weekly_liquid"] = mmf_info.get("pct_weekly_liquid_latest")
                        metrics["weighted_avg_maturity_days"] = mmf_info.get("weighted_avg_maturity")
                    logger.info("cash_analytics_computed", cash_funds=len(cash_fund_ids_g), batch_start=batch_start)

                # Pass 1.78: Alternatives analytics for alt funds in this batch
                alt_fund_ids_g = {str(f.instrument_id) for f, _ in computed if f.asset_class == "alternatives"}
                if alt_fund_ids_g:
                    alt_config = AltAnalyticsConfig()
                    spy_returns = await _fetch_benchmark_dated_returns(db, "na_equity_large", start_date, eval_date)
                    cpi_changes = await _fetch_monthly_cpi_changes(db, start_date, eval_date)
                    if not stress_dates and not fi_fund_ids:
                        dated_returns_by_fund = await _batch_fetch_dated_returns(
                            db, batch_ids, return_type_by_fund, start_date, eval_date,
                        )
                    for fund, metrics in computed:
                        fid_str = str(fund.instrument_id)
                        if fid_str not in alt_fund_ids_g:
                            continue
                        metrics["scoring_model"] = "alternatives"
                        fund_dated_returns = dated_returns_by_fund.get(fid_str, [])
                        if not fund_dated_returns:
                            continue
                        alt_result = compute_alt_analytics(
                            fund_dated_returns=fund_dated_returns,
                            benchmark_dated_returns=spy_returns,
                            cpi_monthly_changes=cpi_changes,
                            return_3y_ann=metrics.get("return_3y_ann"),
                            max_drawdown_3y=metrics.get("max_drawdown_3y"),
                            config=alt_config,
                        )
                        metrics["equity_correlation_252d"] = round(alt_result.equity_correlation_252d, 4) if alt_result.equity_correlation_252d is not None else None
                        metrics["downside_capture_1y"] = round(alt_result.downside_capture_1y, 4) if alt_result.downside_capture_1y is not None else None
                        metrics["upside_capture_1y"] = round(alt_result.upside_capture_1y, 4) if alt_result.upside_capture_1y is not None else None
                        metrics["crisis_alpha_score"] = round(alt_result.crisis_alpha_score, 6) if alt_result.crisis_alpha_score is not None else None
                        metrics["calmar_ratio_3y"] = round(alt_result.calmar_ratio_3y, 4) if alt_result.calmar_ratio_3y is not None else None
                        metrics["inflation_beta"] = round(alt_result.inflation_beta, 4) if alt_result.inflation_beta is not None else None
                        metrics["inflation_beta_r2"] = round(alt_result.inflation_beta_r2, 4) if alt_result.inflation_beta_r2 is not None else None
                    logger.info("alt_analytics_computed", alt_funds=len(alt_fund_ids_g), batch_start=batch_start)

                # Assign scoring_model = "equity" for funds not covered by FI, Cash, or Alternatives
                for fund, metrics in computed:
                    if "scoring_model" not in metrics:
                        metrics["scoring_model"] = "equity"

                # Pass 1.8: compute manager_score from base metrics + momentum + expense ratio
                # Batch-fetch expense ratios from mv_unified_funds via ticker
                batch_tickers = [f.ticker for f in batch if f.ticker]
                er_map: dict[str, float] = {}
                if batch_tickers:
                    placeholders = ", ".join(f"'{t}'" for t in batch_tickers)
                    er_result = await db.execute(text(f"""
                        SELECT ticker, expense_ratio_pct
                        FROM mv_unified_funds
                        WHERE ticker IN ({placeholders})
                          AND expense_ratio_pct IS NOT NULL
                    """))
                    for row in er_result.mappings().all():
                        er_map[row["ticker"]] = float(row["expense_ratio_pct"])

                for fund, metrics in computed:
                    er = er_map.get(fund.ticker) if fund.ticker else None
                    strategy_lbl = (fund.attributes or {}).get("strategy_label")
                    _score_metrics(
                        metrics,
                        expense_ratio_pct=er,
                        asset_class=fund.asset_class or "equity",
                        strategy_label=strategy_lbl,
                    )

                # Pass 1.9: DTW drift scores by strategy_label (global)
                batch_tickers_dtw = [f.ticker for f in batch if f.ticker]
                strategy_map_batch: dict[str, str | None] = {}
                if batch_tickers_dtw:
                    placeholders_dtw = ", ".join(f"'{t}'" for t in batch_tickers_dtw)
                    strat_result = await db.execute(text(f"""
                        SELECT ticker, strategy_label FROM mv_unified_funds
                        WHERE ticker IN ({placeholders_dtw})
                          AND strategy_label IS NOT NULL
                    """))
                    ticker_to_strat = {r[0]: r[1] for r in strat_result.all()}
                    for fund, _ in computed:
                        if fund.ticker and fund.ticker in ticker_to_strat:
                            strategy_map_batch[str(fund.instrument_id)] = ticker_to_strat[fund.ticker]

                dtw_scores_batch = await _compute_global_dtw_scores(
                    db, computed, as_of_date=eval_date,
                    strategy_map=strategy_map_batch,
                )
                logger.info(
                    "global_risk_metrics.dtw_computed",
                    batch_start=batch_start,
                    dtw_scores=len(dtw_scores_batch),
                )

                # Upsert batch with DTW drift, no org_id
                try:
                    for fund, metrics in computed:
                        metrics["organization_id"] = None
                        fid_str = str(fund.instrument_id)
                        dtw_result = dtw_scores_batch.get(
                            fid_str,
                            DtwDriftResult(score=None, status=DtwDriftStatus.degraded, reason="not in dtw batch"),
                        )
                        metrics["dtw_drift_score"] = round(dtw_result.score_or_default(0.0), 6) if dtw_result.is_usable else None
                        upsert = pg_insert(FundRiskMetrics).values(**metrics)
                        # Conflict target includes organization_id (NULL here);
                        # NULLS NOT DISTINCT unique index from migration 0093
                        # ensures only the global row is updated, never any
                        # tenant-scoped row.
                        upsert = upsert.on_conflict_do_update(
                            index_elements=["instrument_id", "calc_date", "organization_id"],
                            set_={
                                k: upsert.excluded[k]
                                for k in metrics
                                if k not in ("instrument_id", "calc_date", "organization_id")
                            },
                        )
                        await db.execute(upsert)
                    await db.commit()
                    results["computed"] += len(computed)
                    logger.info(
                        "global_risk_metrics.batch_committed",
                        batch_start=batch_start,
                        batch_computed=len(computed),
                    )
                except Exception as exc:
                    await db.rollback()
                    results["error"] += len(computed)
                    logger.error("global_risk_metrics.batch_failed", batch_start=batch_start, error=str(exc)[:200])

            # Pass 2: Peer percentile ranking (strategy-grouped)
            # Groups all freshly-computed funds by strategy_label from mv_unified_funds,
            # then computes percentile rank for sharpe, sortino, return, drawdown.
            try:
                peer_updated = await _compute_global_peer_percentiles(db, eval_date)
                results["peer_ranked"] = peer_updated
                logger.info("global_risk_metrics.peer_ranking_done", peer_ranked=peer_updated)
            except Exception:
                logger.exception("global_risk_metrics.peer_ranking_failed")

            # Pass 3: ELITE ranking — top 300 funds by manager_score
            # proportional to the global default strategic allocation
            # (Phase 2 Session B commit 7).
            try:
                total_elite, per_strategy = await _compute_elite_ranking(db, eval_date)
                results["elite_ranked"] = total_elite
                logger.info(
                    "global_risk_metrics.elite_ranking_done",
                    total_elite=total_elite,
                    per_strategy=per_strategy,
                )
            except Exception:
                logger.exception("global_risk_metrics.elite_ranking_failed")

            # Pass 4: refresh the screener hot-path materialized view
            # so Phase 3 Screener sees the new elite_flag + metrics.
            try:
                await db.execute(
                    text("REFRESH MATERIALIZED VIEW CONCURRENTLY mv_fund_risk_latest"),
                )
                await db.commit()
                logger.info("global_risk_metrics.mv_fund_risk_latest_refreshed")
            except Exception:
                await db.rollback()
                logger.exception("global_risk_metrics.mv_refresh_failed")

            logger.info("global_risk_metrics.done", **results)
            return results
        finally:
            try:
                await db.execute(
                    text(f"SELECT pg_advisory_unlock({GLOBAL_RISK_METRICS_LOCK_ID})"),
                )
            except Exception:
                pass


async def _compute_global_peer_percentiles(db: AsyncSession, calc_date: date) -> int:
    """Compute peer percentile rankings for all funds grouped by strategy.

    For each strategy_label with >= 5 peers, computes percentile rank
    (0-100, higher = better) for sharpe_1y, sortino_1y, return_1y,
    max_drawdown_1y. Writes peer_*_pctl + peer_count + peer_strategy_label
    back into fund_risk_metrics.

    Uses a single SQL query to fetch all metrics + strategy labels,
    then NumPy vectorized percentile computation per group.
    """
    import numpy as np
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    MIN_PEERS = 5

    # Fetch all metrics for today + strategy labels from mv_unified_funds.
    #
    # S5 universe-collapse guard — the LEFT JOIN to mv_unified_funds is on
    # ticker. Two distinct fund universes (e.g. an ETF and a money-market
    # fund) can share a NULL ticker, which would let any row from
    # mv_unified_funds match any row from instruments_universe whose
    # ticker is also NULL — non-deterministic strategy labels and silent
    # cross-universe peer contamination. We require both sides to have a
    # non-NULL ticker on the JOIN; rows without a ticker fall through the
    # COALESCE to the 'Unknown' strategy bucket where they belong.
    query = text("""
        SELECT
            frm.instrument_id,
            frm.sharpe_1y,
            frm.sortino_1y,
            frm.return_1y,
            frm.max_drawdown_1y,
            COALESCE(f.strategy_label, f.fund_type, 'Unknown') AS strategy_label
        FROM fund_risk_metrics frm
        JOIN instruments_universe iu ON iu.instrument_id = frm.instrument_id
        LEFT JOIN mv_unified_funds f
               ON f.ticker = iu.ticker
              AND iu.ticker IS NOT NULL
              AND f.ticker IS NOT NULL
        WHERE frm.calc_date = :calc_date
          AND frm.sharpe_1y IS NOT NULL
    """)
    result = await db.execute(query, {"calc_date": calc_date})
    rows = result.mappings().all()

    if not rows:
        return 0

    # Group by strategy
    from collections import defaultdict
    groups: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        groups[row["strategy_label"]].append(dict(row))

    updated = 0
    for strategy, funds in groups.items():
        if len(funds) < MIN_PEERS:
            continue

        # S5 — instruments_universe enumerates only *currently active*
        # funds (Yahoo Finance / SEC stops emitting data for liquidated
        # / merged funds, and they age out of the catalog). The peer
        # percentile is therefore biased upward: every fund is being
        # ranked against survivors, not the full population that
        # included the funds that died for being terrible. We cannot
        # inject the dead funds without a separate historical universe,
        # but we can audit-log the bias so analysts know the rank is
        # an upper-bound estimate.
        logger.warning(
            "peer_percentile_survivorship_biased",
            data_quality_flag="survivorship_biased",
            strategy=strategy,
            peer_count=len(funds),
            note=(
                "instruments_universe contains only currently-listed funds; "
                "rank is computed against survivors only and is therefore an "
                "upper bound on the fund's true peer percentile"
            ),
        )

        # Build arrays
        sharpe_arr = np.array([f["sharpe_1y"] for f in funds if f["sharpe_1y"] is not None], dtype=float)
        sortino_arr = np.array([f["sortino_1y"] for f in funds if f["sortino_1y"] is not None], dtype=float)
        return_arr = np.array([f["return_1y"] for f in funds if f["return_1y"] is not None], dtype=float)
        dd_arr = np.array([f["max_drawdown_1y"] for f in funds if f["max_drawdown_1y"] is not None], dtype=float)

        peer_count = len(funds)

        for fund in funds:
            # Percentile: higher is better for sharpe/sortino/return, higher (less negative) is better for drawdown
            sharpe_pctl = _pctl(fund["sharpe_1y"], sharpe_arr) if fund["sharpe_1y"] is not None else None
            sortino_pctl = _pctl(fund["sortino_1y"], sortino_arr) if fund["sortino_1y"] is not None else None
            return_pctl = _pctl(fund["return_1y"], return_arr) if fund["return_1y"] is not None else None
            dd_pctl = _pctl(fund["max_drawdown_1y"], dd_arr) if fund["max_drawdown_1y"] is not None else None

            # Peer percentiles are a global concept — they belong on the
            # global row (organization_id IS NULL). Explicitly target it so
            # the NULLS NOT DISTINCT unique index from migration 0093
            # routes the upsert to the global row, never to a tenant row.
            upsert = pg_insert(FundRiskMetrics).values(
                instrument_id=fund["instrument_id"],
                calc_date=calc_date,
                organization_id=None,
                peer_strategy_label=strategy,
                peer_sharpe_pctl=sharpe_pctl,
                peer_sortino_pctl=sortino_pctl,
                peer_return_pctl=return_pctl,
                peer_drawdown_pctl=dd_pctl,
                peer_count=peer_count,
            )
            upsert = upsert.on_conflict_do_update(
                index_elements=["instrument_id", "calc_date", "organization_id"],
                set_={
                    "peer_strategy_label": upsert.excluded.peer_strategy_label,
                    "peer_sharpe_pctl": upsert.excluded.peer_sharpe_pctl,
                    "peer_sortino_pctl": upsert.excluded.peer_sortino_pctl,
                    "peer_return_pctl": upsert.excluded.peer_return_pctl,
                    "peer_drawdown_pctl": upsert.excluded.peer_drawdown_pctl,
                    "peer_count": upsert.excluded.peer_count,
                },
            )
            await db.execute(upsert)
            updated += 1

        await db.commit()
        logger.info(
            "global_risk_metrics.peer_group_computed",
            strategy=strategy,
            peer_count=peer_count,
        )

    return updated


def _pctl(value: float, arr: np.ndarray) -> float:
    """Percentile rank (0-100, higher = better)."""
    import numpy as np
    if len(arr) == 0:
        return 50.0
    return round(float(np.sum(arr <= value)) / len(arr) * 100, 2)


#: Phase 2 Session B commit 7 — total ELITE cohort size.
ELITE_TOTAL_COUNT = 300

#: Max acceptable deviation between ``sum(target_counts)`` and
#: ``ELITE_TOTAL_COUNT`` after rounding. At the current canonical
#: moderate profile (0.50 / 0.33 / 0.12 / 0.05) the sum is exactly
#: 300, but a future re-seed with fractional weights may round up
#: or down by 1–2 funds per bucket. Beyond this tolerance the
#: worker logs a warning.
ELITE_ROUNDING_TOLERANCE = 3

#: Sprint 2 TAA — mapping from regime to the boolean column name on
#: fund_risk_metrics. RISK_ON uses the existing ``elite_flag`` for
#: backward compatibility. The 3 new columns were added in migration
#: 0129. Keys are hardcoded constants (safe for f-string SQL).
REGIME_ELITE_COLUMN: dict[str, str] = {
    "RISK_ON": "elite_flag",
    "RISK_OFF": "elite_risk_off",
    "INFLATION": "elite_inflation",
    "CRISIS": "elite_crisis",
}

#: Per-regime target counts derived from TAA band centers (plan §5.2).
#: Computed as round(300 * center) per asset class. These are used by
#: the ELITE ranking pass when computing regime-specific sets.
REGIME_ELITE_TARGETS: dict[str, dict[str, int]] = {
    "RISK_ON":    {"equity": 156, "fixed_income": 90,  "alternatives": 36, "cash": 18},
    "RISK_OFF":   {"equity": 114, "fixed_income": 108, "alternatives": 39, "cash": 39},
    "INFLATION":  {"equity": 126, "fixed_income": 75,  "alternatives": 66, "cash": 33},
    "CRISIS":     {"equity": 75,  "fixed_income": 105, "alternatives": 45, "cash": 75},
}


async def _compute_elite_for_regime(
    db: AsyncSession,
    calc_date: date,
    column_name: str,
    target_counts: dict[str, int],
) -> int:
    """Compute ELITE ranking for a single regime into the specified column.

    Clears the column for all global rows, then ranks by manager_score
    within each asset_class bucket and sets the top N funds to True.

    For the RISK_ON regime (column_name='elite_flag'), also updates
    ``elite_rank_within_strategy`` and ``elite_target_count_per_strategy``
    for screener UX compatibility.

    Args:
        column_name: One of the 4 values from REGIME_ELITE_COLUMN
            (hardcoded constants, safe for f-string SQL).
        target_counts: Per-asset-class target counts (sum ~= 300).

    Returns:
        Total number of funds marked True in this column.
    """
    # Pass A — clear stale flags for this column
    if column_name == "elite_flag":
        # RISK_ON: also clear rank and target_count (screener UX columns)
        await db.execute(
            text(
                """
                UPDATE fund_risk_metrics
                SET elite_flag = false,
                    elite_rank_within_strategy = NULL,
                    elite_target_count_per_strategy = NULL
                WHERE calc_date = :calc_date
                  AND organization_id IS NULL
                """,
            ),
            {"calc_date": calc_date},
        )
    else:
        await db.execute(
            text(
                f"""
                UPDATE fund_risk_metrics
                SET {column_name} = false
                WHERE calc_date = :calc_date
                  AND organization_id IS NULL
                """,
            ),
            {"calc_date": calc_date},
        )

    # Pass B — per bucket, rank by manager_score and mark top N
    for asset_class, target_count in target_counts.items():
        if column_name == "elite_flag":
            # RISK_ON: also record rank + target_count for screener
            target_count_query = text(
                """
                UPDATE fund_risk_metrics frm
                SET elite_target_count_per_strategy = :target_count
                FROM instruments_universe iu
                WHERE frm.instrument_id = iu.instrument_id
                  AND frm.calc_date = :calc_date
                  AND frm.organization_id IS NULL
                  AND iu.is_active = true
                  AND iu.asset_class = :asset_class
                  AND (frm.elite_target_count_per_strategy IS NULL
                       OR frm.elite_target_count_per_strategy <> :target_count)
                """,
            )
            await db.execute(
                target_count_query,
                {
                    "calc_date": calc_date,
                    "asset_class": asset_class,
                    "target_count": target_count,
                },
            )

            rank_query = text(
                """
                WITH ranked AS (
                    SELECT
                        frm.instrument_id,
                        ROW_NUMBER() OVER (
                            ORDER BY frm.manager_score DESC NULLS LAST
                        ) AS rnk
                    FROM fund_risk_metrics frm
                    JOIN instruments_universe iu
                      ON iu.instrument_id = frm.instrument_id
                    WHERE frm.calc_date = :calc_date
                      AND frm.organization_id IS NULL
                      AND frm.manager_score IS NOT NULL
                      AND iu.is_active = true
                      AND iu.asset_class = :asset_class
                )
                UPDATE fund_risk_metrics frm
                SET elite_flag = true,
                    elite_rank_within_strategy = ranked.rnk::smallint,
                    elite_target_count_per_strategy = :target_count
                FROM ranked
                WHERE frm.instrument_id = ranked.instrument_id
                  AND frm.calc_date = :calc_date
                  AND frm.organization_id IS NULL
                  AND ranked.rnk <= :target_count
                """,
            )
        else:
            # Non-RISK_ON regimes: only set the boolean flag
            rank_query = text(
                f"""
                WITH ranked AS (
                    SELECT
                        frm.instrument_id,
                        ROW_NUMBER() OVER (
                            ORDER BY frm.manager_score DESC NULLS LAST
                        ) AS rnk
                    FROM fund_risk_metrics frm
                    JOIN instruments_universe iu
                      ON iu.instrument_id = frm.instrument_id
                    WHERE frm.calc_date = :calc_date
                      AND frm.organization_id IS NULL
                      AND frm.manager_score IS NOT NULL
                      AND iu.is_active = true
                      AND iu.asset_class = :asset_class
                )
                UPDATE fund_risk_metrics frm
                SET {column_name} = true
                FROM ranked
                WHERE frm.instrument_id = ranked.instrument_id
                  AND frm.calc_date = :calc_date
                  AND frm.organization_id IS NULL
                  AND ranked.rnk <= :target_count
                """,
            )

        await db.execute(
            rank_query,
            {
                "calc_date": calc_date,
                "asset_class": asset_class,
                "target_count": target_count,
            },
        )
        logger.info(
            "elite_ranking.strategy_processed",
            regime_column=column_name,
            asset_class=asset_class,
            target_count=target_count,
        )

    # Read back actual count for this column
    total_result = await db.execute(
        text(
            f"""
            SELECT COUNT(*)
            FROM fund_risk_metrics
            WHERE calc_date = :calc_date
              AND organization_id IS NULL
              AND {column_name} = true
            """,
        ),
        {"calc_date": calc_date},
    )
    return int(total_result.scalar_one() or 0)


async def _compute_elite_ranking(
    db: AsyncSession,
    calc_date: date,
) -> tuple[int, dict[str, int]]:
    """ELITE ranking pass — computes 4 regime-specific ELITE sets.

    For each regime (RISK_ON, RISK_OFF, INFLATION, CRISIS), marks the
    top N funds per asset_class in the corresponding boolean column:
    - RISK_ON  → ``elite_flag`` (backward compatible, also sets rank/target)
    - RISK_OFF → ``elite_risk_off``
    - INFLATION → ``elite_inflation``
    - CRISIS   → ``elite_crisis``

    RISK_ON target counts come from the canonical moderate profile via
    ``get_global_default_strategy_weights``. Other regime targets come
    from ``REGIME_ELITE_TARGETS`` (derived from TAA band centers, plan §5.2).

    Returns:
        ``(total_risk_on_elite, risk_on_targets)`` for backward
        compatibility with existing callers.
    """
    from vertical_engines.wealth.elite_ranking.allocation_source import (
        compute_target_counts,
        get_global_default_strategy_weights,
    )

    # RISK_ON: use canonical moderate profile (backward compatible)
    weights = await get_global_default_strategy_weights(db)
    risk_on_targets = compute_target_counts(weights, total_elite=ELITE_TOTAL_COUNT)

    rounding_deviation = abs(sum(risk_on_targets.values()) - ELITE_TOTAL_COUNT)
    if rounding_deviation > ELITE_ROUNDING_TOLERANCE:
        logger.warning(
            "elite_ranking.rounding_deviation_exceeds_tolerance",
            sum_targets=sum(risk_on_targets.values()),
            expected=ELITE_TOTAL_COUNT,
            tolerance=ELITE_ROUNDING_TOLERANCE,
            per_strategy=risk_on_targets,
        )

    per_regime_totals: dict[str, int] = {}

    for regime, column_name in REGIME_ELITE_COLUMN.items():
        if regime == "RISK_ON":
            targets = risk_on_targets
        else:
            targets = REGIME_ELITE_TARGETS[regime]

        total = await _compute_elite_for_regime(db, calc_date, column_name, targets)
        per_regime_totals[regime] = total
        logger.info(
            "elite_ranking.regime_set_done",
            regime=regime,
            column=column_name,
            total_elite=total,
            targets=targets,
        )

    await db.commit()

    # Return RISK_ON total for backward compatibility
    return per_regime_totals.get("RISK_ON", 0), risk_on_targets


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Risk calculation worker")
    parser.add_argument("--org-id", type=uuid.UUID, help="Compute org-scoped metrics for a specific tenant.")
    args = parser.parse_args()

    if args.org_id:
        asyncio.run(run_risk_calc(args.org_id))
    else:
        asyncio.run(run_global_risk_metrics())

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
from app.domains.wealth.models.macro import MacroData
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.risk import FundRiskMetrics
from quant_engine.cvar_service import compute_cvar_from_returns
from quant_engine.drift_service import DtwDriftResult, DtwDriftStatus, compute_dtw_drift_batch
from quant_engine.garch_service import fit_garch
from quant_engine.talib_momentum_service import (
    compute_flow_momentum,
    compute_momentum_signals_talib,
    normalize_flow_momentum,
)

logger = structlog.get_logger()

RISK_CALC_LOCK_ID = 900_007
TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE_FALLBACK = 0.04  # Fallback ~4% if FRED DFF unavailable

MIN_STRESS_OBS = 10  # Minimum stress observations for conditional CVaR


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
    """Compute annualized Sharpe ratio."""
    if len(returns) < days:
        return None
    window = returns[-days:]
    excess = window - risk_free_rate / TRADING_DAYS_PER_YEAR
    vol = float(np.std(excess, ddof=1))
    if vol == 0:
        return None
    return float(np.mean(excess) / vol * np.sqrt(TRADING_DAYS_PER_YEAR))


def _compute_sortino(returns: np.ndarray, days: int, risk_free_rate: float = 0.04) -> float | None:
    """Compute annualized Sortino ratio."""
    if len(returns) < days:
        return None
    window = returns[-days:]
    excess = window - risk_free_rate / TRADING_DAYS_PER_YEAR
    downside = excess[excess < 0]
    if len(downside) == 0:
        return None
    downside_vol = float(np.std(downside, ddof=1))
    if downside_vol == 0:
        return None
    return float(np.mean(excess) / downside_vol * np.sqrt(TRADING_DAYS_PER_YEAR))


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
) -> dict[str, list[float]]:
    """Batch-fetch NAV daily returns for all fund IDs in at most 2 queries.

    Replaces the per-fund SELECT inside compute_fund_risk_metrics, reducing
    N queries to at most 2 (one per return_type group). Returns a dict mapping
    fund_id (str) → ordered list of float returns (ascending by nav_date),
    filtered to the resolved return_type for each fund.
    """
    if not fund_ids:
        return {}

    # Partition fund_ids by their resolved return_type
    log_fund_ids = [fid for fid in fund_ids if return_type_by_fund.get(str(fid), "log") == "log"]
    arith_fund_ids = [fid for fid in fund_ids if return_type_by_fund.get(str(fid), "log") == "arithmetic"]

    raw_by_fund: dict[str, list[float]] = {}

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
            raw_by_fund.setdefault(fid, []).append(float(return_1d))

    return raw_by_fund


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
            raw_by_fund.setdefault(fid, []).append((nav_date, float(return_1d)))

    return raw_by_fund


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
        slope = compute_flow_momentum(close, aum)
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
    fund: Instrument,
    returns_raw: list[float],
    as_of_date: date,
    risk_free_rate: float = 0.04,
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

    # Volatility
    metrics["volatility_1y"] = _round_or_none(_compute_volatility(returns, 252))

    # Drawdown
    metrics["max_drawdown_1y"] = _round_or_none(_compute_max_drawdown(returns, 252))
    metrics["max_drawdown_3y"] = _round_or_none(_compute_max_drawdown(returns, 3 * 252))

    # Sharpe & Sortino (using live risk-free rate from FRED DFF)
    metrics["sharpe_1y"] = _round_or_none(_compute_sharpe(returns, 252, risk_free_rate))
    metrics["sharpe_3y"] = _round_or_none(_compute_sharpe(returns, 3 * 252, risk_free_rate))
    metrics["sortino_1y"] = _round_or_none(_compute_sortino(returns, 252, risk_free_rate))

    # GARCH(1,1) conditional volatility (BL-11)
    garch_result = fit_garch(returns)
    if garch_result is not None and garch_result.converged and garch_result.volatility_garch is not None:
        metrics["volatility_garch"] = round(garch_result.volatility_garch, 6)
    else:
        # Fallback: use sample volatility (already computed above)
        metrics["volatility_garch"] = metrics.get("volatility_1y")

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
    nav_map = await _batch_fetch_nav_returns(db, [fund.instrument_id], return_type_map, start_date, as_of_date)
    raw = nav_map.get(str(fund.instrument_id), [])
    return _compute_metrics_from_returns(fund, raw, as_of_date, risk_free_rate)


def _round_or_none(value: float | None, decimals: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, decimals)


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

    # Group rows by fund_id; track which return types are present per fund
    raw_by_fund: dict[str, dict[str, list[float]]] = {}
    for row_instrument_id, return_1d, return_type in rows:
        fid = str(row_instrument_id)
        if fid not in raw_by_fund:
            raw_by_fund[fid] = {"log": [], "arithmetic": []}
        rtype = return_type if return_type in ("log", "arithmetic") else "arithmetic"
        raw_by_fund[fid][rtype].append(float(return_1d))

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
) -> dict[str, DtwDriftResult]:
    """Compute DTW drift scores for all funds, grouped by block.

    Each fund is compared against the equal-weight average of all fund returns
    in the same block. If a block has fewer than 2 funds, returns a degraded result.

    Returns a dict mapping fund_id (str) → DtwDriftResult.
    """
    # Group funds by block_id
    block_funds: dict[str | None, list[tuple[Instrument, dict]]] = defaultdict(list)
    for fund, metrics in funds_with_metrics:
        block_funds[fund.block_id].append((fund, metrics))

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

            stmt = select(Instrument).where(
                Instrument.is_active == True,
                Instrument.ticker.is_not(None),
                Instrument.instrument_type == "fund",
            )
            result = await db.execute(stmt)
            funds = result.scalars().all()

            logger.info("Funds to process", count=len(funds))

            eval_date = as_of_date or date.today()
            # 3 years + 30-day buffer — same window used in compute_fund_risk_metrics
            start_date = eval_date - timedelta(days=3 * 365 + 30)

            all_fund_ids = [fund.instrument_id for fund in funds]

            # Batch 1: resolve return_type for every fund — 1 query instead of N
            return_type_by_fund = await _batch_resolve_return_types(
                db, all_fund_ids, start_date, eval_date,
            )
            logger.info("Return types resolved", n_funds=len(return_type_by_fund))

            # Batch 2: fetch all NAV returns — at most 2 queries instead of N
            nav_returns_by_fund = await _batch_fetch_nav_returns(
                db, all_fund_ids, return_type_by_fund, start_date, eval_date,
            )
            logger.info("NAV returns batch-fetched", n_funds=len(nav_returns_by_fund))

            # Pass 1: compute standard risk metrics from pre-fetched data — no DB queries in loop
            computed: list[tuple[Instrument, dict]] = []
            for fund in funds:
                fid_str = str(fund.instrument_id)
                returns_raw = nav_returns_by_fund.get(fid_str, [])
                metrics = _compute_metrics_from_returns(fund, returns_raw, eval_date, risk_free_rate=rfr)
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

            # Pass 2: compute DTW drift scores per block (reuses DB session, no extra query per fund)
            logger.info("Computing DTW drift scores", n_funds=len(computed))
            dtw_scores = await _compute_block_dtw_scores(db, computed, eval_date)
            logger.info("DTW drift scores computed", n_scores=len(dtw_scores))

            # Pass 3: upsert metrics + dtw_drift_score (all in one transaction)
            try:
                for fund, metrics in computed:
                    fid_str = str(fund.instrument_id)
                    dtw_result = dtw_scores.get(
                        fid_str,
                        DtwDriftResult(score=None, status=DtwDriftStatus.degraded, reason="fund not in dtw_scores"),
                    )
                    # Use score_or_default so DB column always gets a float,
                    # but the decision to fall back is explicit, not silent.
                    metrics["dtw_drift_score"] = round(dtw_result.score_or_default(0.0), 6)
                    if not dtw_result.is_usable:
                        logger.warning(
                            "dtw_drift_degraded",
                            fund_id=fid_str,
                            ticker=fund.ticker,
                            status=dtw_result.status.value,
                            reason=dtw_result.reason,
                        )

                    metrics["organization_id"] = org_id
                    upsert = pg_insert(FundRiskMetrics).values(**metrics)
                    upsert = upsert.on_conflict_do_update(
                        index_elements=["instrument_id", "calc_date"],
                        set_={k: upsert.excluded[k] for k in metrics if k not in ("instrument_id", "calc_date", "organization_id")},
                    )
                    await db.execute(upsert)
                    results[fund.ticker or str(fund.instrument_id)] = 1
                    logger.info("Risk metrics staged", ticker=fund.ticker, dtw_drift=metrics["dtw_drift_score"])

                # Single commit for the entire batch — atomic and WAL-efficient
                await db.commit()
                logger.info("Risk metrics batch committed", funds_staged=len(computed))

                await _write_risk_cache(org_id, eval_date, computed)
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


if __name__ == "__main__":
    asyncio.run(run_risk_calc())

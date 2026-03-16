"""Track-record computation — backtest, live NAV, stress.

Delegates heavy computation to quant_engine services.
All functions are sync (callers use asyncio.to_thread).
Config as parameter.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.wealth.models.nav import NavTimeseries
from vertical_engines.wealth.model_portfolio.models import (
    BacktestResult,
    FoldMetrics,
    LiveNAV,
    ScenarioResult,
    StressResult,
)
from vertical_engines.wealth.model_portfolio.stress_scenarios import SCENARIOS

logger = structlog.get_logger()

# Minimum trading days for a fund to be included in backtest
MIN_HISTORY_DAYS = 252


def compute_backtest(
    db: Session,
    *,
    fund_ids: list[uuid.UUID],
    weights: list[float],
    lookback_days: int = 1260,
    portfolio_id: uuid.UUID | None = None,
    config: dict[str, Any] | None = None,
) -> BacktestResult:
    """Run walk-forward backtest on a portfolio composition.

    Fetches aligned returns matrix from DB and delegates to
    quant_engine.backtest_service.walk_forward_backtest().

    Parameters
    ----------
    db : Session
        Database session.
    fund_ids : list[uuid.UUID]
        Fund IDs in the portfolio.
    weights : list[float]
        Corresponding portfolio weights.
    lookback_days : int
        How far back to look (default: 1260 = ~5 years).
    portfolio_id : uuid.UUID | None
        Optional portfolio ID for result tracking.
    config : dict | None
        Optional backtest config overrides.
    """
    if not fund_ids:
        return BacktestResult(portfolio_id=portfolio_id, lookback_days=lookback_days)

    # Fetch returns matrix
    returns_matrix, valid_funds, valid_weights, youngest_start = _fetch_returns_matrix(
        db, fund_ids, weights, lookback_days
    )

    if returns_matrix is None or returns_matrix.shape[0] < MIN_HISTORY_DAYS:
        logger.warning(
            "backtest_insufficient_history",
            portfolio_id=str(portfolio_id),
            available_days=returns_matrix.shape[0] if returns_matrix is not None else 0,
        )
        return BacktestResult(
            portfolio_id=portfolio_id,
            lookback_days=lookback_days,
            youngest_fund_start=youngest_start,
        )

    from quant_engine.backtest_service import walk_forward_backtest

    bt_config = config or {}
    result = walk_forward_backtest(
        returns_matrix,
        valid_weights,
        n_splits=bt_config.get("n_splits", 5),
        gap=bt_config.get("gap", 2),
        min_train_size=bt_config.get("min_train_size", MIN_HISTORY_DAYS),
        test_size=bt_config.get("test_size", 63),
    )

    folds = [
        FoldMetrics(
            fold=f["fold"],
            sharpe=f.get("sharpe"),
            cvar_95=f.get("cvar_95"),
            max_drawdown=f.get("max_drawdown"),
            n_obs=f.get("n_obs", 0),
        )
        for f in result.get("folds", [])
    ]

    return BacktestResult(
        portfolio_id=portfolio_id,
        lookback_days=lookback_days,
        folds=folds,
        mean_sharpe=result.get("mean_sharpe"),
        std_sharpe=result.get("std_sharpe"),
        positive_folds=result.get("positive_folds", 0),
        total_folds=len(folds),
        youngest_fund_start=youngest_start,
    )


def compute_live_nav(
    db: Session,
    *,
    portfolio_id: uuid.UUID,
    fund_ids: list[uuid.UUID],
    weights: list[float],
    as_of: date,
    previous_nav: float = 1000.0,
) -> LiveNAV:
    """Compute live NAV for a portfolio at a given date.

    Formula: NAV_t = NAV_{t-1} * (1 + sum(w_i * r_i_t))
    """
    if not fund_ids:
        return LiveNAV(portfolio_id=portfolio_id, as_of=as_of, nav=previous_nav)

    # Fetch returns for the as_of date
    result = db.execute(
        select(NavTimeseries.instrument_id, NavTimeseries.return_1d).where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date == as_of,
        )
    )
    returns_by_fund = {row.instrument_id: float(row.return_1d) for row in result if row.return_1d is not None}

    # Weighted portfolio return
    portfolio_return = 0.0
    for fid, w in zip(fund_ids, weights, strict=False):
        r = returns_by_fund.get(fid, 0.0)
        portfolio_return += w * r

    nav = previous_nav * (1.0 + portfolio_return)

    return LiveNAV(
        portfolio_id=portfolio_id,
        as_of=as_of,
        nav=round(nav, 4),
        daily_return=round(portfolio_return, 6),
        inception_nav=1000.0,
    )


def compute_stress(
    db: Session,
    *,
    fund_ids: list[uuid.UUID],
    weights: list[float],
    portfolio_id: uuid.UUID | None = None,
    config: dict[str, Any] | None = None,
) -> StressResult:
    """Replay portfolio through historical stress scenarios.

    Optimization: fetches the full returns matrix once (widest window)
    and slices in memory per scenario to avoid redundant DB round-trips.
    """
    if not fund_ids:
        return StressResult(portfolio_id=portfolio_id)

    # Find widest window needed across all scenarios
    earliest = min(s.start_date for s in SCENARIOS)
    latest = max(s.end_date for s in SCENARIOS)

    # Fetch all NAV data in one query
    result = db.execute(
        select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav_date,
            NavTimeseries.return_1d,
        )
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= earliest,
            NavTimeseries.nav_date <= latest,
            NavTimeseries.return_1d.isnot(None),
        )
        .order_by(NavTimeseries.nav_date)
    )

    # Build returns lookup: {(fund_id, date): return}
    returns_lookup: dict[tuple[uuid.UUID, date], float] = {}
    all_dates: set[date] = set()
    for row in result:
        returns_lookup[(row.instrument_id, row.nav_date)] = float(row.return_1d)
        all_dates.add(row.nav_date)

    scenario_results: list[ScenarioResult] = []

    for scenario in SCENARIOS:
        # Filter dates for this scenario window
        scenario_dates = sorted(
            d for d in all_dates if scenario.start_date <= d <= scenario.end_date
        )

        if len(scenario_dates) < 5:
            logger.warning(
                "stress_insufficient_data",
                scenario=scenario.name,
                available_days=len(scenario_dates),
            )
            continue

        # Compute weighted portfolio returns for the scenario window
        portfolio_returns = []
        for d in scenario_dates:
            day_return = 0.0
            for fid, w in zip(fund_ids, weights, strict=False):
                r = returns_lookup.get((fid, d), 0.0)
                day_return += w * r
            portfolio_returns.append(day_return)

        pr = np.array(portfolio_returns)
        cum = np.cumprod(1.0 + pr)
        total_return = float(cum[-1] - 1.0)

        # Max drawdown
        running_max = np.maximum.accumulate(cum)
        drawdowns = (cum - running_max) / np.where(running_max > 0, running_max, 1.0)
        max_dd = float(np.min(drawdowns))

        scenario_results.append(
            ScenarioResult(
                name=scenario.name,
                start_date=scenario.start_date,
                end_date=scenario.end_date,
                portfolio_return=round(total_return, 6),
                max_drawdown=round(max_dd, 6),
            )
        )

    return StressResult(portfolio_id=portfolio_id, scenarios=scenario_results)


def _fetch_returns_matrix(
    db: Session,
    fund_ids: list[uuid.UUID],
    weights: list[float],
    lookback_days: int,
) -> tuple[np.ndarray | None, list[uuid.UUID], list[float], date | None]:
    """Fetch aligned returns matrix for the given funds.

    Returns (matrix, valid_fund_ids, valid_weights, youngest_fund_start).
    Funds with < MIN_HISTORY_DAYS are excluded.
    """
    from datetime import timedelta

    cutoff = date.today() - timedelta(days=lookback_days)

    # Fetch all NAV data in one query
    result = db.execute(
        select(
            NavTimeseries.instrument_id,
            NavTimeseries.nav_date,
            NavTimeseries.return_1d,
        )
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= cutoff,
            NavTimeseries.return_1d.isnot(None),
        )
        .order_by(NavTimeseries.nav_date)
    )

    # Group by fund
    fund_returns: dict[uuid.UUID, dict[date, float]] = {}
    all_dates: set[date] = set()
    for row in result:
        fund_returns.setdefault(row.instrument_id, {})[row.nav_date] = float(row.return_1d)
        all_dates.add(row.nav_date)

    if not all_dates:
        return None, [], [], None

    sorted_dates = sorted(all_dates)

    # Filter funds with enough history
    valid_funds: list[uuid.UUID] = []
    valid_weights: list[float] = []
    youngest_start: date | None = None

    for fid, w in zip(fund_ids, weights, strict=False):
        fund_dates = fund_returns.get(fid, {})
        if len(fund_dates) >= MIN_HISTORY_DAYS:
            valid_funds.append(fid)
            valid_weights.append(w)
            fund_start = min(fund_dates.keys())
            if youngest_start is None or fund_start > youngest_start:
                youngest_start = fund_start

    if not valid_funds:
        return None, [], [], youngest_start

    # Re-normalize weights
    w_total = sum(valid_weights)
    if w_total > 0:
        valid_weights = [w / w_total for w in valid_weights]

    # Cap dates at youngest fund start
    if youngest_start:
        sorted_dates = [d for d in sorted_dates if d >= youngest_start]

    # Build matrix (dates x funds)
    matrix = np.zeros((len(sorted_dates), len(valid_funds)))
    for j, fid in enumerate(valid_funds):
        fd = fund_returns.get(fid, {})
        for i, d in enumerate(sorted_dates):
            matrix[i, j] = fd.get(d, 0.0)

    return matrix, valid_funds, valid_weights, youngest_start

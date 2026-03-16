"""Walk-forward backtesting service using TimeSeriesSplit.

Pure computation functions — no I/O.
DB fetch helper fetches a pre-aligned returns matrix from nav_timeseries.

Requires optional dependency group [timeseries]:
    pip install netz-wealth-os[timeseries]

Design decisions:
- gap=2: daily-dealing liquid funds (T+1 NAV + 1 buffer day). Use gap=21 for
  monthly-dealing or illiquid funds.
- test_size=63: fixed 3-month test periods for consistent per-fold Sharpe comparability.
- Expanding window (TimeSeriesSplit default): superior to rolling for covariance stability.
- Report fold consistency (N/5 positive Sharpe), NOT p-values. See Finucane (2004).

Note: imports Fund, NavTimeseries from app.domains.wealth — wealth-vertical-specific dependency.
"""

from collections import defaultdict
from datetime import date, timedelta

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.nav import NavTimeseries

logger = structlog.get_logger()


def _compute_fold_metrics(
    returns: np.ndarray,
    risk_free_daily: float = 0.04 / 252,
) -> dict:
    """Compute Sharpe, CVaR(95%), and max drawdown for a single fold's return series."""
    if len(returns) == 0:
        return {"sharpe": None, "cvar_95": None, "max_drawdown": None, "n_obs": 0}

    mean_r = float(np.mean(returns))
    std_r = float(np.std(returns, ddof=1))
    sharpe = float((mean_r - risk_free_daily) / std_r * np.sqrt(252)) if std_r > 0 else None

    sorted_r = np.sort(returns)
    cutoff = max(int(np.floor(len(sorted_r) * 0.05)), 1)
    cvar_95 = -float(np.mean(sorted_r[:cutoff]))

    cum = np.cumprod(1.0 + returns)
    running_max = np.maximum.accumulate(cum)
    drawdowns = (cum - running_max) / np.where(running_max > 0, running_max, 1.0)
    max_drawdown = float(np.min(drawdowns))

    return {
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "cvar_95": round(cvar_95, 6),
        "max_drawdown": round(max_drawdown, 6),
        "n_obs": len(returns),
    }


def walk_forward_backtest(
    returns_matrix: np.ndarray,
    weights: list[float],
    n_splits: int = 5,
    gap: int = 2,
    min_train_size: int = 252,
    test_size: int = 63,
) -> dict:
    """Walk-forward backtest with expanding window using TimeSeriesSplit.

    Args:
        returns_matrix: T×N matrix of daily returns (log or arithmetic).
        weights: Portfolio weight for each of N assets (must sum to ~1.0).
        n_splits: Number of CV folds (default: 5).
        gap: Trading days between train end and test start.
             gap=2 for daily-dealing liquid funds (T+1 NAV + 1 buffer).
             gap=21 for monthly-dealing or illiquid funds.
        min_train_size: Minimum observations in a training fold.
        test_size: Fixed test fold size in trading days (63 ≈ 3 months).

    Returns:
        dict with folds, mean_sharpe, std_sharpe, positive_folds, n_splits_computed.
    """
    try:
        from sklearn.model_selection import TimeSeriesSplit
    except ImportError:
        raise RuntimeError(
            "scikit-learn not installed. Install with: pip install netz-wealth-os[timeseries]"
        )

    w = np.array(weights, dtype=float)
    portfolio_returns = returns_matrix @ w  # (T,) weighted portfolio

    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap, test_size=test_size)
    folds = []

    for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(portfolio_returns)):
        if len(train_idx) < min_train_size:
            logger.debug("Fold skipped: train too small", fold=fold_idx, train_size=len(train_idx))
            continue

        test_returns = portfolio_returns[test_idx]
        metrics = _compute_fold_metrics(test_returns)
        metrics["fold"] = fold_idx
        metrics["train_size"] = len(train_idx)
        metrics["test_size_actual"] = len(test_idx)
        metrics["train_end_idx"] = int(train_idx[-1])
        metrics["test_start_idx"] = int(test_idx[0])
        folds.append(metrics)

    if not folds:
        return {
            "folds": [],
            "mean_sharpe": None,
            "std_sharpe": None,
            "positive_folds": 0,
            "n_splits_computed": 0,
        }

    sharpes = [f["sharpe"] for f in folds if f["sharpe"] is not None]
    mean_sharpe = float(np.mean(sharpes)) if sharpes else None
    std_sharpe = float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else None
    positive_folds = sum(1 for s in sharpes if s is not None and s > 0)

    return {
        "folds": folds,
        "mean_sharpe": round(mean_sharpe, 4) if mean_sharpe is not None else None,
        "std_sharpe": round(std_sharpe, 4) if std_sharpe is not None else None,
        "positive_folds": positive_folds,
        "n_splits_computed": len(folds),
    }


async def fetch_returns_matrix(
    db: AsyncSession,
    block_ids: list[str],
    lookback_days: int = 756,  # ~3 trading years
) -> tuple[np.ndarray, list[str], list[float]]:
    """Fetch aligned daily returns matrix for walk-forward backtesting.

    Returns:
        (returns_matrix, fund_ids, equal_weights)
        - returns_matrix: T×N float64 array (only dates where all funds have data)
        - fund_ids: list of fund UUID strings (columns)
        - equal_weights: 1/N equal-weight portfolio weights

    Raises:
        ValueError: If <2 blocks have data or <120 aligned dates.
    """
    start_date = date.today() - timedelta(days=int(lookback_days * 1.5))  # buffer for holidays

    # One representative fund per block (same selection as optimizer_service)
    funds_stmt = (
        select(Fund)
        .where(Fund.block_id.in_(block_ids), Fund.is_active == True, Fund.ticker.is_not(None))
        .distinct(Fund.block_id)
        .order_by(Fund.block_id, Fund.name)
    )
    funds_result = await db.execute(funds_stmt)
    block_funds = {f.block_id: f for f in funds_result.scalars().all()}

    if not block_funds:
        raise ValueError("No active funds found for the requested blocks")

    available = [bid for bid in block_ids if bid in block_funds]
    fund_uuids = [block_funds[bid].fund_id for bid in available]
    fund_ids = [str(block_funds[bid].fund_id) for bid in available]

    if len(fund_ids) < 2:
        raise ValueError(f"Need ≥2 blocks with data, found {len(fund_ids)}")

    ret_stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id.in_(fund_uuids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.return_1d.is_not(None),
        )
        .order_by(NavTimeseries.nav_date)
    )
    ret_result = await db.execute(ret_stmt)

    # Group by fund, then find common dates
    grouped: dict[str, dict[str, float]] = defaultdict(dict)
    for fid, nav_date, ret in ret_result.all():
        grouped[str(fid)][str(nav_date)] = float(ret)

    date_sets = [set(grouped[fid].keys()) for fid in fund_ids]
    common_dates = sorted(set.intersection(*date_sets) if date_sets else set())

    if len(common_dates) < 120:
        raise ValueError(
            f"Insufficient aligned return data: {len(common_dates)} common dates (need ≥120)"
        )

    T, N = len(common_dates), len(fund_ids)
    matrix = np.zeros((T, N), dtype=np.float64)
    for j, fid in enumerate(fund_ids):
        for i, d in enumerate(common_dates):
            matrix[i, j] = grouped[fid][d]

    equal_weights = [1.0 / N] * N
    return matrix, fund_ids, equal_weights

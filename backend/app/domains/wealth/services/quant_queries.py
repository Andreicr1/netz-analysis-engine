"""Wealth-layer data access for quant_engine services.

Functions in this module were extracted from quant_engine/ to enforce
vertical isolation: quant_engine/ must not import app.domains.wealth.

Each function here queries wealth ORM models and passes plain data to
pure computation functions in quant_engine/.

Import-linter enforces the boundary: quant_engine → app.domains.wealth
is forbidden; app.domains.wealth → quant_engine is allowed.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quant_engine.drift_service import DriftReport
    from quant_engine.peer_comparison_service import PeerComparison, PeerRank
    from quant_engine.rebalance_service import CascadeResult

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.domains.wealth.models.allocation import StrategicAllocation, TacticalPosition
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from app.domains.wealth.models.rebalance import RebalanceEvent
from app.domains.wealth.models.risk import FundRiskMetrics

logger = structlog.get_logger()


# ── Backtest queries ─────────────────────────────────────────────────


async def fetch_returns_matrix(
    db: AsyncSession,
    block_ids: list[str],
    lookback_days: int = 756,
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
    start_date = date.today() - timedelta(days=int(lookback_days * 1.5))

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

    grouped: dict[str, dict[str, float]] = defaultdict(dict)
    for fid, nav_date, ret in ret_result.all():
        grouped[str(fid)][str(nav_date)] = float(ret)

    date_sets = [set(grouped[fid].keys()) for fid in fund_ids]
    common_dates = sorted(set.intersection(*date_sets) if date_sets else set())

    if len(common_dates) < 120:
        raise ValueError(
            f"Insufficient aligned return data: {len(common_dates)} common dates (need ≥120)",
        )

    T, N = len(common_dates), len(fund_ids)
    matrix = np.zeros((T, N), dtype=np.float64)
    for j, fid in enumerate(fund_ids):
        for i, d in enumerate(common_dates):
            matrix[i, j] = grouped[fid][d]

    equal_weights = [1.0 / N] * N
    return matrix, fund_ids, equal_weights


# ── Optimizer queries ────────────────────────────────────────────────

TRADING_DAYS_PER_YEAR = 252
MIN_OBSERVATIONS = 120


async def compute_inputs_from_nav(
    db: AsyncSession,
    block_ids: list[str],
    lookback_days: int = TRADING_DAYS_PER_YEAR,
    as_of_date: date | None = None,
) -> tuple[np.ndarray, dict[str, float]]:
    """Compute covariance matrix and expected returns from NAV data.

    Returns:
        (annualized_cov_matrix, expected_returns_dict)

    Raises:
        ValueError: If insufficient aligned data (<120 trading days).

    """
    if as_of_date is None:
        as_of_date = date.today()

    start_date = as_of_date - timedelta(days=int(lookback_days * 1.5))

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

    available_blocks = [bid for bid in block_ids if bid in block_funds]
    if len(available_blocks) < 2:
        raise ValueError(f"Need at least 2 blocks with data, found {len(available_blocks)}")

    fund_ids = [block_funds[bid].fund_id for bid in available_blocks]
    ret_stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= as_of_date,
            NavTimeseries.return_1d.is_not(None),
        )
        .order_by(NavTimeseries.nav_date)
    )
    ret_result = await db.execute(ret_stmt)

    fund_returns: dict[str, dict[date, float]] = defaultdict(dict)
    for instrument_id, nav_date, return_1d in ret_result.all():
        fund_returns[str(instrument_id)][nav_date] = float(return_1d)

    fund_id_strs = [str(block_funds[bid].fund_id) for bid in available_blocks]
    all_date_sets = [set(fund_returns[fid].keys()) for fid in fund_id_strs]

    if not all_date_sets:
        raise ValueError("No return data found for any block")

    common_dates = sorted(set.intersection(*all_date_sets))

    if len(common_dates) < MIN_OBSERVATIONS:
        raise ValueError(
            f"Insufficient aligned data: {len(common_dates)} trading days "
            f"(minimum: {MIN_OBSERVATIONS}). Some funds may have sparse history.",
        )

    returns_matrix = np.array([
        [fund_returns[fid][d] for fid in fund_id_strs]
        for d in common_dates
    ])

    daily_cov = np.cov(returns_matrix, rowvar=False)
    annual_cov = daily_cov * TRADING_DAYS_PER_YEAR

    eigenvalues = np.linalg.eigvalsh(annual_cov)
    if eigenvalues.min() < -1e-10:
        eigvals, eigvecs = np.linalg.eigh(annual_cov)
        eigvals = np.maximum(eigvals, 1e-10)
        annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T
        logger.info("Covariance matrix adjusted for PSD", min_eigenvalue=float(eigenvalues.min()))

    daily_means = returns_matrix.mean(axis=0)
    annual_returns = daily_means * TRADING_DAYS_PER_YEAR
    expected_returns = {bid: float(annual_returns[i]) for i, bid in enumerate(available_blocks)}

    logger.info(
        "Computed covariance and expected returns",
        blocks=len(available_blocks),
        observations=len(common_dates),
        lookback_days=lookback_days,
    )

    return annual_cov, expected_returns


def _apply_ledoit_wolf(returns_matrix: np.ndarray) -> np.ndarray:
    """Apply Ledoit-Wolf shrinkage to compute covariance from returns.

    Input: (T x N) returns matrix. Returns: (N x N) shrinkage covariance.
    """
    from sklearn.covariance import LedoitWolf

    lw = LedoitWolf()
    lw.fit(returns_matrix)
    result: np.ndarray = lw.covariance_
    return result


async def _fetch_returns_by_type(
    db: AsyncSession,
    instrument_ids: list[uuid.UUID],
    start_date: date,
    as_of_date: date,
) -> tuple[dict[str, dict[date, float]], str]:
    """Fetch returns filtered by return_type: prefer 'log', fallback 'arithmetic'.

    Never mixes return types in the same result. Returns (fund_returns_dict, used_type).
    """
    for return_type in ("log", "arithmetic"):
        ret_stmt = (
            select(NavTimeseries.instrument_id, NavTimeseries.nav_date, NavTimeseries.return_1d)
            .where(
                NavTimeseries.instrument_id.in_(instrument_ids),
                NavTimeseries.nav_date >= start_date,
                NavTimeseries.nav_date <= as_of_date,
                NavTimeseries.return_1d.is_not(None),
                NavTimeseries.return_type == return_type,
            )
            .order_by(NavTimeseries.nav_date)
        )
        ret_result = await db.execute(ret_stmt)

        fund_returns: dict[str, dict[date, float]] = defaultdict(dict)
        for instrument_id, nav_date, return_1d in ret_result.all():
            fund_returns[str(instrument_id)][nav_date] = float(return_1d)

        n_funds_with_data = sum(
            1 for iid in instrument_ids if str(iid) in fund_returns
        )
        if n_funds_with_data >= 2:
            if return_type == "arithmetic":
                logger.warning(
                    "fund_returns_fallback_to_arithmetic",
                    reason="insufficient funds with log returns",
                    n_funds=n_funds_with_data,
                )
            return fund_returns, return_type

    # Neither type yielded ≥2 funds — return empty (caller raises ValueError)
    logger.warning("no_return_type_yielded_sufficient_funds")
    return defaultdict(dict), "none"


async def fetch_bl_views_for_portfolio(
    db: AsyncSession,
    portfolio_id: uuid.UUID,
    fund_ids: list[str],
) -> list[dict[str, Any]]:
    """Fetch active IC views and map instrument_ids to fund index positions.

    Returns list of dicts ready for black_litterman_service.compute_bl_returns().
    """
    from app.domains.wealth.models.portfolio_view import PortfolioView

    today = date.today()
    stmt = (
        select(PortfolioView)
        .where(
            PortfolioView.portfolio_id == portfolio_id,
            PortfolioView.effective_from <= today,
        )
        .where(
            (PortfolioView.effective_to.is_(None))
            | (PortfolioView.effective_to >= today),
        )
    )
    result = await db.execute(stmt)
    views = result.scalars().all()

    if not views:
        return []

    # Build instrument_id -> index map
    id_to_idx = {fid: i for i, fid in enumerate(fund_ids)}

    bl_views: list[dict[str, Any]] = []
    for v in views:
        if v.view_type == "absolute":
            asset_id = str(v.asset_instrument_id) if v.asset_instrument_id else None
            if asset_id and asset_id in id_to_idx:
                bl_views.append({
                    "type": "absolute",
                    "asset_idx": id_to_idx[asset_id],
                    "Q": float(v.expected_return),
                    "confidence": float(v.confidence),
                })
        elif v.view_type == "relative":
            long_id = str(v.asset_instrument_id) if v.asset_instrument_id else None
            short_id = str(v.peer_instrument_id) if v.peer_instrument_id else None
            if long_id and short_id and long_id in id_to_idx and short_id in id_to_idx:
                bl_views.append({
                    "type": "relative",
                    "long_idx": id_to_idx[long_id],
                    "short_idx": id_to_idx[short_id],
                    "Q": float(v.expected_return),
                    "confidence": float(v.confidence),
                })

    return bl_views


async def fetch_strategic_weights_for_funds(
    db: AsyncSession,
    fund_ids: list[str],
    profile: str,
) -> np.ndarray:
    """Fetch strategic allocation targets as market proxy weights for BL.

    Maps block-level targets to individual fund weights (equal-split within block).
    Returns (N,) array aligned with fund_ids.
    """
    from app.domains.wealth.models.instrument_org import InstrumentOrg

    today = date.today()
    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to > today),
        )
    )
    alloc_result = await db.execute(alloc_stmt)
    block_targets = {a.block_id: float(a.target_weight) for a in alloc_result.scalars().all()}

    # Map fund_ids to blocks via InstrumentOrg
    fund_uuids = [uuid.UUID(fid) for fid in fund_ids]
    inst_stmt = (
        select(InstrumentOrg.instrument_id, InstrumentOrg.block_id)
        .where(InstrumentOrg.instrument_id.in_(fund_uuids))
    )
    inst_result = await db.execute(inst_stmt)
    fund_block_map = {str(r.instrument_id): r.block_id for r in inst_result.all()}

    # Count funds per block for equal-split
    block_fund_counts: dict[str, int] = defaultdict(int)
    for fid in fund_ids:
        blk = fund_block_map.get(fid)
        if blk and blk in block_targets:
            block_fund_counts[blk] += 1

    # Assign weights
    w_market = np.zeros(len(fund_ids))
    for i, fid in enumerate(fund_ids):
        blk = fund_block_map.get(fid)
        if blk and blk in block_targets and block_fund_counts[blk] > 0:
            w_market[i] = block_targets[blk] / block_fund_counts[blk]

    # Normalize
    total = w_market.sum()
    if total > 0:
        w_market /= total

    return w_market


async def compute_fund_level_inputs(
    db: AsyncSession,
    instrument_ids: list[uuid.UUID],
    lookback_days: int = TRADING_DAYS_PER_YEAR,
    as_of_date: date | None = None,
    config: dict[str, Any] | None = None,
    portfolio_id: uuid.UUID | None = None,
    profile: str | None = None,
) -> tuple[np.ndarray, dict[str, float], list[str], np.ndarray, np.ndarray]:
    """Compute covariance matrix, expected returns, and higher moments for individual funds.

    Unlike compute_inputs_from_nav (one proxy per block), this computes the
    full NxN matrix across all provided instrument_ids so the optimizer can
    allocate at fund level with inter-fund diversification.

    Returns:
        (annualized_cov_matrix, expected_returns_dict, ordered_fund_ids, skewness, excess_kurtosis)
        - cov_matrix: NxN where N = number of funds with sufficient data
        - expected_returns_dict: {instrument_id_str: annualized_return}
        - ordered_fund_ids: fund IDs matching matrix rows/cols
        - skewness: (N,) array of per-fund return skewness
        - excess_kurtosis: (N,) array of per-fund excess kurtosis (Fisher)

    Raises:
        ValueError: If <2 funds have aligned data or <120 trading days.

    """
    from scipy import stats as sp_stats

    if as_of_date is None:
        as_of_date = date.today()

    start_date = as_of_date - timedelta(days=int(lookback_days * 1.5))

    # ── BL-3: Filter by return_type (log preferred, arithmetic fallback) ──
    fund_returns, used_return_type = await _fetch_returns_by_type(
        db, instrument_ids, start_date, as_of_date,
    )

    # Keep only funds with data
    available_ids = [str(iid) for iid in instrument_ids if str(iid) in fund_returns]
    if len(available_ids) < 2:
        raise ValueError(f"Need ≥2 funds with NAV data, found {len(available_ids)}")

    all_date_sets = [set(fund_returns[fid].keys()) for fid in available_ids]
    common_dates = sorted(set.intersection(*all_date_sets))

    if len(common_dates) < MIN_OBSERVATIONS:
        raise ValueError(
            f"Insufficient aligned fund data: {len(common_dates)} trading days "
            f"(minimum: {MIN_OBSERVATIONS})",
        )

    returns_matrix = np.array([
        [fund_returns[fid][d] for fid in available_ids]
        for d in common_dates
    ])

    # ── BL-2: Ledoit-Wolf shrinkage (configurable) ──
    apply_shrinkage = True
    if config:
        apply_shrinkage = config.get("optimizer", {}).get("apply_shrinkage", True)

    if apply_shrinkage:
        daily_cov = _apply_ledoit_wolf(returns_matrix)
    else:
        daily_cov = np.cov(returns_matrix, rowvar=False)

    annual_cov = daily_cov * TRADING_DAYS_PER_YEAR

    # PSD adjustment
    eigenvalues = np.linalg.eigvalsh(annual_cov)
    if eigenvalues.min() < -1e-10:
        eigvals, eigvecs = np.linalg.eigh(annual_cov)
        eigvals = np.maximum(eigvals, 1e-10)
        annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T

    daily_means = returns_matrix.mean(axis=0)
    annual_returns = daily_means * TRADING_DAYS_PER_YEAR
    expected_returns = {fid: float(annual_returns[i]) for i, fid in enumerate(available_ids)}

    # ── BL-1: Compute higher moments for Cornish-Fisher CVaR ──
    skewness = sp_stats.skew(returns_matrix, axis=0)              # (N,)
    excess_kurtosis = sp_stats.kurtosis(returns_matrix, axis=0,
                                        fisher=True)              # (N,)

    # ── BL-5: Regime-conditioned covariance ──
    regime_cov = _maybe_regime_condition_cov(db, returns_matrix, annual_cov, config)
    if regime_cov is not None:
        annual_cov = regime_cov

    # ── BL-4: Black-Litterman posterior returns ──
    use_bl = False
    if portfolio_id is not None and profile is not None:
        bl_views = await fetch_bl_views_for_portfolio(db, portfolio_id, available_ids)
        if bl_views:
            w_market = await fetch_strategic_weights_for_funds(db, available_ids, profile)
            from quant_engine.black_litterman_service import compute_bl_returns

            bl_config = config or {}
            risk_aversion = bl_config.get("bl", {}).get("risk_aversion", 2.5)
            tau = bl_config.get("bl", {}).get("tau", 0.05)

            mu_bl = compute_bl_returns(
                sigma=annual_cov,
                w_market=w_market,
                views=bl_views,
                risk_aversion=risk_aversion,
                tau=tau,
            )
            expected_returns = {fid: float(mu_bl[i]) for i, fid in enumerate(available_ids)}
            use_bl = True

    # ── Fee adjustment: subtract expense ratio from expected returns ──
    fee_adjusted = False
    if config and config.get("fee_adjustment", {}).get("enabled"):
        from app.domains.wealth.models.instrument import Instrument

        inst_rows = (
            await db.execute(
                select(Instrument).where(
                    Instrument.instrument_id.in_(instrument_ids),
                ),
            )
        ).scalars().all()
        instruments_by_id = {str(i.instrument_id): i for i in inst_rows}
        for fid in available_ids:
            inst = instruments_by_id.get(fid)
            if inst and inst.attributes:
                er = inst.attributes.get("expense_ratio_pct")
                if er is not None:
                    expected_returns[fid] -= float(er) / 100.0  # pct → decimal
                    fee_adjusted = True

    logger.info(
        "fund_level_inputs_computed",
        n_funds=len(available_ids),
        observations=len(common_dates),
        return_type=used_return_type,
        apply_shrinkage=apply_shrinkage,
        use_bl=use_bl,
        regime_conditioned=regime_cov is not None,
        fee_adjusted=fee_adjusted,
    )

    return annual_cov, expected_returns, available_ids, skewness, excess_kurtosis


# ── Regime-conditioned covariance (BL-5) ─────────────────────────────


def compute_regime_conditioned_cov(
    returns_matrix: np.ndarray,
    regime_probs: np.ndarray,
    short_window: int = 63,
    long_window: int = 252,
) -> np.ndarray:
    """Compute regime-adaptive covariance matrix.

    Strategy:
    - If current regime (mean of last 21d regime_probs) > 0.6 (stress):
        use short window (63d) with stress-weighted observations
    - Otherwise: use long window (252d) standard estimation

    Returns annualized (N x N) covariance.
    """
    T = returns_matrix.shape[0]

    # Current regime: average P(high_vol) over last 21 days
    lookback = min(21, len(regime_probs))
    current_regime_prob = float(np.mean(regime_probs[-lookback:]))

    if current_regime_prob > 0.6:
        # Stress regime: use short window, weight by regime probability
        window = min(short_window, T)
        recent_returns = returns_matrix[-window:]
        recent_probs = regime_probs[-window:] if len(regime_probs) >= window else regime_probs

        # Stress-weight: upweight high-vol observations
        weights = np.array(recent_probs[-len(recent_returns):], dtype=np.float64)
        weights = weights / weights.sum() * len(weights)  # normalize to preserve scale

        # Weighted covariance
        mean_r = np.average(recent_returns, axis=0, weights=weights)
        demeaned = recent_returns - mean_r
        weighted_cov = (demeaned.T * weights) @ demeaned / (weights.sum() - 1)
        annual_cov: np.ndarray = weighted_cov * TRADING_DAYS_PER_YEAR
    else:
        # Normal regime: use long window
        window = min(long_window, T)
        recent_returns = returns_matrix[-window:]
        daily_cov: np.ndarray = np.cov(recent_returns, rowvar=False)
        annual_cov = daily_cov * TRADING_DAYS_PER_YEAR

    # PSD adjustment
    eigenvalues = np.linalg.eigvalsh(annual_cov)
    if eigenvalues.min() < -1e-10:
        eigvals, eigvecs = np.linalg.eigh(annual_cov)
        eigvals = np.maximum(eigvals, 1e-10)
        annual_cov = eigvecs @ np.diag(eigvals) @ eigvecs.T

    return annual_cov


def _maybe_regime_condition_cov(
    db: AsyncSession,
    returns_matrix: np.ndarray,
    fallback_cov: np.ndarray,
    config: dict[str, Any] | None,
) -> np.ndarray | None:
    """Try to apply regime-conditioned covariance. Returns None if regime data unavailable.

    This is a sync helper that reads the latest regime_probs from the most recent
    PortfolioSnapshot. If no regime data exists (regime_fit never ran), returns None
    and the caller uses standard covariance (silent fallback per spec).
    """
    # We need regime_probs from the latest snapshot. Since this function is called
    # from an async context but the data is already in memory from portfolio_eval,
    # we query the DB synchronously via the async session's sync_session.
    # However, since we're already in async context, we'll do a lightweight check.

    # Instead of querying here (which would require await), we check if regime_probs
    # were passed through config. The caller (model_portfolios.py) will inject them.
    if not config:
        return None

    regime_probs_list = config.get("_regime_probs")
    if not regime_probs_list:
        return None

    regime_probs = np.array(regime_probs_list, dtype=np.float64)
    if len(regime_probs) < 21:
        return None

    # Trim regime_probs to match returns_matrix length
    T = returns_matrix.shape[0]
    if len(regime_probs) > T:
        regime_probs = regime_probs[-T:]
    elif len(regime_probs) < T:
        # Pad with neutral (0.5) for missing early observations
        pad = np.full(T - len(regime_probs), 0.5)
        regime_probs = np.concatenate([pad, regime_probs])

    return compute_regime_conditioned_cov(returns_matrix, regime_probs)


# ── Drift queries ────────────────────────────────────────────────────


async def compute_drift(
    db: AsyncSession,
    profile: str,
    as_of_date: date | None = None,
    min_trade_threshold: float = 0.005,
    config: dict[str, Any] | None = None,
) -> DriftReport:
    """Compute drift for all blocks in a profile.

    Queries PortfolioSnapshot, StrategicAllocation, TacticalPosition,
    then delegates to pure compute_block_drifts().

    Returns a DriftReport.
    """
    from quant_engine.drift_service import (
        DriftReport,
        compute_block_drifts,
        resolve_drift_thresholds,
    )

    if as_of_date is None:
        as_of_date = date.today()

    maintenance_trigger, urgent_trigger = resolve_drift_thresholds(config)

    snap_stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    snap_result = await db.execute(snap_stmt)
    snapshot = snap_result.scalar_one_or_none()

    if snapshot is None or not snapshot.weights:
        return DriftReport(
            profile=profile,
            as_of_date=as_of_date,
            blocks=[],
            max_drift_pct=0.0,
            overall_status="ok",
            rebalance_recommended=False,
            estimated_turnover=0.0,
            maintenance_trigger=maintenance_trigger,
            urgent_trigger=urgent_trigger,
        )

    current_weights: dict[str, float] = {
        k: float(v) for k, v in snapshot.weights.items()
    }

    alloc_stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= as_of_date,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= as_of_date),
        )
    )
    alloc_result = await db.execute(alloc_stmt)
    strategic = {a.block_id: float(a.target_weight) for a in alloc_result.scalars().all()}

    tact_stmt = (
        select(TacticalPosition)
        .where(
            TacticalPosition.profile == profile,
            TacticalPosition.valid_from <= as_of_date,
        )
        .where(
            (TacticalPosition.valid_to.is_(None))
            | (TacticalPosition.valid_to >= as_of_date),
        )
    )
    tact_result = await db.execute(tact_stmt)
    tactical = {t.block_id: float(t.overweight) for t in tact_result.scalars().all()}

    target_weights: dict[str, float] = {}
    for block_id in set(strategic.keys()) | set(tactical.keys()):
        target_weights[block_id] = strategic.get(block_id, 0.0) + tactical.get(block_id, 0.0)

    drifts = compute_block_drifts(
        current_weights, target_weights,
        maintenance_trigger, urgent_trigger,
    )

    max_abs = max((abs(d.absolute_drift) for d in drifts), default=0.0)

    if any(d.status == "urgent" for d in drifts):
        overall = "urgent"
    elif any(d.status == "maintenance" for d in drifts):
        overall = "maintenance"
    else:
        overall = "ok"

    meaningful_trades = [
        abs(d.absolute_drift) for d in drifts
        if abs(d.absolute_drift) >= min_trade_threshold
    ]
    turnover = sum(meaningful_trades) / 2

    rebalance_recommended = overall != "ok" and turnover >= 0.01

    return DriftReport(
        profile=profile,
        as_of_date=as_of_date,
        blocks=[d for d in drifts if d.status != "ok"],
        max_drift_pct=round(max_abs, 6),
        overall_status=overall,
        rebalance_recommended=rebalance_recommended,
        estimated_turnover=round(turnover, 6),
        maintenance_trigger=maintenance_trigger,
        urgent_trigger=urgent_trigger,
    )


# ── Peer comparison queries ──────────────────────────────────────────


def compare(
    db: Session,
    *,
    fund_id: uuid.UUID,
    block_id: str,
    aum_min: Decimal | None = None,
    aum_max: Decimal | None = None,
    config: dict[str, Any] | None = None,
) -> PeerComparison:
    """Rank a fund against its peers within a block.

    Queries Fund and FundRiskMetrics, then ranks by manager_score.
    Returns a PeerComparison.
    """
    from quant_engine.peer_comparison_service import PeerComparison, PeerRank

    stmt = select(Fund).where(
        Fund.block_id == block_id,
        Fund.is_active.is_(True),
        Fund.approval_status == "approved",
    )

    if aum_min is not None:
        stmt = stmt.where(Fund.aum_usd >= aum_min)
    if aum_max is not None:
        stmt = stmt.where(Fund.aum_usd <= aum_max)

    funds_result = db.execute(stmt)
    funds = list(funds_result.scalars().all())

    if not funds:
        return PeerComparison(target_fund_id=fund_id, block_id=block_id)

    peer_fund_ids = [f.fund_id for f in funds]

    risk_stmt = (
        select(FundRiskMetrics)
        .where(FundRiskMetrics.instrument_id.in_(peer_fund_ids))
        .order_by(FundRiskMetrics.instrument_id, FundRiskMetrics.calc_date.desc())
        .distinct(FundRiskMetrics.instrument_id)
    )
    risk_result = db.execute(risk_stmt)
    risk_map = {r.instrument_id: r for r in risk_result.scalars().all()}

    scored: list[dict[str, Any]] = []
    for f in funds:
        risk = risk_map.get(f.fund_id)
        scored.append({
            "fund_id": f.fund_id,
            "fund_name": f.name,
            "manager_score": float(risk.manager_score) if risk and risk.manager_score else None,
            "sharpe_1y": float(risk.sharpe_1y) if risk and risk.sharpe_1y else None,
            "return_1y": float(risk.return_1y) if risk and risk.return_1y else None,
        })

    scored.sort(key=lambda s: float(s["manager_score"]) if s["manager_score"] is not None else -999.0, reverse=True)

    peers: list[PeerRank] = []
    target_rank = None
    for i, s in enumerate(scored, 1):
        peer = PeerRank(
            fund_id=uuid.UUID(str(s["fund_id"])),
            fund_name=str(s["fund_name"]),
            manager_score=float(s["manager_score"]) if s["manager_score"] is not None else None,
            sharpe_1y=float(s["sharpe_1y"]) if s["sharpe_1y"] is not None else None,
            return_1y=float(s["return_1y"]) if s["return_1y"] is not None else None,
            rank=i,
            peer_count=len(scored),
        )
        peers.append(peer)
        if s["fund_id"] == fund_id:
            target_rank = i

    return PeerComparison(
        target_fund_id=fund_id,
        block_id=block_id,
        peers=peers,
        target_rank=target_rank,
        peer_count=len(scored),
    )


# ── Rebalance queries ────────────────────────────────────────────────


async def create_system_rebalance_event(
    db: AsyncSession,
    profile: str,
    event_type: str,
    trigger_reason: str,
    weights_before: dict[str, Any] | None = None,
    cvar_before: float | None = None,
    actor_source: str = "system",
) -> RebalanceEvent:
    """Create a rebalance event generated by the system (not manual)."""
    event = RebalanceEvent(
        profile=profile,
        event_date=date.today(),
        event_type=event_type,
        trigger_reason=trigger_reason,
        weights_before=weights_before,
        cvar_before=Decimal(str(round(cvar_before, 6))) if cvar_before is not None else None,
        status="pending",
        actor_source=actor_source,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    logger.info(
        "System rebalance event created",
        event_id=str(event.event_id),
        profile=profile,
        event_type=event_type,
        actor_source=actor_source,
    )
    return event


async def process_cascade(
    db: AsyncSession,
    profile: str,
    trigger_status: str,
    cvar_utilized_pct: float,
    consecutive_breach_days: int,
    cvar_current: float | None = None,
    current_weights: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> CascadeResult:
    """Process the rebalance cascade for a profile.

    Queries PortfolioSnapshot for previous status, delegates to
    determine_cascade_action(), creates event if needed.

    Returns a CascadeResult.
    """
    from quant_engine.rebalance_service import CascadeResult, determine_cascade_action

    stmt = (
        select(PortfolioSnapshot.trigger_status)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    previous_status = result.scalar_one_or_none()

    event_type, reason = determine_cascade_action(
        trigger_status,
        previous_status,
        cvar_utilized_pct,
        consecutive_breach_days,
        profile,
        config=config,
    )

    if event_type is None:
        return CascadeResult(
            previous_status=previous_status or "ok",
            new_status=trigger_status,
            event_created=False,
        )

    event = await create_system_rebalance_event(
        db,
        profile=profile,
        event_type=event_type,
        trigger_reason=reason or "",
        weights_before=current_weights,
        cvar_before=cvar_current,
        actor_source="system",
    )

    return CascadeResult(
        previous_status=previous_status or "ok",
        new_status=trigger_status,
        event_created=True,
        event_id=event.event_id,
        reason=reason,
    )

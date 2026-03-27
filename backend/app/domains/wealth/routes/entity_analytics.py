"""Entity Analytics Vitrine — polymorphic analytics for funds and model portfolios.

Orchestrates nav_reader (I/O) → quant_engine (math) for the 5 institutional
metric groups: Risk Statistics, Drawdown, Capture, Rolling Returns, Distribution.

INVARIANT: Never imports NavTimeseries directly.  All NAV access goes through
nav_reader.fetch_nav_series / fetch_returns_only.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import numpy as np
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from scipy import stats as sp_stats
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.benchmark_nav import BenchmarkNav
from app.domains.wealth.models.block import AllocationBlock
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.schemas.entity_analytics import (
    CaptureRatios,
    DrawdownAnalysis,
    DrawdownPeriod,
    EntityAnalyticsResponse,
    ReturnDistribution,
    RiskStatistics,
    RollingReturns,
    RollingSeries,
)
from app.domains.wealth.services.nav_reader import (
    NavRow,
    fetch_nav_series,
    is_model_portfolio,
)
from quant_engine.cvar_service import compute_cvar_from_returns
from quant_engine.drawdown_service import analyze_drawdowns
from quant_engine.portfolio_metrics_service import aggregate as compute_metrics
from quant_engine.rolling_service import compute_rolling_returns

logger = structlog.get_logger()

router = APIRouter(prefix="/analytics")

_WINDOW_DAYS = {"3m": 63, "6m": 126, "1y": 252, "3y": 756, "5y": 1260}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_entity_meta(
    db: AsyncSession, entity_id: uuid.UUID,
) -> tuple[str, str, str | None]:
    """Return (entity_type, entity_name, block_id | None)."""
    if await is_model_portfolio(db, entity_id):
        row = await db.execute(
            select(ModelPortfolio.display_name).where(ModelPortfolio.id == entity_id),
        )
        name = row.scalar_one_or_none() or "Model Portfolio"
        return "model_portfolio", name, None

    row = await db.execute(
        select(Instrument.name, Instrument.block_id).where(
            Instrument.instrument_id == entity_id,
        ),
    )
    inst = row.one_or_none()
    if inst is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found")
    return "instrument", inst[0], inst[1]


async def _resolve_benchmark_returns(
    db: AsyncSession,
    entity_block_id: str | None,
    benchmark_id: uuid.UUID | None,
    start_date: date,
    end_date: date,
) -> tuple[dict[date, float], str, str]:
    """Resolve benchmark daily returns.

    Returns (date→return map, source label, benchmark display label).
    Priority: param > block > SPY fallback.
    """
    # (1) Explicit benchmark_id via query string → polymorphic nav_reader
    if benchmark_id is not None:
        rows = await fetch_nav_series(db, benchmark_id, start_date, end_date)
        if rows:
            bm_map = {r.nav_date: r.daily_return for r in rows if r.daily_return is not None}
            if bm_map:
                return bm_map, "param", str(benchmark_id)

    # (2) Entity's AllocationBlock benchmark_ticker → benchmark_nav hypertable
    if entity_block_id:
        block_row = await db.execute(
            select(AllocationBlock.benchmark_ticker, AllocationBlock.display_name).where(
                AllocationBlock.block_id == entity_block_id,
            ),
        )
        block = block_row.one_or_none()
        if block and block[0]:
            bm_map = await _fetch_benchmark_nav_returns(
                db, entity_block_id, start_date, end_date,
            )
            if bm_map:
                return bm_map, "block", block[0]

    # (3) SPY fallback — find any block with benchmark_ticker='SPY'
    spy_row = await db.execute(
        select(AllocationBlock.block_id).where(
            AllocationBlock.benchmark_ticker == "SPY",
        ).limit(1),
    )
    spy_block = spy_row.scalar_one_or_none()
    if spy_block:
        bm_map = await _fetch_benchmark_nav_returns(db, spy_block, start_date, end_date)
        if bm_map:
            return bm_map, "spy_fallback", "SPY"

    return {}, "spy_fallback", "SPY"


async def _fetch_benchmark_nav_returns(
    db: AsyncSession, block_id: str, start_date: date, end_date: date,
) -> dict[date, float]:
    """Fetch daily returns from benchmark_nav hypertable."""
    stmt = (
        select(BenchmarkNav.nav_date, BenchmarkNav.return_1d)
        .where(
            BenchmarkNav.block_id == block_id,
            BenchmarkNav.nav_date >= start_date,
            BenchmarkNav.nav_date <= end_date,
            BenchmarkNav.return_1d.isnot(None),
        )
        .order_by(BenchmarkNav.nav_date)
    )
    result = await db.execute(stmt)
    return {row[0]: float(row[1]) for row in result.all()}


def _compute_capture_ratios(
    entity_monthly: list[float],
    benchmark_monthly: list[float],
) -> CaptureRatios:
    """Compute up/down capture and number ratios from aligned monthly returns."""
    if not entity_monthly or not benchmark_monthly:
        return CaptureRatios()

    e = np.array(entity_monthly)
    b = np.array(benchmark_monthly)

    up_mask = b > 0
    down_mask = b < 0

    up_periods = int(np.sum(up_mask))
    down_periods = int(np.sum(down_mask))

    up_capture = None
    down_capture = None
    up_number = None
    down_number = None

    if up_periods > 0:
        bm_up_mean = float(np.mean(b[up_mask]))
        if abs(bm_up_mean) > 1e-12:
            up_capture = round(float(np.mean(e[up_mask]) / bm_up_mean * 100), 2)
        # Up number ratio: % of up-benchmark months where entity also positive
        up_number = round(float(np.sum(e[up_mask] > 0) / up_periods * 100), 2)

    if down_periods > 0:
        bm_down_mean = float(np.mean(b[down_mask]))
        if abs(bm_down_mean) > 1e-12:
            down_capture = round(float(np.mean(e[down_mask]) / bm_down_mean * 100), 2)
        # Down number ratio: % of down-benchmark months where entity outperformed benchmark
        down_number = round(float(np.sum(e[down_mask] > b[down_mask]) / down_periods * 100), 2)

    return CaptureRatios(
        up_capture=up_capture,
        down_capture=down_capture,
        up_number_ratio=up_number,
        down_number_ratio=down_number,
        up_periods=up_periods,
        down_periods=down_periods,
    )


def _monthly_returns_from_daily(
    dates: list[date], returns: list[float],
) -> tuple[list[str], list[float]]:
    """Aggregate daily returns to monthly geometric returns.

    Returns (month_labels, monthly_returns).
    """
    if not dates:
        return [], []

    monthly: dict[str, float] = {}
    for d, r in zip(dates, returns, strict=True):
        key = d.strftime("%Y-%m")
        monthly[key] = (1 + monthly.get(key, 0.0)) * (1 + r) - 1 if key in monthly else r

    labels = sorted(monthly.keys())
    values = [round(monthly[k], 8) for k in labels]
    return labels, values


def _compute_distribution(returns: np.ndarray) -> ReturnDistribution:
    """Compute return distribution metrics: histogram, moments, tail risk."""
    if len(returns) < 10:
        return ReturnDistribution(bin_edges=[], bin_counts=[])

    # Histogram with Freedman-Diaconis bins
    counts, edges = np.histogram(returns, bins="fd")
    mean = float(np.mean(returns))
    std = float(np.std(returns, ddof=1))
    skew = float(sp_stats.skew(returns))
    kurt = float(sp_stats.kurtosis(returns))  # excess kurtosis

    cvar, var = compute_cvar_from_returns(returns, confidence=0.95)

    return ReturnDistribution(
        bin_edges=[round(float(e), 8) for e in edges],
        bin_counts=[int(c) for c in counts],
        mean=round(mean, 8),
        std=round(std, 8),
        skewness=round(skew, 4),
        kurtosis=round(kurt, 4),
        var_95=round(var, 6),
        cvar_95=round(cvar, 6),
    )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.get(
    "/entity/{entity_id}",
    response_model=EntityAnalyticsResponse,
    summary="Entity analytics vitrine (polymorphic)",
    description=(
        "Comprehensive analytics for any entity (fund or model portfolio). "
        "Returns 5 institutional metric groups: Risk Statistics, Drawdown, "
        "Up/Down Capture, Rolling Returns, Return Distribution. "
        "Entity type is auto-detected via nav_reader polymorphism."
    ),
)
async def get_entity_analytics(
    entity_id: uuid.UUID,
    window: str = Query("1y", pattern="^(3m|6m|1y|3y|5y)$", description="Lookback window"),
    benchmark_id: uuid.UUID | None = Query(None, description="Explicit benchmark entity UUID"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> EntityAnalyticsResponse:
    # ── Resolve entity metadata ──────────────────────────────────────
    entity_type, entity_name, block_id = await _resolve_entity_meta(db, entity_id)

    # ── Fetch NAV series via nav_reader ──────────────────────────────
    today = date.today()
    lookback_days = _WINDOW_DAYS.get(window, 252)
    start_date = today - timedelta(days=int(lookback_days * 1.5))  # buffer for trading days

    nav_rows: list[NavRow] = await fetch_nav_series(db, entity_id, start_date, today)

    if len(nav_rows) < 10:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Insufficient NAV data: {len(nav_rows)} rows (need ≥ 10)",
        )

    # Trim to exact trading-day window
    if len(nav_rows) > lookback_days:
        nav_rows = nav_rows[-lookback_days:]

    dates_list = [r.nav_date for r in nav_rows]
    navs = np.array([r.nav for r in nav_rows])
    returns_raw = [r.daily_return for r in nav_rows]
    # Fill None returns with 0.0 for array computation
    returns = np.array([r if r is not None else 0.0 for r in returns_raw])

    # Date strings for time-series output
    date_strs = [d.isoformat() for d in dates_list]

    # ── Resolve benchmark ────────────────────────────────────────────
    bm_map, bm_source, bm_label = await _resolve_benchmark_returns(
        db, block_id, benchmark_id, dates_list[0], dates_list[-1],
    )

    # Align benchmark returns to entity dates
    bm_aligned: np.ndarray | None = None
    if bm_map:
        bm_vals = [bm_map.get(d, 0.0) for d in dates_list]
        bm_aligned = np.array(bm_vals)

    # ── 1. Risk Statistics ───────────────────────────────────────────
    metrics = compute_metrics(
        portfolio_returns=returns,
        benchmark_returns=bm_aligned,
    )

    # Calmar = annualized_return / |max_drawdown|
    calmar = None
    if metrics.max_drawdown and abs(metrics.max_drawdown) > 1e-10 and metrics.annualized_return is not None:
        calmar = round(metrics.annualized_return / abs(metrics.max_drawdown), 4)

    # Alpha & Beta (vs benchmark)
    alpha = None
    beta = None
    tracking_error = None
    if bm_aligned is not None and len(bm_aligned) > 30:
        slope, intercept, _, _, _ = sp_stats.linregress(bm_aligned, returns)
        beta = round(float(slope), 4)
        alpha = round(float(intercept * 252), 4)  # annualized
        excess = returns - bm_aligned
        tracking_error = round(float(np.std(excess, ddof=1) * np.sqrt(252)), 4)

    risk_stats = RiskStatistics(
        annualized_return=metrics.annualized_return,
        annualized_volatility=metrics.annualized_volatility,
        sharpe_ratio=metrics.sharpe_ratio,
        sortino_ratio=metrics.sortino_ratio,
        calmar_ratio=calmar,
        max_drawdown=metrics.max_drawdown,
        alpha=alpha,
        beta=beta,
        tracking_error=tracking_error,
        information_ratio=metrics.information_ratio,
        n_observations=metrics.n_observations,
    )

    # ── 2. Drawdown Analysis ─────────────────────────────────────────
    dd_result = analyze_drawdowns(navs, dates_list)

    drawdown = DrawdownAnalysis(
        dates=date_strs,
        values=[round(float(v), 6) for v in dd_result.series],
        max_drawdown=dd_result.max_drawdown,
        current_drawdown=dd_result.current_drawdown,
        longest_duration_days=dd_result.longest_duration_days,
        avg_recovery_days=dd_result.avg_recovery_days,
        worst_periods=[
            DrawdownPeriod(
                start_date=p.start_date.isoformat(),
                trough_date=p.trough_date.isoformat(),
                end_date=p.end_date.isoformat() if p.end_date else None,
                depth=p.depth,
                duration_days=p.duration_days,
                recovery_days=p.recovery_days,
            )
            for p in dd_result.periods
        ],
    )

    # ── 3. Capture Ratios ────────────────────────────────────────────
    # Aggregate to monthly for capture calculation
    entity_labels, entity_monthly = _monthly_returns_from_daily(
        dates_list, returns.tolist(),
    )
    capture = CaptureRatios(benchmark_source=bm_source, benchmark_label=bm_label)
    if bm_map and entity_monthly:
        # Build aligned monthly benchmark
        bm_daily_for_monthly = [bm_map.get(d, 0.0) for d in dates_list]
        _, bm_monthly = _monthly_returns_from_daily(dates_list, bm_daily_for_monthly)
        # Align by min length
        n_months = min(len(entity_monthly), len(bm_monthly))
        if n_months >= 3:
            capture = _compute_capture_ratios(
                entity_monthly[-n_months:], bm_monthly[-n_months:],
            )
            capture.benchmark_source = bm_source
            capture.benchmark_label = bm_label

    # ── 4. Rolling Returns ───────────────────────────────────────────
    rolling_results = compute_rolling_returns(date_strs, returns)
    rolling = RollingReturns(
        series=[
            RollingSeries(
                window_label=r.window_label,
                dates=r.dates,
                values=r.values,
            )
            for r in rolling_results
        ],
    )

    # ── 5. Return Distribution ───────────────────────────────────────
    # Filter out zero-padding returns for distribution accuracy
    valid_returns = np.array([r for r in returns_raw if r is not None])
    distribution = _compute_distribution(valid_returns if len(valid_returns) > 10 else returns)

    return EntityAnalyticsResponse(
        entity_id=entity_id,
        entity_type=entity_type,
        entity_name=entity_name,
        as_of_date=today,
        window=window,
        risk_statistics=risk_stats,
        drawdown=drawdown,
        capture=capture,
        rolling_returns=rolling,
        distribution=distribution,
    )

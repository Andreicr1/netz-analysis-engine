"""Entity Analytics Vitrine — polymorphic analytics for funds and model portfolios.

Orchestrates nav_reader (I/O) → quant_engine (math) for the 7 institutional
metric groups: Risk Statistics, Drawdown, Capture, Rolling Returns, Distribution,
Return Statistics (eVestment I-V), Tail Risk (eVestment VII).

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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.benchmark_nav import BenchmarkNav
from app.domains.wealth.models.block import AllocationBlock
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.models.model_portfolio import ModelPortfolio
from app.domains.wealth.schemas.analytics import ActiveShareResponse
from app.domains.wealth.schemas.entity_analytics import (
    CaptureRatios,
    DrawdownAnalysis,
    DrawdownPeriod,
    EntityAnalyticsResponse,
    ReturnDistribution,
    ReturnStatistics,
    RiskStatistics,
    RollingReturns,
    RollingSeries,
    TailRiskMetrics,
)
from app.domains.wealth.services.holdings_exploder import (
    fetch_portfolio_holdings_exploded,
)
from app.domains.wealth.services.nav_reader import (
    NavRow,
    fetch_nav_series,
    is_model_portfolio,
)
from app.shared.models import SecFundClass, SecNportHolding
from quant_engine.active_share_service import compute_active_share
from quant_engine.cvar_service import compute_cvar_from_returns
from quant_engine.drawdown_service import analyze_drawdowns
from quant_engine.portfolio_metrics_service import aggregate as compute_metrics
from quant_engine.return_statistics_service import compute_return_statistics
from quant_engine.rolling_service import compute_rolling_returns
from quant_engine.tail_var_service import compute_tail_risk

logger = structlog.get_logger()

router = APIRouter(prefix="/analytics")

# Alias router: frontend calls /wealth/entity-analytics/{entity_id}
# while the canonical path is /analytics/entity/{entity_id}.
wealth_alias_router = APIRouter(prefix="/wealth")

_WINDOW_DAYS = {"3m": 63, "6m": 126, "1y": 252, "3y": 756, "5y": 1260}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _resolve_entity_uuid(
    db: AsyncSession, raw_id: str,
) -> uuid.UUID:
    """Resolve a catalog external_id or UUID string to an instruments_universe UUID.

    Catalog external_id formats (from mv_unified_funds):
    - registered_us: class_id (C000…), series_id (S000…), or CIK
    - etf/bdc/mmf: series_id (S000…)
    - ucits_eu: ISIN
    - private_us: fund UUID
    - Direct UUID: instruments_universe PK or model_portfolio PK
    """
    # 1. Direct UUID
    try:
        return uuid.UUID(raw_id)
    except (ValueError, AttributeError):
        pass

    # 2. Class ID (C000…) → look up ticker via sec_fund_classes → instruments_universe
    if raw_id.startswith("C"):
        row = await db.execute(
            select(SecFundClass.ticker).where(SecFundClass.class_id == raw_id).limit(1),
        )
        ticker = row.scalar_one_or_none()
        if ticker:
            inst = await db.execute(
                select(Instrument.instrument_id).where(Instrument.ticker == ticker).limit(1),
            )
            found = inst.scalar_one_or_none()
            if found:
                return found

    # 3. Series ID (S000…) → attributes->>'series_id'
    if raw_id.startswith("S"):
        row = await db.execute(
            select(Instrument.instrument_id).where(
                Instrument.attributes["series_id"].astext == raw_id,
            ).limit(1),
        )
        found = row.scalar_one_or_none()
        if found:
            return found

    # 4. CIK (numeric string) → attributes->>'sec_cik'
    if raw_id.isdigit() or (raw_id.startswith("0") and raw_id.replace("0", "").isdigit()):
        row = await db.execute(
            select(Instrument.instrument_id).where(
                Instrument.attributes["sec_cik"].astext == raw_id,
            ).limit(1),
        )
        found = row.scalar_one_or_none()
        if found:
            return found

    # 5. ISIN → isin column
    row = await db.execute(
        select(Instrument.instrument_id).where(Instrument.isin == raw_id).limit(1),
    )
    found = row.scalar_one_or_none()
    if found:
        return found

    # 6. Ticker fallback
    row = await db.execute(
        select(Instrument.instrument_id).where(Instrument.ticker == raw_id).limit(1),
    )
    found = row.scalar_one_or_none()
    if found:
        return found

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Could not resolve entity identifier: {raw_id}",
    )


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
        select(Instrument.name, InstrumentOrg.block_id)
        .outerjoin(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
        .where(Instrument.instrument_id == entity_id),
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
        "Returns 7 institutional metric groups: Risk Statistics, Drawdown, "
        "Up/Down Capture, Rolling Returns, Return Distribution, "
        "Return Statistics (eVestment I-V), Tail Risk (eVestment VII). "
        "Entity type is auto-detected via nav_reader polymorphism."
    ),
)
async def get_entity_analytics(
    entity_id: str,
    window: str = Query("1y", pattern="^(3m|6m|1y|3y|5y)$", description="Lookback window"),
    benchmark_id: uuid.UUID | None = Query(None, description="Explicit benchmark entity UUID"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> EntityAnalyticsResponse:
    # ── Resolve catalog external_id to UUID ─────────────────────────
    resolved_id = await _resolve_entity_uuid(db, entity_id)

    # ── Resolve entity metadata ──────────────────────────────────────
    entity_type, entity_name, block_id = await _resolve_entity_meta(db, resolved_id)

    # ── Fetch NAV series via nav_reader ──────────────────────────────
    today = date.today()
    lookback_days = _WINDOW_DAYS.get(window, 252)
    start_date = today - timedelta(days=int(lookback_days * 1.5))  # buffer for trading days

    nav_rows: list[NavRow] = await fetch_nav_series(db, resolved_id, start_date, today)

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

    # ── 6. Return Statistics (eVestment Sections I-V) ────────────────
    return_stats_result = None
    try:
        return_stats_raw = compute_return_statistics(
            daily_returns=returns,
            benchmark_returns=bm_aligned,
            risk_free_rate=0.04,
            mar=0.0,
        )
        return_stats_result = ReturnStatistics(
            arithmetic_mean_monthly=return_stats_raw.arithmetic_mean_monthly,
            geometric_mean_monthly=return_stats_raw.geometric_mean_monthly,
            avg_monthly_gain=return_stats_raw.avg_monthly_gain,
            avg_monthly_loss=return_stats_raw.avg_monthly_loss,
            gain_loss_ratio=return_stats_raw.gain_loss_ratio,
            gain_std_dev=return_stats_raw.gain_std_dev,
            loss_std_dev=return_stats_raw.loss_std_dev,
            downside_deviation=return_stats_raw.downside_deviation,
            semi_deviation=return_stats_raw.semi_deviation,
            sterling_ratio=return_stats_raw.sterling_ratio,
            omega_ratio=return_stats_raw.omega_ratio,
            treynor_ratio=return_stats_raw.treynor_ratio,
            jensen_alpha=return_stats_raw.jensen_alpha,
            up_percentage_ratio=return_stats_raw.up_percentage_ratio,
            down_percentage_ratio=return_stats_raw.down_percentage_ratio,
            r_squared=return_stats_raw.r_squared,
        )
    except Exception:
        logger.warning("return_statistics_computation_failed", entity_id=str(resolved_id))

    # ── 7. Tail Risk (eVestment Section VII) ─────────────────────────
    tail_risk_result = None
    try:
        tail_raw = compute_tail_risk(daily_returns=returns)
        tail_risk_result = TailRiskMetrics(
            var_parametric_90=tail_raw.var_parametric_90,
            var_parametric_95=tail_raw.var_parametric_95,
            var_parametric_99=tail_raw.var_parametric_99,
            var_modified_95=tail_raw.var_modified_95,
            var_modified_99=tail_raw.var_modified_99,
            etl_95=tail_raw.etl_95,
            etl_modified_95=tail_raw.etl_modified_95,
            etr_95=tail_raw.etr_95,
            starr_ratio=tail_raw.starr_ratio,
            rachev_ratio=tail_raw.rachev_ratio,
            jarque_bera_stat=tail_raw.jarque_bera_stat,
            jarque_bera_pvalue=tail_raw.jarque_bera_pvalue,
            is_normal=tail_raw.is_normal,
        )
    except Exception:
        logger.warning("tail_risk_computation_failed", entity_id=str(resolved_id))

    # ── 8. Insider Sentiment (Alternative Data) ────────────────────────
    insider_data = None
    if entity_type == "instrument":
        try:
            inst_row = await db.execute(
                select(Instrument.attributes).where(Instrument.instrument_id == resolved_id)
            )
            attrs = inst_row.scalar_one_or_none()
            if attrs:
                cik = attrs.get("sec_cik")
                ticker = attrs.get("sec_ticker")
                
                if cik or ticker:
                    def fetch_insider_summary(sync_db):
                        from app.domains.wealth.services.insider_queries import get_insider_summary
                        return get_insider_summary(
                            sync_db, 
                            issuer_cik=str(cik).zfill(10) if cik else None, 
                            issuer_ticker=str(ticker) if ticker else None
                        )

                    summary_raw = await db.run_sync(fetch_insider_summary)
                    if summary_raw:
                        from app.domains.wealth.schemas.entity_analytics import (
                            InsiderData,
                            InsiderSummary,
                        )
                        insider_data = InsiderData(
                            insider_sentiment_score=summary_raw.get("score"),
                            insider_summary=InsiderSummary(
                                buy_value=summary_raw.get("buy_value", 0.0),
                                sell_value=summary_raw.get("sell_value", 0.0),
                            )
                        )
        except Exception:
            logger.warning("insider_sentiment_fetch_failed", entity_id=str(resolved_id))

    return EntityAnalyticsResponse(
        entity_id=resolved_id,
        entity_type=entity_type,
        entity_name=entity_name,
        as_of_date=today,
        window=window,
        risk_statistics=risk_stats,
        drawdown=drawdown,
        capture=capture,
        rolling_returns=rolling,
        distribution=distribution,
        return_statistics=return_stats_result,
        tail_risk=tail_risk_result,
        insider_data=insider_data,
    )


# ---------------------------------------------------------------------------
# Active Share (eVestment p.73)
# ---------------------------------------------------------------------------


async def _fetch_fund_holdings_weights(
    db: AsyncSession, entity_id: uuid.UUID,
) -> dict[str, float]:
    """Fetch latest N-PORT holdings as {cusip: weight} for a single fund.

    Resolves sec_cik from Instrument.attributes, queries latest report_date.
    """
    inst_row = await db.execute(
        select(Instrument.attributes).where(Instrument.instrument_id == entity_id),
    )
    attrs = inst_row.scalar_one_or_none()
    if not attrs:
        return {}
    cik = attrs.get("sec_cik")
    if not cik:
        return {}

    cik_str = str(cik)

    # Latest report_date for this CIK
    latest = await db.execute(
        select(func.max(SecNportHolding.report_date)).where(
            SecNportHolding.cik == cik_str,
        ),
    )
    max_date = latest.scalar_one_or_none()
    if max_date is None:
        return {}

    rows = await db.execute(
        select(SecNportHolding.cusip, SecNportHolding.pct_of_nav).where(
            SecNportHolding.cik == cik_str,
            SecNportHolding.report_date == max_date,
            SecNportHolding.cusip.isnot(None),
            SecNportHolding.pct_of_nav.isnot(None),
        ),
    )
    weights: dict[str, float] = {}
    for r in rows.all():
        pct = float(r[1])
        # Aggregate by CUSIP (same security may appear twice)
        weights[r[0]] = weights.get(r[0], 0.0) + pct / 100.0
    return weights


async def _fetch_entity_holdings_weights(
    db: AsyncSession, entity_id: uuid.UUID, entity_type: str,
) -> dict[str, float]:
    """Polymorphic holdings weights resolver."""
    if entity_type == "model_portfolio":
        rows = await fetch_portfolio_holdings_exploded(db, entity_id)
        weights: dict[str, float] = {}
        for h in rows:
            weights[h.cusip] = weights.get(h.cusip, 0.0) + h.weighted_pct
        return weights
    return await _fetch_fund_holdings_weights(db, entity_id)


@router.get(
    "/active-share/{entity_id}",
    response_model=ActiveShareResponse,
    summary="Active Share vs benchmark (eVestment p.73)",
)
async def get_active_share(
    entity_id: uuid.UUID,
    benchmark_id: uuid.UUID = Query(..., description="Benchmark entity UUID (fund with N-PORT data)"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> ActiveShareResponse:
    """Holdings-based Active Share: 0.5 * sum(|w_fund - w_index|).

    Both entity and benchmark must have N-PORT holdings data.
    """
    entity_type, entity_name, block_id = await _resolve_entity_meta(db, entity_id)

    portfolio_weights = await _fetch_entity_holdings_weights(db, entity_id, entity_type)
    benchmark_weights = await _fetch_fund_holdings_weights(db, benchmark_id)

    # Compute excess return for efficiency (optional, best-effort)
    excess_return = None
    today = date.today()
    start = today - timedelta(days=252)
    try:
        e_rows = await fetch_nav_series(db, entity_id, start, today)
        b_rows = await fetch_nav_series(db, benchmark_id, start, today)
        if len(e_rows) > 20 and len(b_rows) > 20:
            e_ret = [r.daily_return for r in e_rows if r.daily_return is not None]
            b_ret = [r.daily_return for r in b_rows if r.daily_return is not None]
            if e_ret and b_ret:
                e_cum = 1.0
                for r in e_ret:
                    e_cum *= (1 + r)
                b_cum = 1.0
                for r in b_ret:
                    b_cum *= (1 + r)
                e_ann = e_cum ** (252 / len(e_ret)) - 1
                b_ann = b_cum ** (252 / len(b_ret)) - 1
                excess_return = e_ann - b_ann
    except Exception:
        logger.debug("active_share_excess_return_unavailable", entity_id=str(entity_id))

    result = compute_active_share(
        portfolio_weights=portfolio_weights,
        benchmark_weights=benchmark_weights,
        excess_return=excess_return,
    )

    return ActiveShareResponse(
        entity_id=entity_id,
        entity_name=entity_name,
        active_share=result.active_share,
        overlap=result.overlap,
        active_share_efficiency=result.active_share_efficiency,
        n_portfolio_positions=result.n_portfolio_positions,
        n_benchmark_positions=result.n_benchmark_positions,
        n_common_positions=result.n_common_positions,
        as_of_date=today,
    )


# ── Frontend alias — /wealth/entity-analytics/{entity_id} ───────────────────
# The frontend calls /wealth/entity-analytics/{cik} but the canonical backend
# path is /analytics/entity/{entity_id}.  This alias delegates to the same
# handler so existing frontend code works without a URL change.

@wealth_alias_router.get(
    "/entity-analytics/{entity_id}",
    response_model=EntityAnalyticsResponse,
    summary="Entity analytics vitrine — frontend alias",
    include_in_schema=False,
)
async def get_entity_analytics_alias(
    entity_id: str,
    window: str = Query("1y", pattern="^(3m|6m|1y|3y|5y)$"),
    benchmark_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> EntityAnalyticsResponse:
    return await get_entity_analytics(
        entity_id=entity_id,
        window=window,
        benchmark_id=benchmark_id,
        db=db,
        user=user,
    )

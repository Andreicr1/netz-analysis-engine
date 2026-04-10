"""Risk timeseries API — vectorized drawdown, GARCH vol, and regime data.

Serves pre-computed risk series from TimescaleDB hypertables for
TradingView chart overlay injection. All computation happens in
the backend (DB-first); the frontend receives clean [{time, value}]
arrays ready for charting.

Global tables (no RLS): nav_timeseries, fund_risk_metrics, macro_regime_history.
Instrument resolution: ticker → instruments_universe.
"""

from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.security.clerk_auth import CurrentUser, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.risk_timeseries import RiskTimeseriesOut

logger = structlog.get_logger()

router = APIRouter(prefix="/risk", tags=["risk"])


@router.get(
    "/timeseries/{ticker}",
    response_model=RiskTimeseriesOut,
    summary="Risk timeseries for TradingView overlay",
    description=(
        "Returns drawdown, GARCH volatility, and macro regime probability "
        "series for a given ticker, indexed by date. All series are pre-computed "
        "from TimescaleDB hypertables — zero in-request computation."
    ),
)
@route_cache(ttl=300, key_prefix="risk:timeseries")
async def get_risk_timeseries(
    ticker: str,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> RiskTimeseriesOut:
    today = date.today()
    if from_date is None:
        from_date = today - timedelta(days=365)
    if to_date is None:
        to_date = today

    # ── 1. Resolve ticker → instrument_id ──────────────────────
    resolve_stmt = text("""
        SELECT instrument_id
        FROM instruments_universe
        WHERE UPPER(ticker) = UPPER(:ticker)
          AND is_active = true
        LIMIT 1
    """)
    result = await db.execute(resolve_stmt, {"ticker": ticker.strip()})
    row = result.one_or_none()
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument not found for ticker: {ticker}",
        )
    instrument_id = row.instrument_id

    # ── 2. Drawdown series from nav_timeseries ─────────────────
    # Running max NAV → drawdown = (nav / running_max) - 1
    drawdown_stmt = text("""
        SELECT
            nav_date AS dt,
            (nav / MAX(nav) OVER (ORDER BY nav_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) - 1
                AS drawdown
        FROM nav_timeseries
        WHERE instrument_id = :iid
          AND nav_date >= :from_date
          AND nav_date <= :to_date
          AND nav IS NOT NULL
        ORDER BY nav_date
    """)
    dd_result = await db.execute(
        drawdown_stmt,
        {"iid": instrument_id, "from_date": from_date, "to_date": to_date},
    )
    drawdown_series = [
        {"time": r.dt.isoformat(), "value": round(float(r.drawdown) * 100, 4)}
        for r in dd_result.all()
    ]

    # ── 3. GARCH volatility from fund_risk_metrics ─────────────
    garch_stmt = text("""
        SELECT calc_date AS dt, volatility_garch
        FROM fund_risk_metrics
        WHERE instrument_id = :iid
          AND calc_date >= :from_date
          AND calc_date <= :to_date
          AND volatility_garch IS NOT NULL
          AND organization_id IS NULL
        ORDER BY calc_date
    """)
    garch_result = await db.execute(
        garch_stmt,
        {"iid": instrument_id, "from_date": from_date, "to_date": to_date},
    )
    volatility_series = [
        {"time": r.dt.isoformat(), "value": round(float(r.volatility_garch) * 100, 4)}
        for r in garch_result.all()
    ]

    # ── 4. Regime probabilities from macro_regime_history ──────
    regime_stmt = text("""
        SELECT regime_date AS dt, p_high_vol, classified_regime
        FROM macro_regime_history
        WHERE regime_date >= :from_date
          AND regime_date <= :to_date
        ORDER BY regime_date
    """)
    regime_result = await db.execute(
        regime_stmt,
        {"from_date": from_date, "to_date": to_date},
    )
    regime_series = [
        {
            "time": r.dt.isoformat(),
            "value": round(float(r.p_high_vol), 4),
            "regime": r.classified_regime,
        }
        for r in regime_result.all()
    ]

    return RiskTimeseriesOut(
        ticker=ticker.upper(),
        instrument_id=str(instrument_id),
        from_date=from_date,
        to_date=to_date,
        drawdown=drawdown_series,
        volatility_garch=volatility_series,
        regime_prob=regime_series,
    )

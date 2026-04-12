"""Risk timeseries API — vectorized drawdown, GARCH vol, and regime data.

Serves pre-computed risk series from TimescaleDB hypertables for
TradingView chart overlay injection. All computation happens in
the backend (DB-first); the frontend receives clean [{time, value}]
arrays ready for charting.

Primary key is ``instrument_id`` (UUID), consistent with the rest of
the wealth domain. Ticker is returned on the payload for display only,
resolved via ``instruments_universe``.

Global tables (no RLS): nav_timeseries, fund_risk_metrics,
macro_regime_history.
"""

import uuid
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
    "/timeseries/{instrument_id}",
    response_model=RiskTimeseriesOut,
    response_model_by_alias=True,
    summary="Risk timeseries for TradingView overlay",
    description=(
        "Returns drawdown, conditional volatility, and macro regime probability "
        "series for a given instrument_id, indexed by date. All series are "
        "pre-computed from TimescaleDB hypertables — zero in-request "
        "computation. Sanitised through sanitized.py: the volatility field "
        "is emitted as ``conditional_volatility`` and regime codes are "
        "rewritten to Expansion / Cautious / Stress phrasing."
    ),
)
@route_cache(ttl=300, key_prefix="risk:timeseries")
async def get_risk_timeseries(
    instrument_id: uuid.UUID,
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

    # ── 1. Resolve ticker for display (optional) ──────────────
    ticker_stmt = text("""
        SELECT ticker
        FROM instruments_universe
        WHERE instrument_id = :iid
        LIMIT 1
    """)
    ticker_row = (await db.execute(ticker_stmt, {"iid": instrument_id})).one_or_none()
    ticker_label = ticker_row.ticker if ticker_row else None

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
    drawdown_rows = dd_result.all()

    if not drawdown_rows and ticker_row is None:
        # Neither metadata nor NAV — the instrument simply does not exist.
        raise HTTPException(
            status_code=404,
            detail=f"Instrument not found: {instrument_id}",
        )

    drawdown_series = [
        {"time": r.dt.isoformat(), "value": round(float(r.drawdown) * 100, 4)}
        for r in drawdown_rows
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
        instrument_id=str(instrument_id),
        ticker=ticker_label,
        from_date=from_date,
        to_date=to_date,
        drawdown=drawdown_series,
        volatility_garch=volatility_series,
        regime_prob=regime_series,
    )

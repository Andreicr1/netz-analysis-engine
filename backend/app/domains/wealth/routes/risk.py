import asyncio
from datetime import UTC, date, datetime, timedelta

import redis.asyncio as aioredis
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func as sa_func
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import route_cache
from app.core.config.config_service import ConfigService
from app.core.config.dependencies import get_config_service
from app.core.config.settings import settings
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.instrument_org import InstrumentOrg
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from app.domains.wealth.models.risk import FundRiskMetrics
from app.domains.wealth.routes.common import VALID_PROFILES, get_latest_snapshot
from app.domains.wealth.routes.common import validate_profile as _validate_profile
from app.domains.wealth.schemas.macro import MacroIndicators
from app.domains.wealth.schemas.risk import (
    BatchRiskSummaryOut,
    CVaRPoint,
    CVaRStatus,
    RegimeHistoryPoint,
)
from app.shared.schemas import RegimeRead
from quant_engine.regime_service import get_current_regime, get_latest_macro_values

logger = structlog.get_logger()

# Shared Redis connection for SSE pub/sub fan-out
_sse_redis: aioredis.Redis | None = None
_sse_redis_lock: asyncio.Lock | None = None


async def _get_sse_redis() -> aioredis.Redis:
    """Get or create a shared Redis connection for SSE (async-safe)."""
    global _sse_redis, _sse_redis_lock
    if _sse_redis_lock is None:
        _sse_redis_lock = asyncio.Lock()
    async with _sse_redis_lock:
        if _sse_redis is None:
            _sse_redis = aioredis.from_url(settings.redis_url)
    return _sse_redis


async def close_sse_redis() -> None:
    """Close the shared SSE Redis connection. Call during app shutdown."""
    global _sse_redis
    if _sse_redis is not None:
        await _sse_redis.aclose()
        _sse_redis = None

router = APIRouter(prefix="/risk")

_MAX_BATCH_PROFILES = 20


def _snap_to_cvar(profile: str, snap: PortfolioSnapshot | None) -> CVaRStatus:
    return CVaRStatus(
        profile=profile,
        calc_date=snap.snapshot_date if snap else None,
        cvar_current=snap.cvar_current if snap else None,
        cvar_limit=snap.cvar_limit if snap else None,
        cvar_utilized_pct=snap.cvar_utilized_pct if snap else None,
        trigger_status=snap.trigger_status if snap else None,
        consecutive_breach_days=snap.consecutive_breach_days if snap else 0,
        regime=snap.regime if snap else None,
        cvar_lower_5=float(snap.cvar_lower_5) if snap and snap.cvar_lower_5 is not None else None,
        cvar_upper_95=float(snap.cvar_upper_95) if snap and snap.cvar_upper_95 is not None else None,
    )


# ── Batched summary (MUST come before /{profile}/* to avoid path capture) ──


@router.get(
    "/summary",
    response_model=BatchRiskSummaryOut,
    summary="Batched risk summary for multiple profiles",
)
@route_cache(ttl=300, key_prefix="risk:summary")
async def get_risk_summary_batch(
    profiles: str = Query(..., description="Comma-separated profile names"),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> BatchRiskSummaryOut:
    names = [p.strip() for p in profiles.split(",") if p.strip()]
    if not names:
        raise HTTPException(status_code=422, detail="profiles parameter must not be empty")
    if len(names) > _MAX_BATCH_PROFILES:
        raise HTTPException(
            status_code=422,
            detail=f"Too many profiles (max {_MAX_BATCH_PROFILES})",
        )

    # Single query: latest snapshot per requested profile
    latest_subq = (
        select(
            PortfolioSnapshot.profile,
            sa_func.max(PortfolioSnapshot.snapshot_date).label("max_date"),
        )
        .where(PortfolioSnapshot.profile.in_(names))
        .group_by(PortfolioSnapshot.profile)
        .subquery()
    )
    stmt = (
        select(PortfolioSnapshot)
        .join(
            latest_subq,
            (PortfolioSnapshot.profile == latest_subq.c.profile)
            & (PortfolioSnapshot.snapshot_date == latest_subq.c.max_date),
        )
    )
    result = await db.execute(stmt)
    snaps_by_profile = {s.profile: s for s in result.scalars().all()}

    # Momentum averages per profile: profile → block_ids → instruments → fund_risk_metrics
    momentum_by_profile: dict[str, dict[str, float | None]] = {}
    valid_names = [n for n in names if n in VALID_PROFILES]
    if valid_names:
        momentum_stmt = (
            select(
                StrategicAllocation.profile,
                sa_func.avg(FundRiskMetrics.rsi_14).label("rsi_14"),
                sa_func.avg(FundRiskMetrics.bb_position).label("bb_position"),
                sa_func.avg(FundRiskMetrics.nav_momentum_score).label("nav_momentum_score"),
                sa_func.avg(FundRiskMetrics.flow_momentum_score).label("flow_momentum_score"),
                sa_func.avg(FundRiskMetrics.blended_momentum_score).label("blended_momentum_score"),
            )
            .join(InstrumentOrg, InstrumentOrg.block_id == StrategicAllocation.block_id)
            .join(Instrument, Instrument.instrument_id == InstrumentOrg.instrument_id)
            .join(FundRiskMetrics, FundRiskMetrics.instrument_id == Instrument.instrument_id)
            .where(
                StrategicAllocation.profile.in_(valid_names),
                FundRiskMetrics.calc_date == (
                    select(sa_func.max(FundRiskMetrics.calc_date))
                    .where(FundRiskMetrics.instrument_id == Instrument.instrument_id)
                    .correlate(Instrument)
                    .scalar_subquery()
                ),
            )
            .group_by(StrategicAllocation.profile)
        )
        mom_result = await db.execute(momentum_stmt)
        for row in mom_result.all():
            momentum_by_profile[row.profile] = {
                "rsi_14": float(row.rsi_14) if row.rsi_14 is not None else None,
                "bb_position": float(row.bb_position) if row.bb_position is not None else None,
                "nav_momentum_score": float(row.nav_momentum_score) if row.nav_momentum_score is not None else None,
                "flow_momentum_score": float(row.flow_momentum_score) if row.flow_momentum_score is not None else None,
                "blended_momentum_score": float(row.blended_momentum_score) if row.blended_momentum_score is not None else None,
            }

    results: dict[str, CVaRStatus | None] = {}
    for name in names:
        if name not in VALID_PROFILES:
            results[name] = None
        else:
            snap = snaps_by_profile.get(name)
            cvar = _snap_to_cvar(name, snap)
            mom = momentum_by_profile.get(name, {})
            cvar.rsi_14 = mom.get("rsi_14")
            cvar.bb_position = mom.get("bb_position")
            cvar.nav_momentum_score = mom.get("nav_momentum_score")
            cvar.flow_momentum_score = mom.get("flow_momentum_score")
            cvar.blended_momentum_score = mom.get("blended_momentum_score")
            results[name] = cvar

    return BatchRiskSummaryOut(
        profiles=results,
        computed_at=datetime.now(UTC),
        profile_count=len(results),
    )


# ── Single-profile endpoints ──────────────────────────────────────


@router.get(
    "/{profile}/cvar",
    response_model=CVaRStatus,
    summary="Current CVaR status",
    description="Returns the current CVaR level, limit, utilization, and trigger status for a profile.",
)
@route_cache(ttl=60, key_prefix="risk:cvar")
async def get_cvar(
    profile: str,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> CVaRStatus:
    _validate_profile(profile)
    snap = await get_latest_snapshot(db, profile)
    cvar = _snap_to_cvar(profile, snap)

    # Enrich with momentum averages for this profile
    momentum_stmt = (
        select(
            sa_func.avg(FundRiskMetrics.rsi_14).label("rsi_14"),
            sa_func.avg(FundRiskMetrics.bb_position).label("bb_position"),
            sa_func.avg(FundRiskMetrics.nav_momentum_score).label("nav_momentum_score"),
            sa_func.avg(FundRiskMetrics.flow_momentum_score).label("flow_momentum_score"),
            sa_func.avg(FundRiskMetrics.blended_momentum_score).label("blended_momentum_score"),
        )
        .select_from(StrategicAllocation)
        .join(InstrumentOrg, InstrumentOrg.block_id == StrategicAllocation.block_id)
        .join(Instrument, Instrument.instrument_id == InstrumentOrg.instrument_id)
        .join(FundRiskMetrics, FundRiskMetrics.instrument_id == Instrument.instrument_id)
        .where(
            StrategicAllocation.profile == profile,
            FundRiskMetrics.calc_date == (
                select(sa_func.max(FundRiskMetrics.calc_date))
                .where(FundRiskMetrics.instrument_id == Instrument.instrument_id)
                .correlate(Instrument)
                .scalar_subquery()
            ),
        )
    )
    row = (await db.execute(momentum_stmt)).one_or_none()
    if row:
        cvar.rsi_14 = float(row.rsi_14) if row.rsi_14 is not None else None
        cvar.bb_position = float(row.bb_position) if row.bb_position is not None else None
        cvar.nav_momentum_score = float(row.nav_momentum_score) if row.nav_momentum_score is not None else None
        cvar.flow_momentum_score = float(row.flow_momentum_score) if row.flow_momentum_score is not None else None
        cvar.blended_momentum_score = float(row.blended_momentum_score) if row.blended_momentum_score is not None else None

    return cvar


@router.get(
    "/{profile}/cvar/history",
    response_model=list[CVaRPoint],
    summary="Rolling CVaR history",
    description="Returns CVaR time-series for a profile within a date range.",
)
async def get_cvar_history(
    profile: str,
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[CVaRPoint]:
    _validate_profile(profile)

    today = date.today()
    # Default: last 6 months if no from_date — avoids full hypertable scan
    if from_date is None:
        from_date = today - timedelta(days=180)
    if to_date is None:
        to_date = today

    stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.profile == profile)
        .where(PortfolioSnapshot.snapshot_date >= from_date)
        .where(PortfolioSnapshot.snapshot_date <= to_date)
        .order_by(PortfolioSnapshot.snapshot_date)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        CVaRPoint(
            snapshot_date=row.snapshot_date,
            cvar_current=row.cvar_current,
            cvar_limit=row.cvar_limit,
            cvar_utilized_pct=row.cvar_utilized_pct,
            trigger_status=row.trigger_status,
        )
        for row in result.scalars().all()
    ]


@router.get(
    "/regime",
    response_model=RegimeRead,
    summary="Current regime classification",
    description="Returns the current market regime based on latest portfolio snapshots.",
)
@route_cache(ttl=300, key_prefix="risk:regime")
async def get_regime(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
    config_service: ConfigService = Depends(get_config_service),
    actor: Actor = Depends(get_actor),
) -> RegimeRead:
    config_result = await config_service.get("liquid_funds", "calibration", actor.organization_id)
    config = config_result.value

    # Pre-fetch fallback regime from latest PortfolioSnapshot
    fallback_stmt = (
        select(PortfolioSnapshot.regime)
        .where(PortfolioSnapshot.regime.is_not(None))
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    fallback_result = await db.execute(fallback_stmt)
    fallback_regime = fallback_result.scalar_one_or_none() or "RISK_ON"

    return await get_current_regime(db, config=config, fallback_regime=fallback_regime)


@router.get(
    "/regime/history",
    response_model=list[RegimeHistoryPoint],
    summary="Regime history",
    description="Returns regime classification history across all profiles.",
)
async def get_regime_history(
    from_date: date | None = Query(None, alias="from"),
    to_date: date | None = Query(None, alias="to"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> list[RegimeHistoryPoint]:
    today = date.today()
    # Default: last 6 months if no from_date — avoids full hypertable scan
    if from_date is None:
        from_date = today - timedelta(days=180)
    if to_date is None:
        to_date = today

    stmt = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.regime.is_not(None))
        .where(PortfolioSnapshot.snapshot_date >= from_date)
        .where(PortfolioSnapshot.snapshot_date <= to_date)
        .order_by(PortfolioSnapshot.snapshot_date)
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        RegimeHistoryPoint(
            snapshot_date=row.snapshot_date,
            profile=row.profile,
            regime=row.regime,
        )
        for row in result.scalars().all()
    ]


@router.get(
    "/macro",
    response_model=MacroIndicators,
    summary="Current macro indicators",
    description="Returns the latest VIX, yield curve spread, CPI YoY, and Fed Funds rate from FRED data.",
)
async def get_macro(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),
) -> MacroIndicators:
    macro = await get_latest_macro_values(db)
    vix_val, vix_date = macro.get("VIXCLS", (None, None))
    yc_val, yc_date = macro.get("YIELD_CURVE_10Y2Y", (None, None))
    cpi_val, cpi_date = macro.get("CPI_YOY", (None, None))
    ff_val, ff_date = macro.get("DFF", (None, None))
    return MacroIndicators(
        vix=vix_val,
        vix_date=vix_date,
        yield_curve_10y2y=yc_val,
        yield_curve_date=yc_date,
        cpi_yoy=cpi_val,
        cpi_date=cpi_date,
        fed_funds_rate=ff_val,
        fed_funds_date=ff_date,
    )


async def _sse_generator(request: Request, org_id: str):
    """Subscribe to Redis pub/sub and stream CVaR/regime alerts as SSE.

    Channels use global profiles (PortfolioSnapshot is a global table with no
    organization_id — profiles are shared across all tenants). Alert data
    contains only profile-level CVaR metrics, not tenant-specific fund data.
    Access is gated by Clerk JWT authentication on the route.
    """
    import time as _time

    r = await _get_sse_redis()
    pubsub = r.pubsub()
    channels = [f"wealth:alerts:{p}" for p in sorted(VALID_PROFILES)]
    await pubsub.subscribe(*channels)

    last_heartbeat = _time.monotonic()
    heartbeat_interval = 15  # seconds

    try:
        while True:
            if await request.is_disconnected():
                break
            # Poll with short timeout so we stay responsive to messages and disconnects
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message["type"] == "message":
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"data: {data}\n\n"
                last_heartbeat = _time.monotonic()
            elif _time.monotonic() - last_heartbeat >= heartbeat_interval:
                # Send heartbeat to keep connection alive without blocking message processing
                yield ": heartbeat\n\n"
                last_heartbeat = _time.monotonic()
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe(*channels)
        await pubsub.aclose()


@router.get(
    "/stream",
    summary="Live risk stream (SSE)",
    description="Server-Sent Events stream for real-time CVaR and regime alerts across all profiles. "
    "Requires Bearer token via standard Authorization header.",
)
async def risk_stream(
    request: Request,
    user: CurrentUser = Depends(get_current_user),
    actor: Actor = Depends(get_actor),
) -> StreamingResponse:
    org_id = str(actor.organization_id) if actor.organization_id else ""
    return StreamingResponse(
        _sse_generator(request, org_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

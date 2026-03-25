"""Portfolio evaluation worker — evaluates CVaR status for all 3 profiles.

Usage:
    python -m app.workers.portfolio_eval

Evaluates each profile's current CVaR, breach status, regime, and
creates daily portfolio_snapshots. Publishes alerts via Redis pub/sub.

Config loaded from DB via ConfigService (falls back to hardcoded defaults
when running standalone without RLS context).
"""

import asyncio
import json
import uuid
from datetime import date, timedelta

import numpy as np
import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.core.tenancy.middleware import set_rls_context
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from quant_engine.cvar_service import (
    BreachStatus,
    check_breach_status,
    compute_cvar_from_returns,
    resolve_cvar_config,
)
from quant_engine.regime_service import detect_regime

logger = structlog.get_logger()

PORTFOLIO_EVAL_LOCK_ID = 900_008
PROFILES = ["conservative", "moderate", "growth"]


async def _load_worker_config(db: AsyncSession) -> dict:
    """Load portfolio_profiles config for worker context (no RLS).

    Workers run without Clerk actor context, so we query the defaults
    table directly (no RLS). Returns raw config dict or None for fallback.
    """
    try:
        from app.core.config.models import VerticalConfigDefault

        result = await db.execute(
            select(VerticalConfigDefault.config).where(
                VerticalConfigDefault.vertical == "liquid_funds",
                VerticalConfigDefault.config_type == "portfolio_profiles",
            )
        )
        config = result.scalar_one_or_none()
        if config is not None:
            return config
    except Exception as e:
        logger.warning("Could not load config from DB, using defaults", error=str(e))
    return None


async def _get_profile_weights(db: AsyncSession, profile: str) -> dict[str, float]:
    """Get current strategic weights for a profile, keyed by block_id."""
    today = date.today()
    stmt = (
        select(StrategicAllocation)
        .where(
            StrategicAllocation.profile == profile,
            StrategicAllocation.effective_from <= today,
        )
        .where(
            (StrategicAllocation.effective_to.is_(None))
            | (StrategicAllocation.effective_to >= today)
        )
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    return {row.block_id: float(row.target_weight) for row in rows}


async def _get_fund_returns_by_block(
    db: AsyncSession,
    block_weights: dict[str, float],
    window_months: int,
) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    """Fetch returns for funds in each block."""
    end_date = date.today()
    start_date = end_date - timedelta(days=window_months * 30)
    block_ids = list(block_weights.keys())

    funds_stmt = (
        select(Fund)
        .where(Fund.block_id.in_(block_ids), Fund.is_active == True, Fund.ticker.is_not(None))
        .distinct(Fund.block_id)
        .order_by(Fund.block_id, Fund.name)
    )
    funds_result = await db.execute(funds_stmt)
    block_funds = {f.block_id: f for f in funds_result.scalars().all()}

    if not block_funds:
        return {}, {}

    fund_ids = [f.fund_id for f in block_funds.values()]
    ret_stmt = (
        select(NavTimeseries.instrument_id, NavTimeseries.return_1d)
        .where(
            NavTimeseries.instrument_id.in_(fund_ids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= end_date,
            NavTimeseries.return_1d.is_not(None),
        )
        .order_by(NavTimeseries.instrument_id, NavTimeseries.nav_date)
    )
    ret_result = await db.execute(ret_stmt)

    from collections import defaultdict
    grouped: dict[str, list[float]] = defaultdict(list)
    for instrument_id, ret in ret_result.all():
        grouped[str(instrument_id)].append(float(ret))

    fund_returns: dict[str, np.ndarray] = {}
    fund_weights: dict[str, float] = {}
    for block_id, fund in block_funds.items():
        fid = str(fund.fund_id)
        rets = grouped.get(fid, [])
        if rets:
            fund_returns[fid] = np.array(rets)
            fund_weights[fid] = block_weights[block_id]

    return fund_returns, fund_weights


async def _publish_alert(
    profile: str, breach: BreachStatus, redis_conn=None,
) -> None:
    """Publish breach alert to Redis pub/sub channel."""
    try:
        import redis.asyncio as aioredis

        from app.core.config.settings import settings

        close_after = False
        if redis_conn is None:
            redis_conn = aioredis.from_url(settings.redis_url)
            close_after = True
        try:
            message = json.dumps({
                "profile": profile,
                "trigger_status": breach.trigger_status,
                "cvar_current": breach.cvar_current,
                "cvar_limit": breach.cvar_limit,
                "cvar_utilized_pct": breach.cvar_utilized_pct,
                "consecutive_breach_days": breach.consecutive_breach_days,
            })
            await redis_conn.publish(f"wealth:alerts:{profile}", message)
            logger.info("Alert published", profile=profile, status=breach.trigger_status)
        finally:
            if close_after:
                await redis_conn.aclose()
    except Exception as e:
        logger.warning("Failed to publish Redis alert", error=str(e))


async def evaluate_profile(
    db: AsyncSession,
    profile: str,
    config: dict | None = None,
) -> dict | None:
    """Evaluate a single profile: compute CVaR, breach status, regime."""
    profiles = resolve_cvar_config(config)
    profile_config = profiles[profile]
    today = date.today()

    block_weights = await _get_profile_weights(db, profile)
    if not block_weights:
        logger.info("No strategic weights found", profile=profile)
        return {
            "profile": profile,
            "snapshot_date": today,
            "weights": {},
            "cvar_current": None,
            "cvar_limit": profile_config["limit"],
            "cvar_utilized_pct": None,
            "trigger_status": "ok",
            "consecutive_breach_days": 0,
            "regime": "RISK_ON",
            "core_weight": sum(block_weights.values()) if block_weights else None,
            "satellite_weight": None,
        }

    fund_returns, fund_weights = await _get_fund_returns_by_block(
        db, block_weights, profile_config["window_months"]
    )

    if fund_returns and fund_weights:
        fund_ids = list(fund_weights.keys())
        min_len = min(len(fund_returns[fid]) for fid in fund_ids)
        if min_len > 0:
            portfolio_returns = np.zeros(min_len)
            for fid in fund_ids:
                w = fund_weights[fid]
                portfolio_returns += w * fund_returns[fid][-min_len:]

            cvar, _ = compute_cvar_from_returns(portfolio_returns, profile_config["confidence"])
            regime_result = detect_regime(portfolio_returns)
        else:
            cvar = 0.0
            regime_result = detect_regime(np.array([]))
    else:
        cvar = 0.0
        regime_result = detect_regime(np.array([]))

    # Pre-fetch consecutive breach days from last snapshot
    prev_breach_stmt = (
        select(PortfolioSnapshot.consecutive_breach_days)
        .where(PortfolioSnapshot.profile == profile)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .limit(1)
    )
    prev_result = await db.execute(prev_breach_stmt)
    prev_breach_days = prev_result.scalar_one_or_none() or 0

    breach = check_breach_status(profile, cvar, consecutive_breach_days=prev_breach_days, config=config)

    if breach.trigger_status in ("warning", "breach"):
        await _publish_alert(profile, breach)

    return {
        "profile": profile,
        "snapshot_date": today,
        "weights": block_weights,
        "cvar_current": round(cvar, 6),
        "cvar_limit": profile_config["limit"],
        "cvar_utilized_pct": round(breach.cvar_utilized_pct, 2),
        "trigger_status": breach.trigger_status,
        "consecutive_breach_days": breach.consecutive_breach_days,
        "regime": regime_result.regime,
        "core_weight": round(sum(block_weights.values()), 4),
        "satellite_weight": round(1.0 - sum(block_weights.values()), 4),
    }


async def run_portfolio_eval(org_id: uuid.UUID) -> dict[str, str]:
    """Evaluate all 3 profiles and create daily snapshots."""
    logger.info("Starting portfolio evaluation")
    results: dict[str, str] = {}

    redis_conn = None
    try:
        import redis.asyncio as aioredis

        from app.core.config.settings import settings
        redis_conn = aioredis.from_url(settings.redis_url)
    except Exception:
        logger.warning("Could not create Redis connection for alerts")

    try:
        async with async_session() as db:
            await set_rls_context(db, org_id)
            lock_result = await db.execute(
                text(f"SELECT pg_try_advisory_lock({PORTFOLIO_EVAL_LOCK_ID})")
            )
            acquired = lock_result.scalar()
            if not acquired:
                logger.info("worker_skipped", reason="another instance running")
                return {"status": "skipped", "reason": "portfolio evaluation already running"}
            try:
                # Load config once for all profiles
                config = await _load_worker_config(db)

                for profile in PROFILES:
                    snapshot_data = await evaluate_profile(db, profile, config=config)
                    if snapshot_data is None:
                        results[profile] = "skipped"
                        continue

                    stmt = pg_insert(PortfolioSnapshot).values(
                        organization_id=org_id,
                        profile=snapshot_data["profile"],
                        snapshot_date=snapshot_data["snapshot_date"],
                        weights=snapshot_data["weights"],
                        cvar_current=snapshot_data["cvar_current"],
                        cvar_limit=snapshot_data["cvar_limit"],
                        cvar_utilized_pct=snapshot_data["cvar_utilized_pct"],
                        trigger_status=snapshot_data["trigger_status"],
                        consecutive_breach_days=snapshot_data["consecutive_breach_days"],
                        regime=snapshot_data["regime"],
                        core_weight=snapshot_data["core_weight"],
                        satellite_weight=snapshot_data["satellite_weight"],
                    )
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["organization_id", "profile", "snapshot_date"],
                        set_={
                            "weights": stmt.excluded.weights,
                            "cvar_current": stmt.excluded.cvar_current,
                            "cvar_limit": stmt.excluded.cvar_limit,
                            "cvar_utilized_pct": stmt.excluded.cvar_utilized_pct,
                            "trigger_status": stmt.excluded.trigger_status,
                            "consecutive_breach_days": stmt.excluded.consecutive_breach_days,
                            "regime": stmt.excluded.regime,
                            "core_weight": stmt.excluded.core_weight,
                            "satellite_weight": stmt.excluded.satellite_weight,
                        },
                    )
                    await db.execute(stmt)
                    await db.commit()
                    await set_rls_context(db, org_id)
                    results[profile] = snapshot_data["trigger_status"]
                    logger.info(
                        "Profile evaluated",
                        profile=profile,
                        trigger=snapshot_data["trigger_status"],
                        regime=snapshot_data["regime"],
                        cvar_pct=snapshot_data["cvar_utilized_pct"],
                    )
            except Exception:
                await db.rollback()
                raise
            finally:
                try:
                    await db.execute(
                        text(f"SELECT pg_advisory_unlock({PORTFOLIO_EVAL_LOCK_ID})")
                    )
                except Exception:
                    pass
    finally:
        if redis_conn is not None:
            await redis_conn.aclose()

    logger.info("Portfolio evaluation complete", results=results)
    return results


if __name__ == "__main__":
    asyncio.run(run_portfolio_eval())

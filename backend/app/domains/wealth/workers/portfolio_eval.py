"""Portfolio evaluation worker — evaluates CVaR status for all 3 profiles.

Usage:
    python -m app.workers.portfolio_eval

Evaluates each profile's current CVaR, breach status, regime, and
creates daily portfolio_snapshots. Publishes alerts via Redis pub/sub.
"""

import asyncio
import json
from datetime import date, timedelta

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory as async_session
from app.domains.wealth.models.allocation import StrategicAllocation
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.nav import NavTimeseries
from app.domains.wealth.models.portfolio import PortfolioSnapshot
from quant_engine.cvar_service import (
    PROFILE_CVAR_CONFIG,
    BreachStatus,
    check_breach_status,
    compute_cvar_from_returns,
)
from quant_engine.regime_service import detect_regime

logger = structlog.get_logger()

PROFILES = ["conservative", "moderate", "growth"]


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
    """Fetch returns for funds in each block. Returns (fund_returns, fund_weights).

    For simplicity, picks the first active fund per block.
    Production would use the full fund_selection logic.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=window_months * 30)
    block_ids = list(block_weights.keys())

    # Batch-fetch one representative fund per block
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

    # Batch-fetch returns for all selected funds in one query
    fund_ids = [f.fund_id for f in block_funds.values()]
    ret_stmt = (
        select(NavTimeseries.fund_id, NavTimeseries.return_1d)
        .where(
            NavTimeseries.fund_id.in_(fund_ids),
            NavTimeseries.nav_date >= start_date,
            NavTimeseries.nav_date <= end_date,
            NavTimeseries.return_1d.is_not(None),
        )
        .order_by(NavTimeseries.fund_id, NavTimeseries.nav_date)
    )
    ret_result = await db.execute(ret_stmt)

    from collections import defaultdict
    grouped: dict[str, list[float]] = defaultdict(list)
    for fund_id, ret in ret_result.all():
        grouped[str(fund_id)].append(float(ret))

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


async def evaluate_profile(db: AsyncSession, profile: str) -> dict | None:
    """Evaluate a single profile: compute CVaR, breach status, regime."""
    config = PROFILE_CVAR_CONFIG[profile]
    today = date.today()

    # Get strategic weights
    block_weights = await _get_profile_weights(db, profile)
    if not block_weights:
        logger.info("No strategic weights found", profile=profile)
        # Create snapshot with no data
        return {
            "profile": profile,
            "snapshot_date": today,
            "weights": {},
            "cvar_current": None,
            "cvar_limit": config["limit"],
            "cvar_utilized_pct": None,
            "trigger_status": "ok",
            "consecutive_breach_days": 0,
            "regime": "RISK_ON",
            "core_weight": sum(block_weights.values()) if block_weights else None,
            "satellite_weight": None,
        }

    # Get fund returns for the profile's CVaR window
    fund_returns, fund_weights = await _get_fund_returns_by_block(
        db, block_weights, config["window_months"]
    )

    # Compute portfolio-level CVaR
    if fund_returns and fund_weights:
        # Weighted portfolio returns
        fund_ids = list(fund_weights.keys())
        min_len = min(len(fund_returns[fid]) for fid in fund_ids)
        if min_len > 0:
            portfolio_returns = np.zeros(min_len)
            for fid in fund_ids:
                w = fund_weights[fid]
                portfolio_returns += w * fund_returns[fid][-min_len:]

            cvar, _ = compute_cvar_from_returns(portfolio_returns, config["confidence"])

            # Regime detection from portfolio returns
            regime_result = detect_regime(portfolio_returns)
        else:
            cvar = 0.0
            regime_result = detect_regime(np.array([]))
    else:
        cvar = 0.0
        regime_result = detect_regime(np.array([]))

    # Check breach status
    breach = await check_breach_status(db, profile, cvar)

    # Publish alert if warning or breach
    if breach.trigger_status in ("warning", "breach"):
        await _publish_alert(profile, breach)

    return {
        "profile": profile,
        "snapshot_date": today,
        "weights": block_weights,
        "cvar_current": round(cvar, 6),
        "cvar_limit": config["limit"],
        "cvar_utilized_pct": round(breach.cvar_utilized_pct, 2),
        "trigger_status": breach.trigger_status,
        "consecutive_breach_days": breach.consecutive_breach_days,
        "regime": regime_result.regime,
        "core_weight": round(sum(block_weights.values()), 4),
        "satellite_weight": round(1.0 - sum(block_weights.values()), 4),
    }


async def run_portfolio_eval() -> dict[str, str]:
    """Evaluate all 3 profiles and create daily snapshots."""
    logger.info("Starting portfolio evaluation")
    results: dict[str, str] = {}

    # Shared Redis connection for all alert publishes
    redis_conn = None
    try:
        import redis.asyncio as aioredis

        from app.core.config.settings import settings
        redis_conn = aioredis.from_url(settings.redis_url)
    except Exception:
        logger.warning("Could not create Redis connection for alerts")

    try:
        async with async_session() as db:
            for profile in PROFILES:
                snapshot_data = await evaluate_profile(db, profile)
                if snapshot_data is None:
                    results[profile] = "skipped"
                    continue

                # Upsert snapshot (use index_elements instead of hardcoded constraint name)
                stmt = pg_insert(PortfolioSnapshot).values(
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
                    index_elements=["profile", "snapshot_date"],
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
                # Commit per-profile to avoid long transactions
                await db.commit()
                results[profile] = snapshot_data["trigger_status"]
                logger.info(
                    "Profile evaluated",
                    profile=profile,
                    trigger=snapshot_data["trigger_status"],
                    regime=snapshot_data["regime"],
                    cvar_pct=snapshot_data["cvar_utilized_pct"],
                )
    finally:
        if redis_conn is not None:
            await redis_conn.aclose()

    logger.info("Portfolio evaluation complete", results=results)
    return results


if __name__ == "__main__":
    asyncio.run(run_portfolio_eval())

"""Watchlist batch worker — periodic re-evaluation of watchlisted instruments.

Uses pg_try_advisory_lock (non-blocking) with hardcoded lock ID 900_003.
Re-screens all instruments with approval_status='watchlist', detects transitions,
and publishes alerts via Redis pub/sub.

Short transactions: commits every 200 results to prevent connection pool starvation.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.db.engine import async_session_factory
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.screening_result import ScreeningResult, ScreeningRun

logger = structlog.get_logger(__name__)

WATCHLIST_BATCH_LOCK_ID = 900_003


def _chunked(iterable: list, size: int):
    """Yield chunks of `size` from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


async def run_watchlist_check(org_id: uuid.UUID) -> dict:
    """Weekly watchlist re-evaluation. Uses pg_try_advisory_lock (non-blocking).

    Returns dict with status, counts, or skip reason.
    """
    async with async_session_factory() as db:
        # 1. Non-blocking advisory lock
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({WATCHLIST_BATCH_LOCK_ID})")
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("watchlist_check_skipped", reason="another instance running")
            return {"status": "skipped", "reason": "batch already running"}

        try:
            return await _execute_watchlist_check(db, org_id)
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({WATCHLIST_BATCH_LOCK_ID})")
            )


async def _execute_watchlist_check(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Execute watchlist check logic."""
    # 2. Fetch config ONCE (frozen for entire run)
    config_svc = ConfigService(db)
    config_l1 = (await config_svc.get("liquid_funds", "screening_layer1", org_id)).value
    config_l2 = (await config_svc.get("liquid_funds", "screening_layer2", org_id)).value
    config_l3 = (await config_svc.get("liquid_funds", "screening_layer3", org_id)).value

    # 3. Load all watchlisted instruments
    result = await db.execute(
        select(Instrument).where(
            Instrument.is_active.is_(True),
            Instrument.approval_status == "watchlist",
        )
    )
    instruments = result.scalars().all()

    if not instruments:
        logger.info("watchlist_check_empty", reason="no watchlisted instruments")
        return {"status": "completed", "total_screened": 0}

    # Extract scalar data before crossing async/thread boundary
    instrument_dicts = [
        {
            "instrument_id": i.instrument_id,
            "instrument_type": i.instrument_type,
            "attributes": dict(i.attributes) if i.attributes else {},
            "block_id": i.block_id,
            "name": i.name,
        }
        for i in instruments
    ]

    # 4. Fetch previous screening outcomes for comparison
    instrument_ids = [i.instrument_id for i in instruments]
    prev_results = await db.execute(
        select(ScreeningResult.instrument_id, ScreeningResult.overall_status).where(
            ScreeningResult.instrument_id.in_(instrument_ids),
            ScreeningResult.is_current.is_(True),
        )
    )
    previous_outcomes: dict[uuid.UUID, str] = {
        row.instrument_id: row.overall_status for row in prev_results
    }

    # 5. Create screening run record (type = "watchlist")
    run = ScreeningRun(
        organization_id=org_id,
        run_type="watchlist",
        instrument_count=len(instrument_dicts),
        config_hash="watchlist-check",
    )
    db.add(run)
    await db.flush()
    run_id = run.run_id

    # 6. Re-screen in thread (pure logic, no DB)
    from vertical_engines.wealth.screener.service import ScreenerService
    from vertical_engines.wealth.watchlist.service import WatchlistService

    screener = ScreenerService(config_l1, config_l2, config_l3)
    watchlist_svc = WatchlistService(screener)

    alerts = await asyncio.to_thread(
        watchlist_svc.check_transitions,
        instrument_dicts,
        previous_outcomes,
    )

    # Also re-screen to get new results for DB storage
    screening_results = await asyncio.to_thread(
        lambda: [
            screener.screen_instrument(
                instrument_id=inst["instrument_id"],
                instrument_type=inst["instrument_type"],
                attributes=inst.get("attributes", {}),
                block_id=inst.get("block_id"),
            )
            for inst in instrument_dicts
        ]
    )

    # 7. Write screening results in batches of 200
    for batch in _chunked(screening_results, 200):
        batch_ids = [sr.instrument_id for sr in batch]
        await db.execute(
            update(ScreeningResult)
            .where(
                ScreeningResult.instrument_id.in_(batch_ids),
                ScreeningResult.is_current.is_(True),
            )
            .values(is_current=False)
        )

        for sr in batch:
            screening_result = ScreeningResult(
                organization_id=org_id,
                instrument_id=sr.instrument_id,
                run_id=run_id,
                overall_status=sr.overall_status,
                score=sr.score,
                failed_at_layer=sr.failed_at_layer,
                layer_results=sr.layer_results_dict,
                required_analysis_type=sr.required_analysis_type,
                is_current=True,
            )
            db.add(screening_result)

        await db.commit()

    # 8. Mark run completed
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    await db.commit()

    # 9. Publish alerts via Redis pub/sub
    if alerts:
        await _publish_watchlist_alerts(alerts, str(org_id))

    improvements = sum(1 for a in alerts if a.direction == "improvement")
    deteriorations = sum(1 for a in alerts if a.direction == "deterioration")
    stable_count = len(instrument_dicts) - improvements - deteriorations

    logger.info(
        "watchlist_check_completed",
        total_screened=len(instrument_dicts),
        improvements=improvements,
        deteriorations=deteriorations,
        stable=stable_count,
    )

    return {
        "status": "completed",
        "total_screened": len(instrument_dicts),
        "improvements": improvements,
        "deteriorations": deteriorations,
        "stable": stable_count,
    }


async def _publish_watchlist_alerts(
    alerts: list, org_id: str,
) -> None:
    """Publish transition alerts to Redis pub/sub channel."""
    try:
        import redis.asyncio as aioredis

        from app.core.config.settings import settings

        redis_conn = aioredis.from_url(settings.redis_url)
        try:
            for alert in alerts:
                message = json.dumps({
                    "type": "watchlist_transition",
                    "instrument_id": str(alert.instrument_id),
                    "instrument_name": alert.instrument_name,
                    "previous_outcome": alert.previous_outcome,
                    "new_outcome": alert.new_outcome,
                    "direction": alert.direction,
                    "message": alert.message,
                    "detected_at": alert.detected_at.isoformat(),
                })
                await redis_conn.publish(
                    f"wealth:watchlist:{org_id}", message,
                )
            logger.info(
                "watchlist_alerts_published",
                count=len(alerts),
                org_id=org_id,
            )
        finally:
            await redis_conn.aclose()
    except Exception:
        logger.warning("watchlist_redis_publish_failed", exc_info=True)

"""Screening batch worker — weekly re-screening of all active instruments.

Uses pg_try_advisory_lock (non-blocking) with hardcoded lock ID 900_002.
Python hash() is nondeterministic across processes — never use it for lock IDs.

Short transactions: commits every 200 results to prevent connection pool starvation.
Config captured at start (frozen for entire run — prevents mid-batch inconsistency).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.db.engine import async_session_factory
from app.core.tenancy.middleware import set_rls_context
from app.domains.wealth.models.instrument import Instrument
from app.domains.wealth.models.screening_result import ScreeningResult, ScreeningRun

logger = logging.getLogger(__name__)

SCREENING_BATCH_LOCK_ID = 900_002


def _chunked(iterable: list, size: int):
    """Yield chunks of `size` from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


async def run_screening_batch(org_id: uuid.UUID) -> dict:
    """Weekly batch re-screening. Uses pg_try_advisory_lock (non-blocking).

    Returns dict with status, counts, or skip reason.
    """
    async with async_session_factory() as db:
        await set_rls_context(db, org_id)
        # 1. Non-blocking advisory lock
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({SCREENING_BATCH_LOCK_ID})"),
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("Screening batch skipped — another instance is running")
            return {"status": "skipped", "reason": "batch already running"}

        try:
            return await _execute_batch(db, org_id)
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({SCREENING_BATCH_LOCK_ID})"),
            )


async def _execute_batch(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Execute the batch screening logic."""
    # 2. Fetch config ONCE (frozen for entire run)
    config_svc = ConfigService(db)
    config_l1 = (await config_svc.get("liquid_funds", "screening_layer1", org_id)).value
    config_l2 = (await config_svc.get("liquid_funds", "screening_layer2", org_id)).value
    config_l3 = (await config_svc.get("liquid_funds", "screening_layer3", org_id)).value

    config_hash = hashlib.sha256(
        json.dumps({"l1": config_l1, "l2": config_l2, "l3": config_l3}, sort_keys=True).encode(),
    ).hexdigest()

    # 3. Load all active instruments (short transaction)
    result = await db.execute(
        select(Instrument).where(Instrument.is_active.is_(True)),
    )
    instruments = result.scalars().all()

    if not instruments:
        logger.info("No active instruments to screen")
        return {"status": "completed", "instrument_count": 0}

    # Extract scalar data before crossing async/thread boundary
    instrument_dicts = [
        {
            "instrument_id": i.instrument_id,
            "instrument_type": i.instrument_type,
            "attributes": dict(i.attributes) if i.attributes else {},
            "block_id": i.block_id,
        }
        for i in instruments
    ]

    # 4. Create screening run record
    run = ScreeningRun(
        organization_id=org_id,
        run_type="batch",
        instrument_count=len(instrument_dicts),
        config_hash=config_hash,
    )
    db.add(run)
    await db.flush()
    run_id = run.run_id

    # 5. Compute all layers in thread (pure logic, no DB)
    from vertical_engines.wealth.screener.service import ScreenerService

    screener = ScreenerService(config_l1, config_l2, config_l3)
    screening_results = await asyncio.to_thread(
        lambda: [
            screener.screen_instrument(**inst_dict)
            for inst_dict in instrument_dicts
        ],
    )

    # 6. Write in batches of 200 (short transactions)
    for batch in _chunked(screening_results, 200):
        # Mark previous results as not current for this batch
        batch_ids = [sr.instrument_id for sr in batch]
        await db.execute(
            update(ScreeningResult)
            .where(
                ScreeningResult.instrument_id.in_(batch_ids),
                ScreeningResult.is_current.is_(True),
            )
            .values(is_current=False),
        )

        # Insert new results
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
        await set_rls_context(db, org_id)

    # 7. Mark run as completed
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    await db.commit()
    await set_rls_context(db, org_id)

    passed = sum(1 for r in screening_results if r.overall_status == "PASS")
    failed = sum(1 for r in screening_results if r.overall_status == "FAIL")
    watchlist = sum(1 for r in screening_results if r.overall_status == "WATCHLIST")

    logger.info(
        "Screening batch completed",
        instrument_count=len(screening_results),
        passed=passed,
        failed=failed,
        watchlist=watchlist,
    )

    return {
        "status": "completed",
        "instrument_count": len(screening_results),
        "passed": passed,
        "failed": failed,
        "watchlist": watchlist,
    }

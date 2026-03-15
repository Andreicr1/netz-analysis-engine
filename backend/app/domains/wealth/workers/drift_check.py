"""Drift monitoring worker — checks allocation drift for all profiles.

Usage:
    python -m app.workers.drift_check

Computes drift for all 3 profiles and creates rebalance events
when drift exceeds configured thresholds. Uses PostgreSQL advisory
lock to prevent concurrent pipeline runs from creating duplicates.
"""

import asyncio

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session
from quant_engine.drift_service import compute_drift
from quant_engine.rebalance_service import create_system_rebalance_event

logger = structlog.get_logger()

PROFILES = ["conservative", "moderate", "growth"]
PIPELINE_LOCK_ID = 42  # Advisory lock ID for pipeline serialization


async def run_drift_check() -> dict[str, str]:
    """Check allocation drift for all profiles.

    Creates rebalance events when drift exceeds thresholds.
    Uses advisory lock to prevent concurrent pipeline runs.
    """
    logger.info("Starting drift check")
    results: dict[str, str] = {}

    async with async_session() as db:
        # Non-blocking advisory lock — skip if another pipeline is running
        lock_result = await db.execute(text(f"SELECT pg_try_advisory_lock({PIPELINE_LOCK_ID})"))
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("Drift check already running, skipping")
            return results

        # Load config once for all profiles (worker context, no RLS)
        try:
            from sqlalchemy import select as sa_select

            from app.core.config.models import VerticalConfigDefault

            cfg_result = await db.execute(
                sa_select(VerticalConfigDefault.config).where(
                    VerticalConfigDefault.vertical == "liquid_funds",
                    VerticalConfigDefault.config_type == "calibration",
                )
            )
            config = cfg_result.scalar_one_or_none()
        except Exception:
            config = None

        try:
            for profile in PROFILES:
                report = await compute_drift(db, profile, config=config)
                results[profile] = report.overall_status

                logger.info(
                    "Drift check result",
                    profile=profile,
                    status=report.overall_status,
                    max_drift=report.max_drift_pct,
                    rebalance_recommended=report.rebalance_recommended,
                    turnover=report.estimated_turnover,
                )

                if report.rebalance_recommended:
                    # Build drift detail for trigger reason
                    drifted_blocks = ", ".join(
                        f"{d.block_id}={d.absolute_drift:+.1%}"
                        for d in report.blocks[:3]  # Top 3 drifted blocks
                    )
                    event = await create_system_rebalance_event(
                        db,
                        profile=profile,
                        event_type="drift_rebalance",
                        trigger_reason=(
                            f"Allocation drift detected: max {report.max_drift_pct:.1%} "
                            f"(threshold: {report.maintenance_trigger:.0%}). "
                            f"Blocks: {drifted_blocks}. "
                            f"Estimated turnover: {report.estimated_turnover:.1%}"
                        ),
                        cvar_before=None,
                        actor_source="system",
                    )
                    logger.info(
                        "Drift rebalance event created",
                        profile=profile,
                        event_id=str(event.event_id),
                    )

                await db.commit()

        finally:
            await db.execute(text(f"SELECT pg_advisory_unlock({PIPELINE_LOCK_ID})"))

    logger.info("Drift check complete", results=results)
    return results


if __name__ == "__main__":
    asyncio.run(run_drift_check())

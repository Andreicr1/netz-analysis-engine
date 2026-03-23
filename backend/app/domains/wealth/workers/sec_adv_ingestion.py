"""SEC ADV ingestion worker — monthly Form ADV bulk CSV from SEC FOIA.

Usage:
    python -m app.domains.wealth.workers.sec_adv_ingestion

Downloads the latest monthly ADV CSV from SEC FOIA (or reads a local path),
parses manager registration data, and upserts into sec_managers +
sec_manager_funds tables.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_022.
"""

import asyncio

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()
SEC_ADV_LOCK_ID = 900_022


async def run_sec_adv_ingestion(
    *,
    csv_path: str | None = None,
) -> dict:
    """Download and ingest Form ADV bulk CSV into sec_managers.

    If csv_path is provided, reads from local file (supports ZIP).
    Otherwise downloads the latest from SEC FOIA website.
    """
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({SEC_ADV_LOCK_ID})")
        )
        if not lock_result.scalar():
            logger.warning("sec_adv_ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            logger.info("sec_adv_ingestion_start", csv_path=csv_path)

            from data_providers.sec.adv_service import AdvService

            service = AdvService(db_session_factory=async_session)

            managers_upserted = await service.ingest_bulk_adv(csv_path=csv_path)

            summary = {
                "status": "completed",
                "managers_upserted": managers_upserted,
            }
            logger.info("sec_adv_ingestion_complete", **summary)
            return summary

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({SEC_ADV_LOCK_ID})")
            )


if __name__ == "__main__":
    asyncio.run(run_sec_adv_ingestion())

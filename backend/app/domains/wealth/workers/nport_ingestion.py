"""N-PORT ingestion worker — fetches monthly mutual fund holdings from SEC EDGAR.

Usage:
    python -m app.domains.wealth.workers.nport_ingestion

Fetches N-PORT filings for active managers with CIKs from sec_managers,
parses holdings from XML, and upserts into sec_nport_holdings hypertable.

GLOBAL TABLE: No organization_id, no RLS.
Advisory lock ID = 900_018.
"""

import asyncio

import structlog
from sqlalchemy import select, text

from app.core.db.engine import async_session_factory as async_session
from app.shared.models import SecManager

logger = structlog.get_logger()
NPORT_LOCK_ID = 900_018


async def run_nport_ingestion(months: int = 12) -> dict:
    """Fetch N-PORT holdings for all active managers and upsert to hypertable."""
    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({NPORT_LOCK_ID})")
        )
        if not lock_result.scalar():
            logger.warning("N-PORT ingestion already running (advisory lock not acquired)")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            # Get all managers with CIK (needed for EDGAR lookup)
            result = await db.execute(
                select(SecManager.cik).where(SecManager.cik.isnot(None))
            )
            ciks = [row[0] for row in result.all() if row[0]]

            if not ciks:
                logger.info("nport_no_managers_with_cik")
                return {"status": "completed", "managers": 0, "holdings": 0}

            logger.info("nport_ingestion_start", managers=len(ciks))

            # Import service lazily to avoid circular imports
            from data_providers.sec.nport_service import NportService

            service = NportService(db_session_factory=async_session)

            total_holdings = 0
            errors = 0

            for cik in ciks:
                try:
                    holdings = await service.fetch_holdings(
                        cik, months=months, force_refresh=True,
                    )
                    total_holdings += len(holdings)
                    logger.debug(
                        "nport_cik_complete",
                        cik=cik,
                        holdings=len(holdings),
                    )
                except Exception as exc:
                    errors += 1
                    logger.warning(
                        "nport_cik_failed",
                        cik=cik,
                        error=str(exc),
                    )

            summary = {
                "status": "completed",
                "managers": len(ciks),
                "holdings": total_holdings,
                "errors": errors,
            }
            logger.info("nport_ingestion_complete", **summary)
            return summary

        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({NPORT_LOCK_ID})")
            )


if __name__ == "__main__":
    asyncio.run(run_nport_ingestion())

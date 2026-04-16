"""Worker: universe_auto_import — bulk-populate every active org's
``instruments_org`` from the sanitized global catalog.

* Advisory lock : 900_103 (literal, deterministic)
* Scope         : global — one run covers every active org
* Frequency     : daily 04:00 UTC, scheduled downstream of
                  ``universe_sync`` (900_070, 03:00) and
                  ``universe_sanitization`` (900_063) so
                  ``is_institutional`` reflects the latest sanitization.
* Idempotent    : yes — second invocation with the same catalog
                  snapshot produces zero adds/updates.

The worker is intentionally thin: it reuses
:func:`app.domains.wealth.services.universe_auto_import_service.auto_import_for_org`
so the nightly run and the admin endpoint share one code path.
"""

from __future__ import annotations

import time
from typing import Any

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session
from app.core.tenancy.middleware import set_rls_context
from app.domains.wealth.services.universe_auto_import_service import (
    auto_import_for_org,
    fetch_active_org_ids,
    fetch_qualified_instruments,
)

UNIVERSE_AUTO_IMPORT_LOCK_ID = 900_103

logger: Any = structlog.get_logger()


async def run_universe_auto_import() -> dict[str, Any]:
    """Entry point invoked by the cron CLI.

    Returns a summary dict compatible with the admin inspection route.
    When the advisory lock is contended (another instance still running)
    the function short-circuits with ``skipped=True`` so the scheduler
    can treat it as a no-op rather than an error.
    """
    started = time.monotonic()
    summary: dict[str, Any] = {
        "lock_id": UNIVERSE_AUTO_IMPORT_LOCK_ID,
        "orgs_processed": 0,
        "rows_added": 0,
        "rows_updated": 0,
        "rows_skipped": 0,
        "per_org": [],
    }

    async with async_session() as db:
        got_lock = await db.scalar(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": UNIVERSE_AUTO_IMPORT_LOCK_ID},
        )
        if not got_lock:
            logger.warning(
                "universe_auto_import.lock_contention",
                lock_id=UNIVERSE_AUTO_IMPORT_LOCK_ID,
            )
            return {
                "skipped": True,
                "reason": "lock_contention",
                "lock_id": UNIVERSE_AUTO_IMPORT_LOCK_ID,
            }

        try:
            org_ids = await fetch_active_org_ids(db)
            # Prefetch the qualified global rowset once — the SQL reads
            # only ``instruments_universe`` + ``nav_timeseries`` (both
            # no-RLS) so the result is tenant-agnostic and reused across
            # every org. This avoids re-running the heavy CTE per org.
            qualified = await fetch_qualified_instruments(db)
            logger.info(
                "universe_auto_import.discovered_orgs",
                count=len(org_ids),
                qualified=len(qualified),
            )

            for org_id in org_ids:
                try:
                    await set_rls_context(db, org_id)
                    metrics = await auto_import_for_org(
                        db,
                        org_id,
                        reason="scheduled_run",
                        qualified=qualified,
                    )
                    await db.commit()
                    summary["orgs_processed"] += 1
                    summary["rows_added"] += metrics["added"]
                    summary["rows_updated"] += metrics["updated"]
                    summary["rows_skipped"] += metrics["skipped"]
                    summary["per_org"].append(metrics)
                except Exception:
                    await db.rollback()
                    logger.exception(
                        "universe_auto_import.org_failed",
                        org_id=str(org_id),
                    )
                    # Keep iterating — one poisoned org mustn't starve
                    # the rest. Lock is still held; other orgs run in
                    # fresh transactions.
        finally:
            await db.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": UNIVERSE_AUTO_IMPORT_LOCK_ID},
            )
            await db.commit()

    summary["duration_ms"] = int((time.monotonic() - started) * 1000)
    logger.info("universe_auto_import.completed", **{
        k: v for k, v in summary.items() if k != "per_org"
    })
    return summary


if __name__ == "__main__":  # pragma: no cover — manual smoke test
    import asyncio

    asyncio.run(run_universe_auto_import())

"""Wealth Library — `recent` pins TTL pruning worker.

Phase 1.2 of the Wealth Library sprint
(docs/superpowers/specs/2026-04-08-wealth-library.md §4.4 / §10).

Bounded-growth enforcement for ``wealth_library_pins`` (pin_type =
'recent') — keeps only the 20 most recent pins per (organization_id,
user_id) ordered by ``last_accessed_at DESC``. Older recent pins are
deleted in a single transactional pass.

Hard rules
==========

- ONLY rows with ``pin_type = 'recent'`` are considered. Pins of type
  ``pinned`` and ``starred`` are NEVER deleted by this worker — they
  represent explicit user intent and must persist indefinitely.
- The cleanup runs without an RLS session GUC because the worker
  operates at the platform level. The advisory lock 900_081 prevents
  concurrent runs across processes.
- A single window-function CTE selects every recent row that exceeds
  the 20-row-per-user budget. The DELETE then targets those IDs by
  primary key, which is index-friendly and bounded.

Schedule: every 6h via the ``run-library-pins-ttl`` HTTP trigger
(see ``backend/app/domains/wealth/routes/workers.py``) or any cron
process invoking this module directly.

Usage
-----

    python -m app.domains.wealth.workers.library_pins_ttl
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from sqlalchemy import text

from app.core.db.engine import async_session_factory as async_session

logger = structlog.get_logger()

LIBRARY_PINS_TTL_LOCK_ID = 900_081
RECENT_PINS_PER_USER_LIMIT = 20


async def run_library_pins_ttl() -> dict[str, Any]:
    """Prune ``recent`` pins beyond the per-user limit.

    Returns a summary dict with the number of rows deleted and whether
    the advisory lock was acquired.
    """
    log = logger.bind(worker="library_pins_ttl", lock_id=LIBRARY_PINS_TTL_LOCK_ID)
    log.info("library_pins_ttl.started")

    async with async_session() as db:
        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({LIBRARY_PINS_TTL_LOCK_ID})"),
        )
        acquired = bool(lock_result.scalar())
        if not acquired:
            log.info("library_pins_ttl.skipped", reason="advisory_lock_held")
            return {"status": "skipped", "deleted": 0}

        try:
            # Window-function CTE: rank every 'recent' pin per
            # (organization_id, user_id) by last_accessed_at DESC and
            # delete anything beyond rank N.  The DELETE...USING form
            # is faster than a sub-select because PostgreSQL can plan
            # it as a hash join on the primary key.
            result = await db.execute(
                text(
                    """
                    WITH ranked AS (
                        SELECT
                            id,
                            row_number() OVER (
                                PARTITION BY organization_id, user_id
                                ORDER BY last_accessed_at DESC, created_at DESC
                            ) AS rn
                        FROM wealth_library_pins
                        WHERE pin_type = 'recent'
                    )
                    DELETE FROM wealth_library_pins p
                    USING ranked r
                    WHERE p.id = r.id
                      AND r.rn > :limit
                      AND p.pin_type = 'recent'
                    """,
                ),
                {"limit": RECENT_PINS_PER_USER_LIMIT},
            )
            deleted = result.rowcount or 0
            await db.commit()
            log.info("library_pins_ttl.completed", deleted=deleted)
            return {"status": "completed", "deleted": deleted}
        except Exception:
            await db.rollback()
            log.exception("library_pins_ttl.failed")
            raise
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({LIBRARY_PINS_TTL_LOCK_ID})"),
            )


if __name__ == "__main__":
    asyncio.run(run_library_pins_ttl())

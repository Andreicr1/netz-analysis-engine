"""Alert sweeper worker — auto-dismiss stale portfolio alerts past TTL.

Runs hourly. Uses pg_try_advisory_xact_lock (transaction-scoped) to prevent
concurrent runs. Lock auto-releases on commit/rollback — no manual unlock.
Dismisses alerts where auto_dismiss_at < now() and dismissed_at IS NULL.
Emits write_audit_event per alert (allow_global=False, tenant-scoped).

Lock ID: 900_102 (documented in CLAUDE.md worker table).
"""

from __future__ import annotations

import uuid
import zlib
from datetime import UTC, datetime

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.db.engine import async_session_factory
from app.core.tenancy.middleware import set_rls_context
from app.domains.wealth.models.model_portfolio import PortfolioAlert

logger = structlog.get_logger(__name__)

ALERT_SWEEPER_LOCK_ID = 900_102


def _org_lock_key(organization_id: uuid.UUID | str) -> int:
    """Deterministic per-org lock key via zlib.crc32 (CLAUDE.md §3)."""
    return zlib.crc32(str(organization_id).encode("utf-8")) & 0x7FFFFFFF


async def run_alert_sweeper(org_id: uuid.UUID) -> dict:
    """Auto-dismiss portfolio alerts past auto_dismiss_at.

    Uses pg_try_advisory_xact_lock(class, key) with org-scoped key so
    different organizations can run concurrently. Lock is automatically
    released on commit or rollback — no manual unlock needed.

    Returns dict with status and count of dismissed alerts.
    """
    async with async_session_factory() as db:
        await set_rls_context(db, org_id)

        # Acquire org-scoped xact lock — non-blocking, auto-released on commit/rollback
        org_lock_key = _org_lock_key(org_id)
        lock_result = await db.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_class, :lock_obj)"),
            {"lock_class": ALERT_SWEEPER_LOCK_ID, "lock_obj": org_lock_key},
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.info(
                "alert_sweeper_skipped",
                reason="lock held",
                organization_id=str(org_id),
            )
            return {"status": "skipped", "reason": "lock held", "dismissed": 0}

        count = await _execute_sweep(db, org_id)
        await db.commit()

        logger.info("alert_sweeper_dismissed", count=count)
        return {"status": "completed", "dismissed": count}


async def _execute_sweep(db: AsyncSession, org_id: uuid.UUID) -> int:
    """Sweep expired alerts within advisory lock.

    Does NOT commit — caller commits once after all mutations and audit
    events are written (Q92 atomicity: audit + dismiss in same transaction).
    """
    now = datetime.now(UTC)

    result = await db.execute(
        select(PortfolioAlert).where(
            PortfolioAlert.dismissed_at.is_(None),
            PortfolioAlert.auto_dismiss_at.isnot(None),
            PortfolioAlert.auto_dismiss_at < now,
        ),
    )
    candidates = result.scalars().all()

    if not candidates:
        logger.info("alert_sweeper_no_expired")
        return 0

    for alert in candidates:
        alert.dismissed_at = now
        alert.dismissed_by = "system:alert_sweeper"

        await write_audit_event(
            db,
            action="portfolio_alert.auto_dismissed",
            entity_type="portfolio_alert",
            entity_id=str(alert.id),
            actor_id="system:alert_sweeper",
            before={"dismissed_at": None},
            after={
                "dismissed_at": now.isoformat(),
                "dismissed_by": "system:alert_sweeper",
            },
            allow_global=False,
        )

    return len(candidates)

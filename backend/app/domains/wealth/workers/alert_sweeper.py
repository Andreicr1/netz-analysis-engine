"""Alert sweeper worker — auto-dismiss stale portfolio alerts past TTL.

Runs hourly. Uses pg_try_advisory_lock to prevent concurrent runs.
Dismisses alerts where auto_dismiss_at < now() and dismissed_at IS NULL.
Emits write_audit_event per alert (allow_global=False, tenant-scoped).

Lock ID: 900_102 (documented in CLAUDE.md worker table).
"""

from __future__ import annotations

import uuid
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


async def run_alert_sweeper(org_id: uuid.UUID) -> dict:
    """Auto-dismiss portfolio alerts past auto_dismiss_at.

    Returns dict with status and count of dismissed alerts.
    """
    async with async_session_factory() as db:
        await set_rls_context(db, org_id)

        lock_result = await db.execute(
            text(f"SELECT pg_try_advisory_lock({ALERT_SWEEPER_LOCK_ID})"),
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("alert_sweeper_skipped", reason="lock held")
            return {"status": "skipped", "reason": "lock held", "dismissed": 0}

        try:
            return await _execute_sweep(db, org_id)
        except Exception:
            await db.rollback()
            raise
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({ALERT_SWEEPER_LOCK_ID})"),
            )


async def _execute_sweep(db: AsyncSession, org_id: uuid.UUID) -> dict:
    """Sweep expired alerts within advisory lock."""
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
        return {"status": "completed", "dismissed": 0}

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

    await db.commit()
    await set_rls_context(db, org_id)

    logger.info("alert_sweeper_dismissed", count=len(candidates))
    return {"status": "completed", "dismissed": len(candidates)}

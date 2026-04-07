"""Fast-Track Eviction worker — daily revocation of degraded fast-tracked funds.

Iterates over every active organization and invokes
``vertical_engines.wealth.asset_universe.eviction_service.process_fast_track_evictions``
to revoke fast-tracked Universe approvals whose latest ``manager_score`` has
dropped below the eviction threshold.

Usage:
    python -m app.workers.cli fast_track_eviction
    # or directly:
    python -m app.domains.wealth.workers.fast_track_eviction

Advisory lock ID: 900_009 — global, prevents two evictions running concurrently.
Per-org failures are isolated: a crash on one org_id never blocks the next.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy import select, text, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.engine import async_session_factory
from app.core.tenancy.middleware import set_rls_context
from vertical_engines.wealth.asset_universe.eviction_service import (
    process_fast_track_evictions,
)

logger = structlog.get_logger(__name__)

FAST_TRACK_EVICTION_LOCK_ID: int = 900_009


async def run_fast_track_eviction() -> dict[str, Any]:
    """Daily entry point — revokes degraded fast-tracked approvals across orgs.

    Acquires a non-blocking advisory lock so concurrent cron triggers no-op
    instead of double-revoking. Iterates active organizations sequentially;
    each org gets its own RLS-scoped transaction so a failure on one tenant
    is contained and reported but does not abort the sweep.

    Returns:
        Summary dict with totals and per-org breakdown — useful for
        observability dashboards and the worker_registry callsite.
    """
    logger.info("fast_track_eviction.start")

    async with async_session_factory() as db:
        lock_acquired = await db.scalar(
            text(f"SELECT pg_try_advisory_lock({FAST_TRACK_EVICTION_LOCK_ID})"),
        )
        if not lock_acquired:
            logger.warning("fast_track_eviction.lock_held")
            return {"status": "skipped", "reason": "lock_held"}

        try:
            org_ids = await _get_active_org_ids(db)
            logger.info("fast_track_eviction.org_count", count=len(org_ids))

            total_revoked = 0
            org_failures = 0
            per_org: dict[str, int] = {}

            for org_id in org_ids:
                try:
                    revoked = await _process_single_org(org_id)
                    per_org[str(org_id)] = revoked
                    total_revoked += revoked
                except Exception:
                    org_failures += 1
                    logger.exception(
                        "fast_track_eviction.org_failed",
                        org_id=str(org_id),
                    )

            summary: dict[str, Any] = {
                "status": "completed",
                "orgs_scanned": len(org_ids),
                "orgs_failed": org_failures,
                "total_revoked": total_revoked,
                "per_org": per_org,
            }
            logger.info("fast_track_eviction.summary", **summary)
            return summary
        finally:
            await db.execute(
                text(f"SELECT pg_advisory_unlock({FAST_TRACK_EVICTION_LOCK_ID})"),
            )


async def _process_single_org(org_id: uuid.UUID) -> int:
    """Run eviction for one org in its own session/transaction.

    Each org gets a fresh AsyncSession so RLS context, commits and rollbacks
    are fully isolated. Returns the number of instruments revoked.
    """
    async with async_session_factory() as session:
        await set_rls_context(session, org_id)
        try:
            revoked = await process_fast_track_evictions(session, org_id)
            await session.commit()
            return revoked
        except Exception:
            await session.rollback()
            raise


async def _get_active_org_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Discover active organizations.

    Mirrors :func:`app.workers.cli._get_active_org_ids` — unions
    ``vertical_config_overrides`` and ``tenant_assets`` so any tenant that has
    ever been provisioned is swept. Imported lazily to dodge import cycles.
    """
    from app.core.config.models import VerticalConfigOverride
    from app.domains.admin.models import TenantAsset

    stmt = union(
        select(VerticalConfigOverride.organization_id),
        select(TenantAsset.organization_id),
    )
    result = await db.execute(select(stmt.subquery().c.organization_id))
    return [row[0] for row in result.all() if row[0] is not None]


if __name__ == "__main__":
    asyncio.run(run_fast_track_eviction())

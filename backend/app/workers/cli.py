"""Railway Cron CLI — thin wrapper to invoke workers by name.

Usage:
    python -m app.workers.cli macro_ingestion
    python -m app.workers.cli risk_calc

For org-scoped workers, queries all active organizations and runs
the worker once per org (same behavior as the /internal/workers/dispatch
endpoint).

Exit codes:
    0 — all workers completed (or skipped via advisory lock)
    1 — invalid worker name or unhandled exception
"""

from __future__ import annotations

import asyncio
import sys
import time

import structlog

logger = structlog.get_logger()


async def _get_active_org_ids() -> list:
    """Get distinct organization IDs from config overrides and tenant assets."""
    from sqlalchemy import select, union

    from app.core.config.models import VerticalConfigOverride
    from app.core.db.engine import async_session_factory
    from app.domains.admin.models import TenantAsset

    async with async_session_factory() as db:
        stmt = union(
            select(VerticalConfigOverride.organization_id),
            select(TenantAsset.organization_id),
        )
        result = await db.execute(select(stmt.subquery().c.organization_id))
        return [row[0] for row in result.all()]


async def run(worker_name: str) -> None:
    """Look up and execute a worker by name."""
    from app.domains.admin.routes.worker_registry import get_worker_registry

    registry = get_worker_registry()
    entry = registry.get(worker_name)
    if entry is None:
        logger.error("worker.unknown", worker=worker_name)
        sys.exit(1)

    coro_fn, scope_type, timeout = entry
    log = logger.bind(worker=worker_name, scope=scope_type, timeout=timeout)
    log.info("cli.start")
    t0 = time.monotonic()

    try:
        if scope_type == "global":
            await asyncio.wait_for(coro_fn(), timeout=timeout)
        elif scope_type == "org":
            org_ids = await _get_active_org_ids()
            log.info("cli.org_ids", count=len(org_ids))
            for org_id in org_ids:
                await asyncio.wait_for(coro_fn(org_id), timeout=timeout)
        else:
            log.error("cli.unknown_scope", scope=scope_type)
            sys.exit(1)

        duration = round(time.monotonic() - t0, 2)
        log.info("cli.done", duration_seconds=duration)
    except asyncio.TimeoutError:
        duration = round(time.monotonic() - t0, 2)
        log.error("cli.timeout", duration_seconds=duration)
        sys.exit(1)
    except Exception:
        duration = round(time.monotonic() - t0, 2)
        log.exception("cli.failed", duration_seconds=duration)
        sys.exit(1)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m app.workers.cli <worker_name>")  # noqa: T201
        sys.exit(1)
    worker_name = sys.argv[1]
    asyncio.run(run(worker_name))


if __name__ == "__main__":
    main()

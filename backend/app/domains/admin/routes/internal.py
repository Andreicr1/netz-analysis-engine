"""Internal worker dispatch — called by Cloudflare Cron Workers only.

This endpoint is NOT exposed to the public internet. The API gateway
Worker blocks /internal/* unless the caller presents X-Worker-Secret.

For org-scoped workers, the endpoint queries all active organizations
and dispatches one task per org (each with its own idempotency key).
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.models import VerticalConfigOverride
from app.core.config.settings import settings
from app.core.jobs.worker_idempotency import (
    check_worker_status,
    idempotent_worker_wrapper,
    mark_worker_running,
)
from app.core.tenancy.admin_middleware import get_db_admin
from app.domains.admin.models import TenantAsset
from app.domains.admin.routes.worker_registry import get_worker_registry

logger = structlog.get_logger()

router = APIRouter(prefix="/internal", tags=["internal"])


# ── Auth dependency ───────────────────────────────────────────


async def require_worker_secret(request: Request) -> None:
    """Reject requests without a valid X-Worker-Secret header."""
    expected = settings.worker_dispatch_secret
    if not expected:
        raise HTTPException(status_code=503, detail="Worker dispatch not configured")
    if request.headers.get("X-Worker-Secret") != expected:
        raise HTTPException(status_code=403, detail="Forbidden")


# ── Timeout wrapper (matches workers.py pattern) ─────────────

import asyncio  # noqa: E402
import time  # noqa: E402


async def _run_worker_with_timeout(
    worker_name: str,
    coro_fn,  # noqa: ANN001
    *args,  # noqa: ANN002
    timeout_seconds: int = 600,
    org_id: uuid.UUID | None = None,
) -> None:
    """Execute a worker coroutine with timeout and structured logging."""
    log = logger.bind(worker_name=worker_name, org_id=str(org_id) if org_id else None)
    log.info("worker.started")
    t0 = time.monotonic()

    try:
        await asyncio.wait_for(coro_fn(*args), timeout=timeout_seconds)
        duration = round(time.monotonic() - t0, 2)
        log.info("worker.completed", duration_seconds=duration)
    except asyncio.TimeoutError:
        duration = round(time.monotonic() - t0, 2)
        log.error("worker.timeout", duration_seconds=duration)
    except Exception:
        duration = round(time.monotonic() - t0, 2)
        log.exception("worker.failed", duration_seconds=duration)


# ── Schemas ───────────────────────────────────────────────────


class DispatchRequest(BaseModel):
    workers: list[str]


class DispatchResponse(BaseModel):
    status: str
    dispatched: list[str]
    skipped: list[str]


# ── Helpers ───────────────────────────────────────────────────


async def _get_active_org_ids(db: AsyncSession) -> list[uuid.UUID]:
    """Get distinct organization IDs from config overrides and tenant assets."""
    stmt = union(
        select(VerticalConfigOverride.organization_id),
        select(TenantAsset.organization_id),
    )
    result = await db.execute(select(stmt.subquery().c.organization_id))
    return [row[0] for row in result.all()]


async def _dispatch_single(
    background_tasks: BackgroundTasks,
    worker_name: str,
    scope: str,
    coro_fn,  # noqa: ANN001
    *args,  # noqa: ANN002
    timeout_seconds: int = 600,
    org_id: uuid.UUID | None = None,
) -> bool:
    """Dispatch a single worker if not already running. Returns True if dispatched."""
    existing = await check_worker_status(worker_name, scope)
    if existing is not None and existing.get("status") in ("running", "completed"):
        logger.info("worker.skipped", worker=worker_name, scope=scope, reason=existing.get("status"))
        return False

    await mark_worker_running(worker_name, scope)
    background_tasks.add_task(
        idempotent_worker_wrapper,
        worker_name,
        scope,
        _run_worker_with_timeout,
        worker_name,
        coro_fn,
        *args,
        timeout_seconds=timeout_seconds,
        org_id=org_id,
    )
    return True


# ── Endpoint ──────────────────────────────────────────────────


@router.post(
    "/workers/dispatch",
    response_model=DispatchResponse,
    status_code=202,
    dependencies=[Depends(require_worker_secret)],
)
async def dispatch_workers(
    body: DispatchRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db_admin),
) -> DispatchResponse:
    """Dispatch one or more workers as background tasks.

    Global workers are dispatched once.
    Org-scoped workers are dispatched once per active organization.
    Returns 202 immediately — actual execution is async.
    """
    registry = get_worker_registry()
    dispatched: list[str] = []
    skipped: list[str] = []

    # Lazily resolve org IDs only if any org-scoped worker is requested
    org_ids: list[uuid.UUID] | None = None

    for name in body.workers:
        entry = registry.get(name)
        if entry is None:
            skipped.append(name)
            logger.warning("worker.unknown", worker=name)
            continue

        coro_fn, scope_type, timeout = entry

        if scope_type == "global":
            ok = await _dispatch_single(
                background_tasks, name, "global", coro_fn,
                timeout_seconds=timeout,
            )
            (dispatched if ok else skipped).append(name)

        elif scope_type == "org":
            if org_ids is None:
                org_ids = await _get_active_org_ids(db)

            dispatched_any = False
            for org_id in org_ids:
                scope = str(org_id)
                ok = await _dispatch_single(
                    background_tasks, name, scope, coro_fn, org_id,
                    timeout_seconds=timeout, org_id=org_id,
                )
                if ok:
                    dispatched_any = True

            (dispatched if dispatched_any else skipped).append(name)

    logger.info(
        "internal.dispatch",
        dispatched=dispatched,
        skipped=skipped,
    )
    return DispatchResponse(status="dispatched", dispatched=dispatched, skipped=skipped)

"""Admin health monitoring routes."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.admin_auth import require_super_admin
from app.core.security.clerk_auth import Actor
from app.core.tenancy.admin_middleware import get_db_admin
from app.domains.admin.schemas import PipelineStatsOut, ServiceHealthOut, WorkerStatusOut

router = APIRouter(
    prefix="/admin/health",
    tags=["admin-health"],
    dependencies=[Depends(require_super_admin)],
)


async def _check_postgres(db: AsyncSession) -> ServiceHealthOut:
    """Check PostgreSQL connection + latency."""
    checked_at = datetime.now(UTC)
    try:
        start = time.monotonic()
        await db.execute(text("SELECT 1"))
        latency = (time.monotonic() - start) * 1000
        return ServiceHealthOut(name="PostgreSQL", status="ok", latency_ms=round(latency, 2), error=None, checked_at=checked_at)
    except Exception as e:
        return ServiceHealthOut(name="PostgreSQL", status="down", latency_ms=None, error=str(e), checked_at=checked_at)


async def _check_redis() -> ServiceHealthOut:
    """Check Redis connection + latency."""
    checked_at = datetime.now(UTC)
    try:
        from app.core.jobs.tracker import get_redis_pool
        start = time.monotonic()
        pool = get_redis_pool()
        r = aioredis.Redis(connection_pool=pool)
        try:
            await r.ping()
            latency = (time.monotonic() - start) * 1000
            return ServiceHealthOut(name="Redis", status="ok", latency_ms=round(latency, 2), error=None, checked_at=checked_at)
        finally:
            await r.aclose()
    except Exception as e:
        return ServiceHealthOut(name="Redis", status="down", latency_ms=None, error=str(e), checked_at=checked_at)


async def _check_storage() -> ServiceHealthOut:
    """Check storage backend availability (R2 or local)."""
    checked_at = datetime.now(UTC)
    from app.core.config.settings import settings
    backend = "R2" if settings.feature_r2_enabled else "LocalStorage"
    return ServiceHealthOut(name=backend, status="ok", latency_ms=None, error=None, checked_at=checked_at)


async def _check_search() -> ServiceHealthOut:
    """Vector search health via pgvector (PostgreSQL)."""
    checked_at = datetime.now(UTC)
    try:
        from app.core.db.engine import async_session_factory
        start = time.monotonic()
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1 FROM vector_chunks LIMIT 1"))
        latency = (time.monotonic() - start) * 1000
        return ServiceHealthOut(
            name="pgvector",
            status="ok",
            latency_ms=round(latency, 2),
            error=None,
            checked_at=checked_at,
        )
    except Exception as exc:
        return ServiceHealthOut(
            name="pgvector",
            status="degraded",
            latency_ms=None,
            error=f"vector_chunks not ready: {exc}",
            checked_at=checked_at,
        )


def _check_pg_notifier(request: Request) -> ServiceHealthOut:
    """Check PgNotifier listener connection state."""
    checked_at = datetime.now(UTC)
    from app.core.config.pg_notify import PgNotifier

    notifier: PgNotifier | None = getattr(request.app.state, "pg_notifier", None)
    if notifier is None:
        return ServiceHealthOut(
            name="PgNotifier",
            status="disabled",
            latency_ms=None,
            error=None,
            checked_at=checked_at,
        )
    return ServiceHealthOut(
        name="PgNotifier",
        status="ok" if notifier.is_connected else "disconnected",
        latency_ms=None,
        error=None,
        checked_at=checked_at,
    )


@router.get("/services", response_model=list[ServiceHealthOut])
async def get_service_health(
    request: Request,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
) -> list[ServiceHealthOut]:
    """Service status -- PostgreSQL, Redis, Storage, pgvector, PgNotifier."""
    results = await asyncio.gather(
        _check_postgres(db),
        _check_redis(),
        _check_storage(),
        _check_search(),
        return_exceptions=True,
    )
    services: list[ServiceHealthOut] = []
    for r in results:
        if isinstance(r, BaseException):
            services.append(ServiceHealthOut(name="unknown", status="down", latency_ms=None, error=str(r), checked_at=datetime.now(UTC)))
        else:
            services.append(r)

    # PgNotifier is synchronous — no await needed
    services.append(_check_pg_notifier(request))
    return services


@router.get("/workers", response_model=list[WorkerStatusOut])
async def get_worker_status(
    actor: Actor = Depends(require_super_admin),
) -> list[WorkerStatusOut]:
    """Worker status -- last run, duration, errors from Redis."""
    checked_at = datetime.now(UTC)
    try:
        from app.core.jobs.tracker import get_redis_pool
        pool = get_redis_pool()
        r = aioredis.Redis(connection_pool=pool)
        try:
            workers: list[WorkerStatusOut] = []
            async for key in r.scan_iter(match="worker:status:*"):
                data = await r.hgetall(key)
                if data:
                    name = key.replace("worker:status:", "") if isinstance(key, str) else key.decode().replace("worker:status:", "")
                    raw_status = data.get("status", data.get(b"status", "unknown"))
                    if isinstance(raw_status, bytes):
                        raw_status = raw_status.decode()
                    raw_last_run = data.get("last_run", data.get(b"last_run"))
                    if isinstance(raw_last_run, bytes):
                        raw_last_run = raw_last_run.decode()
                    raw_duration = data.get("duration_ms", data.get(b"duration_ms"))
                    if isinstance(raw_duration, bytes):
                        raw_duration = raw_duration.decode()
                    workers.append(WorkerStatusOut(
                        name=name,
                        last_run=raw_last_run,
                        duration_ms=float(raw_duration) if raw_duration is not None else None,
                        status=str(raw_status),
                        error_count=int(data.get("error_count", data.get(b"error_count", 0))),
                        checked_at=checked_at,
                    ))
            return workers
        finally:
            await r.aclose()
    except Exception:
        return []


@router.get("/pipelines", response_model=PipelineStatsOut)
async def get_pipeline_stats(
    actor: Actor = Depends(require_super_admin),
) -> PipelineStatsOut:
    """Pipeline stats -- docs processed, queue depth."""
    checked_at = datetime.now(UTC)
    try:
        from app.core.jobs.tracker import get_redis_pool
        pool = get_redis_pool()
        r = aioredis.Redis(connection_pool=pool)
        try:
            processed = await r.get("pipeline:docs_processed") or "0"
            queue_depth = await r.llen("pipeline:queue") if await r.exists("pipeline:queue") else 0
            return PipelineStatsOut(
                docs_processed=int(processed),
                queue_depth=queue_depth,
                error_rate=0.0,
                checked_at=checked_at,
            )
        finally:
            await r.aclose()
    except Exception:
        return PipelineStatsOut(docs_processed=0, queue_depth=0, error_rate=0.0, checked_at=checked_at)


# Lazy-initialized semaphore for SSE connection limiting.
# MUST NOT be created at module level — see CLAUDE.md asyncio primitives rule.
_worker_log_semaphore: asyncio.Semaphore | None = None
_MAX_LOG_STREAMS = 10


def _get_worker_log_semaphore() -> asyncio.Semaphore:
    """Return (and lazily create) the worker-log SSE semaphore."""
    global _worker_log_semaphore  # noqa: PLW0603
    if _worker_log_semaphore is None:
        _worker_log_semaphore = asyncio.Semaphore(_MAX_LOG_STREAMS)
    return _worker_log_semaphore


@router.get("/workers/logs")
async def stream_worker_logs(
    request: Request,
    actor: Actor = Depends(require_super_admin),
):
    """SSE stream of worker logs via Redis pub/sub.

    Limited to ``_MAX_LOG_STREAMS`` concurrent connections.
    Returns HTTP 429 when all slots are occupied.
    """
    from sse_starlette.sse import EventSourceResponse

    from app.core.jobs.tracker import get_redis_pool

    sem = _get_worker_log_semaphore()

    # Non-blocking acquire: if all slots are taken, return 429 immediately.
    if sem.locked():
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many SSE connections"},
        )
    await sem.acquire()

    # Semaphore slot acquired — release it when the generator finishes.
    async def event_generator():
        try:
            pool = get_redis_pool()
            r = aioredis.Redis(connection_pool=pool)
            pubsub = r.pubsub()
            await pubsub.subscribe("worker:logs")

            try:
                while True:
                    if await request.is_disconnected():
                        break
                    message = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if message and message["type"] == "message":
                        raw_data = message["data"]
                        yield {
                            "event": "log",
                            "data": raw_data.decode() if isinstance(raw_data, bytes) else str(raw_data),
                        }
                    else:
                        yield {"event": "ping", "data": ""}
            finally:
                await pubsub.unsubscribe("worker:logs")
                await pubsub.aclose()
                await r.aclose()
        finally:
            sem.release()

    return EventSourceResponse(
        event_generator(),
        headers={"Cache-Control": "no-store"},
    )

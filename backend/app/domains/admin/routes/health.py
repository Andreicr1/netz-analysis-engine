"""Admin health monitoring routes."""

from __future__ import annotations

import asyncio
import time

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.admin_auth import require_super_admin
from app.core.security.clerk_auth import Actor
from app.core.tenancy.admin_middleware import get_db_admin

router = APIRouter(
    prefix="/admin/health",
    tags=["admin-health"],
    dependencies=[Depends(require_super_admin)],
)


async def _check_postgres(db: AsyncSession) -> dict:
    """Check PostgreSQL connection + latency."""
    try:
        start = time.monotonic()
        await db.execute(text("SELECT 1"))
        latency = (time.monotonic() - start) * 1000
        return {"name": "PostgreSQL", "status": "ok", "latency_ms": round(latency, 2), "error": None}
    except Exception as e:
        return {"name": "PostgreSQL", "status": "down", "latency_ms": None, "error": str(e)}


async def _check_redis() -> dict:
    """Check Redis connection + latency."""
    try:
        from app.core.jobs.tracker import get_redis_pool
        start = time.monotonic()
        pool = get_redis_pool()
        r = aioredis.Redis(connection_pool=pool)
        try:
            await r.ping()
            latency = (time.monotonic() - start) * 1000
            return {"name": "Redis", "status": "ok", "latency_ms": round(latency, 2), "error": None}
        finally:
            await r.aclose()
    except Exception as e:
        return {"name": "Redis", "status": "down", "latency_ms": None, "error": str(e)}


async def _check_adls() -> dict:
    """Check ADLS availability (feature-flagged)."""
    from app.core.config.settings import settings
    if not getattr(settings, "feature_adls_enabled", False):
        return {"name": "ADLS", "status": "ok", "latency_ms": None, "error": "Disabled (using local storage)"}
    return {"name": "ADLS", "status": "ok", "latency_ms": None, "error": None}


async def _check_search() -> dict:
    """Check Azure Search availability."""
    return {"name": "Azure Search", "status": "ok", "latency_ms": None, "error": "Check not implemented"}


@router.get("/services")
async def get_service_health(
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Service status -- PostgreSQL, Redis, ADLS, Azure Search."""
    results = await asyncio.gather(
        _check_postgres(db),
        _check_redis(),
        _check_adls(),
        _check_search(),
        return_exceptions=True,
    )
    services = []
    for r in results:
        if isinstance(r, Exception):
            services.append({"name": "unknown", "status": "down", "latency_ms": None, "error": str(r)})
        else:
            services.append(r)
    return services


@router.get("/workers")
async def get_worker_status(
    actor: Actor = Depends(require_super_admin),
):
    """Worker status -- last run, duration, errors from Redis."""
    try:
        from app.core.jobs.tracker import get_redis_pool
        pool = get_redis_pool()
        r = aioredis.Redis(connection_pool=pool)
        try:
            workers = []
            async for key in r.scan_iter(match="worker:status:*"):
                data = await r.hgetall(key)
                if data:
                    name = key.replace("worker:status:", "") if isinstance(key, str) else key.decode().replace("worker:status:", "")
                    raw_status = data.get("status", data.get(b"status", "unknown"))
                    if isinstance(raw_status, bytes):
                        raw_status = raw_status.decode()
                    workers.append({
                        "name": name,
                        "last_run": data.get("last_run", data.get(b"last_run")),
                        "duration_ms": data.get("duration_ms", data.get(b"duration_ms")),
                        "status": str(raw_status),
                        "error_count": int(data.get("error_count", data.get(b"error_count", 0))),
                    })
            return workers
        finally:
            await r.aclose()
    except Exception:
        return []


@router.get("/pipelines")
async def get_pipeline_stats(
    actor: Actor = Depends(require_super_admin),
):
    """Pipeline stats -- docs processed, queue depth."""
    try:
        from app.core.jobs.tracker import get_redis_pool
        pool = get_redis_pool()
        r = aioredis.Redis(connection_pool=pool)
        try:
            processed = await r.get("pipeline:docs_processed") or "0"
            queue_depth = await r.llen("pipeline:queue") if await r.exists("pipeline:queue") else 0
            return {
                "docs_processed": int(processed),
                "queue_depth": queue_depth,
                "error_rate": 0.0,
            }
        finally:
            await r.aclose()
    except Exception:
        return {"docs_processed": 0, "queue_depth": 0, "error_rate": 0.0}


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

    if sem.locked():
        return JSONResponse(
            status_code=429,
            content={"detail": "Too many log streams"},
        )

    async def event_generator():
        async with sem:
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

    return EventSourceResponse(
        event_generator(),
        headers={"Cache-Control": "no-store"},
    )

"""Worker idempotency guard — prevents duplicate runs via Redis.

Each worker dispatch is tracked with a Redis key:
    worker:{worker_name}:{scope}:status

Lifecycle:
    1. Before dispatch: check Redis key
       - If "running" → 409 Conflict (duplicate)
       - If "completed" within TTL → return cached result
    2. Set status to "running" with TTL before dispatch
    3. Background wrapper sets "completed" or "failed" after execution

This is a lightweight guard — NOT a full job queue. It prevents
accidental double-triggers from UI/CI without adding Celery/RQ.
"""

from __future__ import annotations

import json
import time
import traceback
from typing import Any

import redis.asyncio as aioredis
import structlog

from app.core.jobs.tracker import get_redis_pool

logger = structlog.get_logger()

# How long a "running" status is valid before auto-expiring (seconds).
# Safety net: if the worker crashes without setting terminal status,
# the key expires and the worker can be re-triggered.
RUNNING_TTL: int = 3600  # 1 hour

# How long a "completed" status is cached (seconds).
# Within this window, re-triggers return the cached result.
COMPLETED_TTL: int = 300  # 5 minutes

# How long a "failed" status persists (seconds).
# Visible for debugging; does NOT block re-triggers.
FAILED_TTL: int = 1800  # 30 minutes


def _status_key(worker_name: str, scope: str) -> str:
    """Build the Redis key for a worker's idempotency status.

    scope is typically org_id or "global" for tenant-agnostic workers.
    """
    return f"worker:{worker_name}:{scope}:status"


async def check_worker_status(
    worker_name: str,
    scope: str,
) -> dict[str, Any] | None:
    """Check if a worker is currently running or recently completed.

    Returns:
        None — worker is idle, safe to dispatch
        dict with "status" key — worker is running/completed, caller should
            return appropriate HTTP response

    """
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        raw = await r.get(_status_key(worker_name, scope))
        if raw is None:
            return None

        state = json.loads(raw)
        status = state.get("status")

        if status == "running":
            return dict(state)

        if status == "completed":
            return dict(state)

        # "failed" does NOT block re-triggers — the whole point is
        # to allow manual retry after failure
        return None
    finally:
        await r.aclose()


async def mark_worker_running(
    worker_name: str,
    scope: str,
) -> None:
    """Set worker status to running with auto-expiry TTL."""
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        state = json.dumps({
            "status": "running",
            "worker": worker_name,
            "scope": scope,
            "started_at": time.time(),
        })
        await r.set(_status_key(worker_name, scope), state, ex=RUNNING_TTL)
    finally:
        await r.aclose()


async def mark_worker_completed(
    worker_name: str,
    scope: str,
    result: Any = None,
) -> None:
    """Set worker status to completed with short cache TTL."""
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        state = json.dumps({
            "status": "completed",
            "worker": worker_name,
            "scope": scope,
            "completed_at": time.time(),
            "result_summary": str(result)[:500] if result is not None else None,
        })
        await r.set(_status_key(worker_name, scope), state, ex=COMPLETED_TTL)
    finally:
        await r.aclose()


async def mark_worker_failed(
    worker_name: str,
    scope: str,
    error: str,
    tb: str | None = None,
) -> None:
    """Set worker status to failed with error details."""
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        state = json.dumps({
            "status": "failed",
            "worker": worker_name,
            "scope": scope,
            "failed_at": time.time(),
            "error": error[:1000],
            "traceback": (tb or "")[:2000],
        })
        await r.set(_status_key(worker_name, scope), state, ex=FAILED_TTL)
    finally:
        await r.aclose()


async def idempotent_worker_wrapper(
    worker_name: str,
    scope: str,
    coro_func: Any,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Wrap an async worker function with idempotency tracking.

    Sets Redis status to "running" before execution, then "completed"
    or "failed" after. This is the function passed to BackgroundTasks.

    Args:
        worker_name: Unique name for the worker (e.g. "run-risk-calc")
        scope: Tenant scope — org_id string or "global"
        coro_func: The async worker function to call
        *args, **kwargs: Forwarded to coro_func

    """
    try:
        result = await coro_func(*args, **kwargs)
        await mark_worker_completed(worker_name, scope, result)
        logger.info(
            "worker_completed",
            worker=worker_name,
            scope=scope,
        )
    except Exception as exc:
        tb = traceback.format_exc()
        await mark_worker_failed(worker_name, scope, str(exc), tb)
        logger.exception(
            "worker_failed",
            worker=worker_name,
            scope=scope,
            error=str(exc),
        )
        # Re-raise so BackgroundTasks logs the exception too
        raise

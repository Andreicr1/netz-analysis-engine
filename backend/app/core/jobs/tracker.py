"""Job Progress Tracker — Redis Pub/Sub
======================================

Workers publish progress events to Redis channels.
SSE endpoints subscribe and stream to clients.

Channel convention: job:{job_id}:events

Ownership lifecycle (ASYNC-01):
  register_job_owner()   — sets job:{id}:org with TTL on dispatch
  refresh_job_owner_ttl() — extends TTL for long-running active jobs
  clear_job_owner()      — removes ownership key on terminal state
  publish_terminal_event() — publishes event AND clears ownership atomically
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import redis.asyncio as aioredis

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

# Default ownership TTL in seconds (1 hour).
# Active jobs refresh this before expiry; terminal jobs clear it immediately.
DEFAULT_OWNERSHIP_TTL: int = 3600

# Terminal event types that signal a job has finished.
# Used by publish_terminal_event() and SSE stream to know when to stop.
TERMINAL_EVENT_TYPES: frozenset[str] = frozenset({
    "done",
    "error",
    "ingestion_complete",
    "memo_complete",
    "report_completed",
    "report_failed",
})

# How long to keep the ownership key after terminal state (seconds).
# Allows final SSE delivery before the key disappears.
TERMINAL_CLEANUP_TTL: int = 120

_redis_pool: aioredis.ConnectionPool | None = None


def get_redis_pool() -> aioredis.ConnectionPool:
    """Lazy-init shared Redis connection pool."""
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = aioredis.ConnectionPool.from_url(
            settings.redis_url,
            max_connections=100,
            decode_responses=True,
        )
    return _redis_pool


async def close_redis_pool() -> None:
    """Close the pool — call during app shutdown."""
    global _redis_pool
    if _redis_pool is not None:
        await _redis_pool.aclose()
        _redis_pool = None


def _channel_name(job_id: str) -> str:
    return f"job:{job_id}:events"


async def register_job_owner(
    job_id: str,
    organization_id: str,
    ttl_seconds: int = DEFAULT_OWNERSHIP_TTL,
) -> None:
    """Store job->org mapping in Redis for SSE tenant authorization."""
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        await r.set(f"job:{job_id}:org", organization_id, ex=ttl_seconds)
    finally:
        await r.aclose()


async def refresh_job_owner_ttl(
    job_id: str,
    ttl_seconds: int = DEFAULT_OWNERSHIP_TTL,
) -> bool:
    """Extend the ownership key TTL for a long-running active job.

    Returns True if the key existed and was refreshed, False if already expired.
    Workers should call this periodically (e.g. every 15-30 min) for jobs
    that may exceed the default 1-hour TTL.
    """
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        # EXPIRE returns True if the key exists, False otherwise
        refreshed = await r.expire(f"job:{job_id}:org", ttl_seconds)
        if not refreshed:
            logger.warning("job_ttl_refresh_key_missing job_id=%s", job_id)
        return bool(refreshed)
    finally:
        await r.aclose()


async def clear_job_owner(
    job_id: str,
    grace_ttl: int = TERMINAL_CLEANUP_TTL,
) -> None:
    """Expire the ownership key after a terminal event.

    Instead of immediate deletion, set a short grace TTL so clients that
    reconnect within the grace window can still verify ownership for final
    event delivery.  After grace_ttl seconds, the key auto-expires.
    """
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        await r.expire(f"job:{job_id}:org", grace_ttl)
    finally:
        await r.aclose()


async def verify_job_owner(job_id: str, organization_id: str) -> bool:
    """Check if job belongs to the given organization.

    Returns False when no mapping exists (expired or never set) — deny by default.
    """
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        owner = await r.get(f"job:{job_id}:org")
        if owner is None:
            logger.warning("job_owner_missing job_id=%s org_id=%s", job_id, organization_id)
            return False
        # Pool uses decode_responses=True, so owner is already str
        return bool(owner == organization_id)
    finally:
        await r.aclose()


async def publish_event(
    job_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    """Publish a progress event to the job's Redis channel."""
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        payload = json.dumps({"event": event_type, **(data or {})})
        await r.publish(_channel_name(job_id), payload)
    except Exception:
        logger.warning(
            "sse_publish_failed job_id=%s event_type=%s",
            job_id,
            event_type,
            exc_info=True,
        )
        raise
    finally:
        await r.aclose()


async def publish_terminal_event(
    job_id: str,
    event_type: str,
    data: dict[str, Any] | None = None,
    grace_ttl: int = TERMINAL_CLEANUP_TTL,
) -> None:
    """Publish a terminal event and schedule ownership key cleanup.

    Combines publish_event + clear_job_owner in a single call so callers
    cannot forget to clean up.  The ownership key gets a short grace TTL
    (default 120s) allowing final reconnect delivery before auto-expiry.
    """
    await publish_event(job_id, event_type, data)
    await clear_job_owner(job_id, grace_ttl=grace_ttl)


async def persist_job_state(
    job_id: str,
    *,
    terminal_state: str,
    attempted_chunk_count: int = 0,
    successful_chunk_count: int = 0,
    failed_chunk_count: int = 0,
    retryable: bool = False,
    errors: list[str] | None = None,
    ttl_seconds: int = 86400,
) -> None:
    """Persist terminal job state in Redis so clients can query final outcome.

    Terminal states: ``success``, ``degraded``, ``failed``.
    The ``degraded`` state indicates partial chunk persistence — some chunks
    were indexed but others failed. Clients use this to distinguish full
    success from partial persistence without inspecting logs.
    """
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        state = json.dumps({
            "job_id": job_id,
            "terminal_state": terminal_state,
            "attempted_chunk_count": attempted_chunk_count,
            "successful_chunk_count": successful_chunk_count,
            "failed_chunk_count": failed_chunk_count,
            "retryable": retryable,
            "errors": errors or [],
        })
        await r.set(f"job:{job_id}:state", state, ex=ttl_seconds)
    finally:
        await r.aclose()


async def get_job_state(job_id: str) -> dict[str, Any] | None:
    """Retrieve persisted terminal state for a job. Returns None if not found."""
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        raw = await r.get(f"job:{job_id}:state")
        if raw is None:
            return None
        return dict(json.loads(raw))
    finally:
        await r.aclose()


async def subscribe_job(job_id: str) -> AsyncIterator[dict[str, Any]]:
    """Async generator: yields messages from a job's Redis channel.

    Each subscriber gets its own Redis connection (pub/sub mode is exclusive).
    Always unsubscribe + close in finally to prevent connection leaks.
    """
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    pubsub = r.pubsub()
    channel = _channel_name(job_id)

    await pubsub.subscribe(channel)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                yield json.loads(message["data"])
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()  # type: ignore[no-untyped-call]
        await r.aclose()

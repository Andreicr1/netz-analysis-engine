"""
Job Progress Tracker — Redis Pub/Sub
======================================

Workers publish progress events to Redis channels.
SSE endpoints subscribe and stream to clients.

Channel convention: job:{job_id}:events
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

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


async def register_job_owner(job_id: str, organization_id: str, ttl_seconds: int = 3600) -> None:
    """Store job->org mapping in Redis for SSE tenant authorization."""
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        await r.set(f"job:{job_id}:org", organization_id, ex=ttl_seconds)
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
            logger.warning("job_owner_missing", job_id=job_id, org_id=organization_id)
            return False
        # Pool uses decode_responses=True, so owner is already str
        return owner == organization_id
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
    finally:
        await r.aclose()


async def subscribe_job(job_id: str):
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
        await pubsub.aclose()
        await r.aclose()

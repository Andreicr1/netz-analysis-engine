"""
Route-level Redis cache decorator for read-heavy GET endpoints.

Usage:
    from app.core.cache.route_cache import route_cache

    @router.get("/screener/facets")
    @route_cache(ttl=60, key_prefix="screener:facets")
    async def get_facets(org_id: UUID = Depends(get_org_id), ...):
        ...

Key format: rc:{prefix}:{org_id}:{sha8(sorted_params)}
Org-scoped by default — global_key=True for tenant-agnostic endpoints.
Fail-open: Redis unavailable -> request proceeds normally.
"""
from __future__ import annotations

import functools
import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

import redis.asyncio as aioredis
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


def _params_hash(kwargs: dict) -> str:
    filtered = {
        k: str(v) for k, v in kwargs.items()
        if k not in ("db", "actor", "user", "request", "response", "config_service")
        and v is not None
    }
    return hashlib.sha256(json.dumps(filtered, sort_keys=True).encode()).hexdigest()[:8]


def route_cache(ttl: int = 60, key_prefix: str = "route", global_key: bool = False) -> Callable:
    """
    Decorator for FastAPI async route handlers.

    Args:
        ttl: Cache TTL in seconds.
        key_prefix: Redis key prefix e.g. "screener:facets".
        global_key: If True, key is not org-scoped (for public/global data).
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            _actor = kwargs.get("actor") or kwargs.get("user")
            org_id: UUID | None = kwargs.get("org_id") or (
                _actor.organization_id if _actor else None
            )
            scope = "global" if global_key else str(org_id or "anon")
            cache_key = f"rc:{key_prefix}:{scope}:{_params_hash(kwargs)}"

            redis: aioredis.Redis | None = None
            try:
                from app.core.jobs.tracker import get_redis_pool
                redis = aioredis.Redis(connection_pool=get_redis_pool())
                cached = await redis.get(cache_key)
                if cached is not None:
                    logger.debug("Cache HIT  %s", cache_key)
                    return JSONResponse(content=json.loads(cached))
                logger.debug("Cache MISS %s", cache_key)
            except Exception as exc:
                logger.debug("Route cache GET fail-open: %s", exc)

            result = await func(*args, **kwargs)

            if redis is not None:
                try:
                    if hasattr(result, "model_dump"):
                        payload = result.model_dump(mode="json")
                    elif isinstance(result, list):
                        payload = [
                            r.model_dump(mode="json") if hasattr(r, "model_dump") else r
                            for r in result
                        ]
                    else:
                        payload = result
                    await redis.set(cache_key, json.dumps(payload), ex=ttl)
                except Exception as exc:
                    logger.debug("Route cache SET fail-open: %s", exc)

            return result
        return wrapper
    return decorator


async def invalidate_prefix(prefix: str, org_id: UUID | None = None) -> int:
    """Delete all cache keys matching a prefix + org scope. Returns count deleted."""
    try:
        from app.core.jobs.tracker import get_redis_pool
        redis = aioredis.Redis(connection_pool=get_redis_pool())
        pattern = f"rc:{prefix}:{org_id or '*'}:*"
        keys = await redis.keys(pattern)
        return await redis.delete(*keys) if keys else 0
    except Exception as exc:
        logger.warning("Cache invalidation failed: %s", exc)
        return 0

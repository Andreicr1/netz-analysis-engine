"""
Redis-based API Rate Limiter — Netz Analysis Engine
====================================================

Sliding-window counter using Redis INCR + EXPIRE.
Rate limit key: ``ratelimit:{organization_id}:{endpoint_group}``

Two tiers:
  - **standard** — default RPM for most endpoints
  - **compute**  — lower RPM for LLM-heavy endpoints (IC memos, deep review, DD reports)

Fail-open: if Redis is unavailable the request proceeds with a logged warning.
Admin endpoints (``/admin/``) and health probes are never rate-limited.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import redis.asyncio as aioredis
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

# Path prefixes that map to the "compute" (lower-limit) tier.
# These correspond to LLM-intensive operations: IC memo generation,
# AI modules (deep review, extraction, copilot), and DD reports.
_COMPUTE_HEAVY_PREFIXES: tuple[str, ...] = (
    "/api/v1/ai/",
    "/api/v1/dd-reports/",
    "/ic-memo",
    "/deep-review",
    "/document-reviews",
)

# Paths that are never rate-limited.
_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/health",
    "/api/health",
    "/api/v1/admin/",
)


def _classify_endpoint(path: str) -> str | None:
    """Return the rate-limit tier for a request path.

    Returns ``None`` for exempt paths, ``"compute"`` for LLM-heavy
    endpoints, and ``"standard"`` for everything else.
    """
    for prefix in _EXEMPT_PREFIXES:
        if path.startswith(prefix):
            return None

    for prefix in _COMPUTE_HEAVY_PREFIXES:
        if prefix in path:
            return "compute"

    return "standard"


def _extract_org_id_from_jwt_lightweight(token: str) -> str | None:
    """Extract organization_id from a Clerk JWT *without* signature verification.

    This is safe because the auth dependency performs full verification later.
    We only need the org_id for building the rate-limit key.  Worst case:
    a forged token targets a wrong bucket, but the request will be rejected
    by the real auth layer anyway.
    """
    import base64
    import json

    parts = token.split(".")
    if len(parts) != 3:
        return None
    try:
        # JWT payload is the second segment, base64url-encoded.
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        org_claims = payload.get("o", {})
        return org_claims.get("id")
    except Exception:
        return None


def _extract_org_id(request: Request) -> str | None:
    """Best-effort extraction of organization_id from the request.

    Checks dev header first (dev mode only), then falls back to
    lightweight JWT payload parsing.
    """
    # Dev bypass header
    if settings.is_development:
        import json as _json

        dev_header = request.headers.get(settings.dev_actor_header)
        if dev_header:
            try:
                data = _json.loads(dev_header)
                return data.get("org_id")
            except Exception:
                pass

    # Bearer token — lightweight parse (no signature check)
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        return _extract_org_id_from_jwt_lightweight(token)

    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window rate limiter backed by Redis INCR + EXPIRE."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Always pass through CORS preflight — CORSMiddleware handles these.
        if request.method == "OPTIONS":
            return await call_next(request)

        if not settings.rate_limit_enabled:
            return await call_next(request)

        path = request.url.path
        tier = _classify_endpoint(path)

        # Exempt endpoint (admin, health)
        if tier is None:
            return await call_next(request)

        org_id = _extract_org_id(request)
        if not org_id:
            # No auth context — let the auth layer reject later
            return await call_next(request)

        rpm = (
            settings.rate_limit_compute_rpm
            if tier == "compute"
            else settings.rate_limit_default_rpm
        )
        key = f"ratelimit:{org_id}:{tier}"
        window_seconds = 60

        try:
            from app.core.jobs.tracker import get_redis_pool

            pool = get_redis_pool()
            redis_client = aioredis.Redis(connection_pool=pool)

            now = time.time()
            window_key = f"{key}:{int(now // window_seconds)}"

            pipe = redis_client.pipeline(transaction=True)
            pipe.incr(window_key)
            pipe.expire(window_key, window_seconds + 1)
            results: list[Any] = await pipe.execute()
            current_count: int = results[0]

            if current_count > rpm:
                retry_after = window_seconds - int(now % window_seconds)
                logger.warning(
                    "Rate limit exceeded — org=%s tier=%s count=%d limit=%d",
                    org_id,
                    tier,
                    current_count,
                    rpm,
                )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too many requests. Please retry later.",
                    },
                    headers={
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(rpm),
                        "X-RateLimit-Remaining": "0",
                    },
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(rpm)
            response.headers["X-RateLimit-Remaining"] = str(
                max(0, rpm - current_count)
            )
            return response

        except (aioredis.ConnectionError, aioredis.TimeoutError, OSError) as exc:
            # Fail open — Redis unavailable should not block requests
            logger.warning("Rate limiter Redis unavailable, failing open: %s", exc)
            return await call_next(request)
        except Exception:
            logger.exception("Unexpected error in rate limiter, failing open")
            return await call_next(request)

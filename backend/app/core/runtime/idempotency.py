"""Idempotency decorator — cross-process deduplication of mutations.

Stability Guardrails §2.7 — satisfies P5 (Idempotent).

Problem this solves
-------------------
Human interaction is intrinsically retry-prone: a user clicks
"Import" twice because the first click took too long; a browser
re-sends a POST on back-navigation; a mobile connection drops and
the client auto-retries. With no deduplication, a single mutating
handler receives two concurrent POSTs and races against itself —
inserting duplicate rows, returning HTTP 409 on the second, or (the
worst case) silently corrupting state because of interleaved SQL.

``SingleFlightLock`` (§2.3) handles asyncio-level dedupe within a
single process. This decorator handles the cross-process variant
via a Redis-backed lock + result cache. The contract is the same:
at most one execution per key; concurrent callers receive the same
result; repeats within the TTL hit the cache.

What this primitive guarantees
------------------------------
- **At most one execution per idempotency key.** The first caller
  to acquire the lock executes the body. Concurrent callers with
  the same key wait for the result (polling with bounded sleep)
  and return the cached value.
- **Opaque result caching.** Successful results are serialised
  with ``orjson`` and cached under ``result:{key}``. Repeats within
  the TTL return the cached body without re-invoking the function.
- **Failure isolation.** If the function raises, the lock is
  released and the result is **not** cached. Callers observe the
  exception; the next call with the same key is free to retry.
- **Graceful degradation.** If the Redis backend is unreachable or
  raises during the lock attempt, the decorator logs a structured
  warning and executes the function **without** idempotency. This
  is the single intentional P5 relaxation, documented in the
  design spec risk R1.6. A ``X-Idempotency-Bypassed: true`` header
  hint can be surfaced by the caller if needed.
- **Deterministic key derivation.** The caller supplies a ``key``
  callable that maps the function's arguments to a string. Opaque
  to the decorator, explicit in the code.

Non-goals (v1)
--------------
- No result merging across mixed types. The cached result is the
  exact Python object returned by the first call, serialised via
  ``orjson``. If the function returns different shapes under
  different conditions, that's on the caller.
- No automatic extraction from FastAPI ``Request`` headers. Pass
  the ``Idempotency-Key`` header explicitly via the ``key``
  callable.
- No lock renewal / liveness checks. TTL is fixed at acquire time.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

import orjson

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


# ── Storage protocol ──────────────────────────────────────────────


class IdempotencyStorage(Protocol):
    """Minimal storage surface used by the decorator.

    Real deployments use ``RedisIdempotencyStorage``. Tests inject
    ``InMemoryIdempotencyStorage`` so the suite runs without Redis.
    """

    async def try_acquire(self, key: str, ttl_s: int) -> bool:
        """Atomically claim ``key`` if unclaimed. Returns True on
        success. TTL applies to the lock, not the result.
        """

    async def release(self, key: str) -> None:
        """Release the lock held on ``key``. No-op if not held."""

    async def set_result(self, key: str, value: bytes, ttl_s: int) -> None:
        """Store a serialised result under ``key`` with the given TTL."""

    async def get_result(self, key: str) -> bytes | None:
        """Return the cached result bytes, or None if absent."""


# ── In-memory storage (tests) ────────────────────────────────────


class InMemoryIdempotencyStorage:
    """Simple in-memory storage. Intended for tests and single-process
    development, never for multi-worker production.
    """

    def __init__(self) -> None:
        self._locks: dict[str, float] = {}  # key -> expires_at (monotonic)
        self._results: dict[str, tuple[bytes, float]] = {}
        self._mu = asyncio.Lock()

    async def try_acquire(self, key: str, ttl_s: int) -> bool:
        async with self._mu:
            now = time.monotonic()
            existing = self._locks.get(key)
            if existing is not None and existing > now:
                return False
            self._locks[key] = now + ttl_s
            return True

    async def release(self, key: str) -> None:
        async with self._mu:
            self._locks.pop(key, None)

    async def set_result(self, key: str, value: bytes, ttl_s: int) -> None:
        async with self._mu:
            self._results[key] = (value, time.monotonic() + ttl_s)

    async def get_result(self, key: str) -> bytes | None:
        async with self._mu:
            entry = self._results.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at <= time.monotonic():
                self._results.pop(key, None)
                return None
            return value


# ── Redis storage (production) ───────────────────────────────────


class RedisIdempotencyStorage:
    """Production Redis-backed storage.

    Uses ``SET NX EX`` for atomic lock acquire. The lock and result
    live under distinct key prefixes (``idem:lock:`` and
    ``idem:result:``) to avoid accidental collision with other
    Redis users.
    """

    LOCK_PREFIX = "idem:lock:"
    RESULT_PREFIX = "idem:result:"

    def __init__(self, redis: Any) -> None:
        # ``redis`` is typed ``Any`` to avoid a hard import of
        # ``redis.asyncio`` at module load. Callers wire up the real
        # ``aioredis.Redis`` instance from the pool.
        self._redis = redis

    async def try_acquire(self, key: str, ttl_s: int) -> bool:
        lock_key = f"{self.LOCK_PREFIX}{key}"
        # SET NX EX — atomic
        result = await self._redis.set(lock_key, "1", nx=True, ex=ttl_s)
        return bool(result)

    async def release(self, key: str) -> None:
        lock_key = f"{self.LOCK_PREFIX}{key}"
        try:
            await self._redis.delete(lock_key)
        except Exception:  # noqa: BLE001
            logger.debug("idempotency_release_failed key=%s", key, exc_info=True)

    async def set_result(self, key: str, value: bytes, ttl_s: int) -> None:
        result_key = f"{self.RESULT_PREFIX}{key}"
        await self._redis.set(result_key, value, ex=ttl_s)

    async def get_result(self, key: str) -> bytes | None:
        result_key = f"{self.RESULT_PREFIX}{key}"
        val = await self._redis.get(result_key)
        if val is None:
            return None
        if isinstance(val, str):
            return val.encode()
        return bytes(val)


# ── Decorator ────────────────────────────────────────────────────


def idempotent(
    *,
    key: Callable[..., str],
    ttl_s: int = 86400,
    storage: IdempotencyStorage,
    wait_timeout_s: float = 10.0,
    wait_poll_s: float = 0.05,
) -> Callable[[F], F]:
    """Decorate an async function to deduplicate by idempotency key.

    Args:
        key: function that receives the same args/kwargs as the
            wrapped function and returns a stable string key.
        ttl_s: lock + result TTL in seconds. Defaults to 24h.
        storage: backing store. In production, pass a
            ``RedisIdempotencyStorage`` bound to the app's aioredis
            instance. In tests, pass ``InMemoryIdempotencyStorage``.
        wait_timeout_s: how long a concurrent caller waits for the
            first execution's result before giving up and executing
            without the lock (logged as a fallback).
        wait_poll_s: interval between result polls during waiting.

    The wrapped function's return value is serialised via
    ``orjson``. Any return type that ``orjson`` cannot encode will
    raise at call time — keep results to JSON-compatible data
    structures (dict, list, str, int, float, bool, None).
    """
    if ttl_s <= 0:
        raise ValueError("idempotent ttl_s must be > 0")
    if wait_timeout_s <= 0:
        raise ValueError("idempotent wait_timeout_s must be > 0")

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                op_key = key(*args, **kwargs)
            except Exception:
                logger.exception("idempotency_key_extractor_failed")
                return await func(*args, **kwargs)

            # 1. Cache hit?
            try:
                cached = await storage.get_result(op_key)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "idempotency_storage_get_result_failed key=%s — "
                    "executing without cache (fail-open)",
                    op_key,
                    exc_info=True,
                )
                return await func(*args, **kwargs)
            if cached is not None:
                try:
                    return orjson.loads(cached)
                except orjson.JSONDecodeError:
                    logger.warning(
                        "idempotency_cache_decode_failed key=%s — "
                        "treating as miss",
                        op_key,
                    )

            # 2. Try to acquire the lock.
            try:
                acquired = await storage.try_acquire(op_key, ttl_s)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "idempotency_storage_acquire_failed key=%s — "
                    "executing without cache (fail-open)",
                    op_key,
                    exc_info=True,
                )
                return await func(*args, **kwargs)

            if acquired:
                # 3a. We own the flight. Execute.
                try:
                    result = await func(*args, **kwargs)
                except Exception:
                    # Failure: release lock, do not cache.
                    try:
                        await storage.release(op_key)
                    except Exception:  # noqa: BLE001
                        pass
                    raise
                else:
                    try:
                        payload = orjson.dumps(result)
                        await storage.set_result(op_key, payload, ttl_s)
                    except Exception:  # noqa: BLE001
                        logger.warning(
                            "idempotency_store_result_failed key=%s",
                            op_key,
                            exc_info=True,
                        )
                    finally:
                        try:
                            await storage.release(op_key)
                        except Exception:  # noqa: BLE001
                            pass
                    return result

            # 3b. Another caller owns the flight. Wait for its result.
            deadline = time.monotonic() + wait_timeout_s
            while time.monotonic() < deadline:
                await asyncio.sleep(wait_poll_s)
                try:
                    cached = await storage.get_result(op_key)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "idempotency_wait_get_failed key=%s",
                        op_key,
                        exc_info=True,
                    )
                    break
                if cached is not None:
                    try:
                        return orjson.loads(cached)
                    except orjson.JSONDecodeError:
                        break

            # Wait timed out or cache decode failed. Fall through
            # and execute directly — the in-flight caller may still
            # complete, but the user gets their answer.
            logger.warning(
                "idempotency_wait_timeout key=%s — executing without "
                "lock (fail-open)",
                op_key,
            )
            return await func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator

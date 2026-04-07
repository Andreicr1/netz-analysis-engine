"""Single-flight lock — coroutine deduplication with optional TTL cache.

Stability Guardrails §2.3 — satisfies P2 (Batched), P3 (Isolated).

Problem this solves
-------------------
Several places in the engine produce expensive work whose inputs
collide under load:

- ``tiingo_bridge._drain_buffer`` fires ``asyncio.create_task`` when
  the tick buffer overflows, then fires it again on the next
  overflow, and again — producing overlapping drain coroutines that
  race on ``self._buffer = []``. Race condition by construction.
- ``POST /screener/import/{identifier}`` handlers can be invoked
  twice in a row by an impatient double-click; the two handlers fetch
  the same SEC row in parallel, race to INSERT, and leave behind
  either a 409 or (worse) a duplicate row depending on timing.
- Cache warm-up routines retrieve the same upstream document from two
  different request paths and duplicate the cost.

``SingleFlightLock`` is the minimal primitive for all of these: at
most one coroutine per key is in-flight at a time; every concurrent
caller observes the **same** result; an optional TTL turns it into a
coalescing cache.

What this primitive guarantees
------------------------------
- **At most one in-flight execution per key.** The second and
  subsequent callers with the same key during the flight window
  observe the exact same result object returned by the first caller.
- **Exception propagation.** If the factory raises, every waiter
  receives the **same** exception re-raised (not a copy). The cache
  entry is **not** populated.
- **Cancellation propagation.** If the original flight is cancelled
  (e.g. via ``task.cancel()``), every waiter receives
  ``asyncio.CancelledError``. The cache is not populated. A
  subsequent ``run()`` with the same key is free to re-execute.
- **Deterministic cleanup.** In-flight bookkeeping is removed in a
  ``finally`` block so one-off exceptions never leak lock state.
- **TTL-based caching.** When ``ttl_s`` is not ``None`` and the
  factory succeeds, the result is cached for ``ttl_s`` seconds.
  Callers within the TTL get the cached value without re-executing
  the factory. Failures and cancellations are never cached.
- **Isolation between keys.** Different keys never wait on each other.
  The lock is per-key, not global.

Non-goals (v1)
--------------
- No cross-process coordination. ``SingleFlightLock`` is an asyncio
  primitive bound to the single-process event loop. Cross-process
  deduplication lives in the ``@idempotent`` decorator (§2.7) which
  uses Redis ``SETNX``.
- No LRU bound on the cache. Callers with unbounded key spaces must
  provide a ``ttl_s`` so entries expire; if they don't, memory grows.
  A ``max_cached_entries`` knob can be added in a later amendment if
  real call sites need it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Hashable
from dataclasses import dataclass
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


# ── Internal bookkeeping ──────────────────────────────────────────


@dataclass
class _Flight(Generic[V]):
    """An in-flight execution. Waiters block on ``event`` and then
    read ``result`` / ``exception``.
    """

    event: asyncio.Event
    result: V | None = None
    exception: BaseException | None = None
    cancelled: bool = False


@dataclass
class _CacheEntry(Generic[V]):
    value: V
    expires_at: float  # monotonic seconds; math.inf means never


# ── Lock ───────────────────────────────────────────────────────────


class SingleFlightLock(Generic[K, V]):
    """Per-key coroutine deduplication with optional TTL cache.

    The lock is intentionally generic in both ``K`` (the key type,
    any ``Hashable``) and ``V`` (the factory return type). Callers
    should pin both type parameters at construction time for clear
    error messages from their type checker.
    """

    def __init__(self) -> None:
        self._flights: dict[K, _Flight[V]] = {}
        self._cache: dict[K, _CacheEntry[V]] = {}

    async def run(
        self,
        key: K,
        coro_factory: Callable[[], Awaitable[V]],
        *,
        ttl_s: float | None = None,
    ) -> V:
        """Execute ``coro_factory()`` at most once per key.

        Semantics:
        1. If a valid cache entry exists for ``key``, return it. The
           factory is **not** called.
        2. Otherwise, if a flight is already in-flight for ``key``,
           block on it and return the same result (or re-raise the
           same exception).
        3. Otherwise, create a new flight, invoke ``coro_factory()``,
           populate the cache if ``ttl_s`` is given and the factory
           succeeded, and return the result.
        """
        # 1. Cache hit.
        cached = self._lookup_cache(key)
        if cached is not None:
            return cached

        # 2. Join in-flight.
        existing = self._flights.get(key)
        if existing is not None:
            return await self._await_flight(existing)

        # 3. New flight.
        flight: _Flight[V] = _Flight(event=asyncio.Event())
        self._flights[key] = flight
        try:
            try:
                result = await coro_factory()
            except asyncio.CancelledError:
                flight.cancelled = True
                flight.event.set()
                raise
            except BaseException as exc:  # noqa: BLE001 — intentional
                flight.exception = exc
                flight.event.set()
                raise
            else:
                flight.result = result
                flight.event.set()
                if ttl_s is not None:
                    self._store_cache(key, result, ttl_s)
                return result
        finally:
            # Remove the in-flight entry after waiters have been
            # woken so a fresh ``run()`` for the same key is allowed
            # to start its own flight.
            self._flights.pop(key, None)

    def invalidate(self, key: K) -> bool:
        """Remove any cached value for ``key``. Returns True if a
        value was evicted.
        """
        return self._cache.pop(key, None) is not None

    def clear(self) -> None:
        """Drop every cached value. Does not affect in-flight work."""
        self._cache.clear()

    # ── Internals ──────────────────────────────────────────────

    def _lookup_cache(self, key: K) -> V | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            self._cache.pop(key, None)
            return None
        return entry.value

    def _store_cache(self, key: K, value: V, ttl_s: float) -> None:
        self._cache[key] = _CacheEntry(
            value=value,
            expires_at=time.monotonic() + ttl_s,
        )

    async def _await_flight(self, flight: _Flight[V]) -> V:
        await flight.event.wait()
        if flight.cancelled:
            raise asyncio.CancelledError("flight was cancelled")
        if flight.exception is not None:
            raise flight.exception
        # If we got here, ``result`` was set. The narrow cast is
        # safe because success is the only path that sets ``result``.
        return flight.result  # type: ignore[return-value]

"""External provider gate — fail-fast wrapper for REST-style APIs.

Stability Guardrails §2.5 — satisfies P6 (Fault-Tolerant).

Problem this solves
-------------------
Every external HTTP dependency in the engine (Tiingo REST, SEC EDGAR,
FRED, Yahoo Finance, Mistral OCR) is a latent availability risk. A
provider that slows down from 200ms to 30s will hold asyncpg pool
connections open, starve unrelated requests, and cascade a
third-party incident into our own outage. Routes that call these
APIs directly have no budget, no fallback, and no circuit breaker.

``ExternalProviderGate`` is a thin wrapper that makes every call:

- **Bounded in time** — a hard ``asyncio.wait_for`` wall enforces
  ``timeout_s``. A hung provider returns ``ProviderTimeoutError``
  in exactly that many seconds, never more.
- **Circuit-broken** — after ``failure_threshold`` consecutive
  failures the circuit opens, and the next ``recovery_after_s``
  seconds of calls return ``ProviderUnavailableError`` (or an
  ``on_open`` fallback / cached result) without hitting the provider
  at all. One probe is allowed when the recovery window passes; if
  it succeeds the circuit closes.
- **Cacheable** — an optional ``cache_ttl_s`` caches successful
  responses keyed by ``op_key``. During an open circuit, cached
  values are returned if they exist and have not expired.

What this primitive guarantees
------------------------------
- **No call exceeds ``timeout_s``.** Wall-clock bounded with
  ``asyncio.wait_for``; a cancelled provider call never leaks the
  hung coroutine.
- **No new call during an open circuit** unless the caller
  explicitly provides an ``on_open`` fallback or a fresh cache hit
  is available. The circuit protects the process, not the
  individual call.
- **Deterministic recovery.** The half-open probe runs exactly
  once, on the first call after ``recovery_after_s`` elapses since
  the open transition. Probe success → closed; probe failure →
  reset the open timer.
- **Exception mapping.** Timeouts raise ``ProviderTimeoutError``;
  open-circuit rejections raise ``ProviderUnavailableError``; any
  exception from the factory is re-raised as-is (callers can map
  HTTP errors themselves).
- **Per-gate isolation.** Two gates with different ``name``s are
  independent — one provider going down does not affect another.

Non-goals (v1)
--------------
- No OpenAI/LLM support. LLM calls have different semantics
  (variable latency, 429 backoff, fallback model) and live in
  ``LLMGate`` (§2.5b / commit 06).
- No request coalescing. If two callers hit the gate simultaneously
  with the same ``op_key``, both execute unless a cache hit is
  available. Coalescing is ``SingleFlightLock``'s job; stack them if
  you need both.
- No Prometheus export. Metrics are local.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# ── Errors ─────────────────────────────────────────────────────────


class ProviderGateError(Exception):
    """Base class for gate errors."""


class ProviderTimeoutError(ProviderGateError):
    """Raised when a call exceeds the gate's ``timeout_s``."""


class ProviderUnavailableError(ProviderGateError):
    """Raised when the circuit is open and no fallback is available."""


# ── State ──────────────────────────────────────────────────────────


class GateState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


# ── Config ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateConfig:
    """Declarative gate configuration.

    Tune ``recovery_after_s`` per provider SLA: fast providers (Tiingo
    HTTP, Yahoo) can recover in ~10s; slow providers (SEC EDGAR) need
    30s or more. Defaults are conservative but appropriate for SEC.
    """

    name: str
    timeout_s: float
    failure_threshold: int = 5
    recovery_after_s: float = 30.0
    cache_ttl_s: float | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("GateConfig.name must be non-empty")
        if self.timeout_s <= 0:
            raise ValueError("GateConfig.timeout_s must be > 0")
        if self.failure_threshold <= 0:
            raise ValueError("GateConfig.failure_threshold must be > 0")
        if self.recovery_after_s <= 0:
            raise ValueError("GateConfig.recovery_after_s must be > 0")
        if self.cache_ttl_s is not None and self.cache_ttl_s < 0:
            raise ValueError("GateConfig.cache_ttl_s must be >= 0 or None")


# ── Metrics ────────────────────────────────────────────────────────


@dataclass
class GateMetrics:
    calls: int = 0
    successes: int = 0
    failures: int = 0
    timeouts: int = 0
    circuit_opens: int = 0
    rejected_open: int = 0
    cache_hits: int = 0


# ── Cache ──────────────────────────────────────────────────────────


@dataclass
class _CacheEntry(Generic[T]):
    value: T
    expires_at: float


# ── Gate ───────────────────────────────────────────────────────────


class ExternalProviderGate(Generic[T]):
    """Circuit breaker + hard timeout + cache fallback for REST APIs."""

    def __init__(self, cfg: GateConfig) -> None:
        self._cfg = cfg
        self._state = GateState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float | None = None
        self._cache: dict[str, _CacheEntry[T]] = {}
        self._metrics = GateMetrics()

    # ── Public API ─────────────────────────────────────────────

    @property
    def state(self) -> GateState:
        """Return the current state, advancing to ``HALF_OPEN`` if
        the open window has elapsed.
        """
        self._advance_state()
        return self._state

    @property
    def metrics(self) -> GateMetrics:
        return self._metrics

    async def call(
        self,
        op_key: str,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        on_open: Callable[[], T] | None = None,
    ) -> T:
        """Execute ``coro_factory()`` under the gate's protections.

        Resolution order:
          1. If the circuit is OPEN, return a cached value for
             ``op_key`` if available. Otherwise return ``on_open()``
             if provided. Otherwise raise ``ProviderUnavailableError``.
          2. If the circuit is CLOSED or HALF_OPEN, execute the
             factory with a ``timeout_s`` wall. A successful probe
             closes the circuit; a failure (including timeout) counts
             toward ``failure_threshold`` and may reopen it.
          3. On success with ``cache_ttl_s`` set, cache the result.
        """
        self._metrics.calls += 1
        self._advance_state()

        if self._state == GateState.OPEN:
            self._metrics.rejected_open += 1
            cached = self._lookup_cache(op_key)
            if cached is not None:
                self._metrics.cache_hits += 1
                return cached
            if on_open is not None:
                return on_open()
            raise ProviderUnavailableError(
                f"provider '{self._cfg.name}' circuit is open",
            )

        # CLOSED or HALF_OPEN — attempt the call.
        try:
            result = await asyncio.wait_for(
                coro_factory(),
                timeout=self._cfg.timeout_s,
            )
        except asyncio.TimeoutError as exc:
            self._metrics.timeouts += 1
            self._record_failure()
            raise ProviderTimeoutError(
                f"provider '{self._cfg.name}' timed out after "
                f"{self._cfg.timeout_s}s",
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception:
            self._record_failure()
            raise
        else:
            self._record_success()
            if self._cfg.cache_ttl_s is not None:
                self._store_cache(op_key, result)
            return result

    def invalidate_cache(self, op_key: str | None = None) -> None:
        """Drop cached entries. Pass ``op_key`` to evict one entry;
        omit to clear the whole cache.
        """
        if op_key is None:
            self._cache.clear()
        else:
            self._cache.pop(op_key, None)

    def reset(self) -> None:
        """Force the circuit back to CLOSED and clear the cache.

        Intended for test teardown and for a manual "known good"
        recovery after an operator intervention.
        """
        self._state = GateState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None
        self._cache.clear()

    # ── Internals ──────────────────────────────────────────────

    def _advance_state(self) -> None:
        """If the open window has elapsed, move to ``HALF_OPEN``."""
        if self._state != GateState.OPEN:
            return
        if self._opened_at is None:
            return
        if time.monotonic() - self._opened_at >= self._cfg.recovery_after_s:
            self._state = GateState.HALF_OPEN
            logger.info(
                "provider_gate_half_open name=%s",
                self._cfg.name,
            )

    def _record_success(self) -> None:
        self._metrics.successes += 1
        self._consecutive_failures = 0
        if self._state in (GateState.HALF_OPEN, GateState.OPEN):
            self._state = GateState.CLOSED
            self._opened_at = None
            logger.info(
                "provider_gate_closed name=%s",
                self._cfg.name,
            )

    def _record_failure(self) -> None:
        self._metrics.failures += 1
        if self._state == GateState.HALF_OPEN:
            # Probe failed — reopen the circuit and restart the timer.
            self._state = GateState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "provider_gate_reopened_after_probe name=%s",
                self._cfg.name,
            )
            return
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._cfg.failure_threshold:
            self._state = GateState.OPEN
            self._opened_at = time.monotonic()
            self._metrics.circuit_opens += 1
            logger.warning(
                "provider_gate_opened name=%s failures=%d",
                self._cfg.name,
                self._consecutive_failures,
            )

    def _lookup_cache(self, op_key: str) -> T | None:
        entry = self._cache.get(op_key)
        if entry is None:
            return None
        if entry.expires_at <= time.monotonic():
            self._cache.pop(op_key, None)
            return None
        return entry.value

    def _store_cache(self, op_key: str, value: T) -> None:
        if self._cfg.cache_ttl_s is None:
            return
        self._cache[op_key] = _CacheEntry(
            value=value,
            expires_at=time.monotonic() + self._cfg.cache_ttl_s,
        )

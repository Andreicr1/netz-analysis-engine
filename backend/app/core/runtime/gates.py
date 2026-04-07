"""Global runtime gate / storage singletons.

Stability Guardrails — wires the §2.5 ``ExternalProviderGate`` and the
§2.7 ``RedisIdempotencyStorage`` to the running application's shared
Redis pool, exposing them as lazy module-level singletons so call sites
can decorate themselves at import time without taking on the cost of
constructing the gate / storage on every request.

Why singletons?
---------------
- A circuit breaker is **state**: a gate per request defeats the point.
  Two callers that hit the same provider must observe the same circuit
  state, otherwise one of them will keep retrying while the other is
  cooling down.
- The idempotency decorator is applied at function-decoration time. It
  needs an ``IdempotencyStorage`` instance to wrap each call, and that
  instance must be the same for every request that should dedupe
  against itself.

Initialisation order
--------------------
The singletons are constructed lazily on first access. The Redis pool
factory (``app.core.jobs.tracker.get_redis_pool``) is itself lazy, so
import-time decoration of routes is safe — no I/O happens until a
request actually fires.

Adding a new provider
---------------------
1. Pick a stable ``name`` ("sec_edgar", "fred", "yahoo", etc.).
2. Add a ``get_<name>_gate()`` factory below with a ``GateConfig``
   tuned to that provider's SLA. Keep timeouts conservative — better
   to fail fast and let the circuit cool down than hold a worker
   coroutine for 60s.
3. Use the gate at the call site::

       gate = get_sec_edgar_gate()
       result = await gate.call("op_key", lambda: do_the_call())
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis

from app.core.jobs.tracker import get_redis_pool
from app.core.runtime.idempotency import (
    IdempotencyStorage,
    RedisIdempotencyStorage,
)
from app.core.runtime.provider_gate import ExternalProviderGate, GateConfig

# ── Idempotency storage ────────────────────────────────────────────

_idempotency_storage: IdempotencyStorage | None = None


def get_idempotency_storage() -> IdempotencyStorage:
    """Lazy singleton ``RedisIdempotencyStorage`` bound to the shared pool.

    The decorator's storage parameter is resolved at decoration time;
    routes that depend on this MUST import the module after the
    settings layer has loaded (true at FastAPI app construction).
    """
    global _idempotency_storage
    if _idempotency_storage is None:
        pool = get_redis_pool()
        redis_client: Any = aioredis.Redis(connection_pool=pool)
        _idempotency_storage = RedisIdempotencyStorage(redis_client)
    return _idempotency_storage


# ── SEC EDGAR provider gate ────────────────────────────────────────

# SEC EDGAR rate limit: 10 req/s per host (officially documented).
# We give a generous 30s wall on individual requests because brochure
# downloads from reports.adviserinfo.sec.gov can sit on the server
# side for 10-20s before responding. The circuit opens after five
# consecutive failures and stays open for 30s before probing — long
# enough to ride out a transient outage without holding asyncpg
# connections.
_SEC_EDGAR_GATE_CONFIG = GateConfig(
    name="sec_edgar",
    timeout_s=30.0,
    failure_threshold=5,
    recovery_after_s=30.0,
    cache_ttl_s=None,
)

_sec_edgar_gate: ExternalProviderGate[Any] | None = None


def get_sec_edgar_gate() -> ExternalProviderGate[Any]:
    """Lazy singleton gate for interactive SEC EDGAR REST calls.

    Use this for any SEC EDGAR fetch reachable from a request /
    user-facing path: brochure PDFs, EFTS queries, IAPD search.
    The 30 s wall is generous enough for adviserinfo's slow edge
    POPs but tight enough to release asyncpg connections quickly
    on a hung provider.

        gate = get_sec_edgar_gate()
        pdf = await gate.call(f"brochure:{crd}", lambda: download_pdf(crd))
    """
    global _sec_edgar_gate
    if _sec_edgar_gate is None:
        _sec_edgar_gate = ExternalProviderGate(_SEC_EDGAR_GATE_CONFIG)
    return _sec_edgar_gate


# Dedicated gate for **bulk** SEC EDGAR operations (FOIA ZIPs, N-PORT
# bulk dumps, multi-megabyte downloads). These are worker-context only
# and routinely take more than 30 s — using the interactive gate
# would cancel the thread mid-download. The bulk gate gives them a
# 5 minute wall and a more lenient circuit (10 failures before opening,
# 60 s recovery probe) so an SEC FOIA hiccup doesn't permanently
# break daily ingestion.
_SEC_EDGAR_BULK_GATE_CONFIG = GateConfig(
    name="sec_edgar_bulk",
    timeout_s=300.0,
    failure_threshold=10,
    recovery_after_s=60.0,
    cache_ttl_s=None,
)

_sec_edgar_bulk_gate: ExternalProviderGate[Any] | None = None


def get_sec_edgar_bulk_gate() -> ExternalProviderGate[Any]:
    """Lazy singleton gate for **worker-only** bulk SEC downloads.

    Distinct from ``get_sec_edgar_gate`` because the timeout budget
    differs by an order of magnitude. Never call from a request
    handler — bulk downloads must run inside background workers.
    """
    global _sec_edgar_bulk_gate
    if _sec_edgar_bulk_gate is None:
        _sec_edgar_bulk_gate = ExternalProviderGate(_SEC_EDGAR_BULK_GATE_CONFIG)
    return _sec_edgar_bulk_gate


# ── Test hooks ─────────────────────────────────────────────────────


def reset_for_tests() -> None:
    """Drop every cached singleton. Tests call this between cases so
    a circuit opened in one test doesn't bleed into the next.
    """
    global _idempotency_storage, _sec_edgar_gate, _sec_edgar_bulk_gate
    _idempotency_storage = None
    _sec_edgar_gate = None
    _sec_edgar_bulk_gate = None

"""Bounded outbound channel — per-connection WebSocket write buffer.

Stability Guardrails §2.1 — satisfies P1 (Bounded), P3 (Isolated),
P4 (Lifecycle-correct).

Problem this solves
-------------------
The legacy ``ConnectionManager._fanout`` iterated sequentially over all
WebSocket subscribers and called ``await ws.send_bytes(payload)``
directly, with **no timeout** and **no per-connection buffering**. A
single slow or stalled client (bad network, tab in background, browser
throttled) would block the entire fan-out for that channel until the
TCP stack gave up, starving every other subscriber of the same data.
Combined with the Tiingo firehose (hundreds of ticks per second), this
class of failure is the mechanical root cause of the Dashboard
self-DDoS incidents documented in §7.1 of the design spec.

What this primitive guarantees
------------------------------
- **Non-blocking publish.** ``offer(payload)`` never awaits, never
  raises. The publisher is decoupled from client send latency.
- **Explicit capacity.** ``max_queued`` is a hard cap. When full, the
  configured ``DropPolicy`` decides what to drop. No silent growth.
- **Bounded send latency.** A background drain task sends each payload
  with ``asyncio.wait_for(..., send_timeout_s)``. A stalled socket is
  detected after exactly ``send_timeout_s`` — not after the OS-level
  TCP timeout.
- **Slow-consumer signalling.** Consecutive drops (from queue-full or
  send-timeout) are counted. After ``eviction_threshold`` consecutive
  failures the channel flags ``is_evictable = True``. Once set, the
  flag is sticky — the broadcaster owns the decision to detach the
  offending connection. A single successful send resets the counter
  but does **not** clear the eviction flag.
- **Deterministic teardown.** ``stop(drain=True)`` waits up to
  ``send_timeout_s`` for the queue to empty; ``stop(drain=False)``
  cancels the drain task immediately. Either way the task is always
  cancelled and joined — no orphan coroutines.

Non-goals (v1)
--------------
- The ``BLOCK`` drop policy (publisher backpressure) is intentionally
  omitted. WebSocket fan-out is the only consumer in this sprint and
  the fan-out must never block; if a future consumer needs real
  backpressure, a ``BlockingOutboundChannel`` variant will be added in
  a later charter amendment.
- Metrics are local (per-channel). Aggregation lives in
  ``RateLimitedBroadcaster`` (§2.2).

Usage
-----
```python
from app.core.runtime.outbound_channel import (
    BoundedOutboundChannel, ChannelConfig, DropPolicy,
)

cfg = ChannelConfig(
    max_queued=256,
    send_timeout_s=2.0,
    drop_policy=DropPolicy.DROP_OLDEST,
    eviction_threshold=3,
)
channel = BoundedOutboundChannel(ws=websocket, cfg=cfg)
await channel.start()
try:
    channel.offer(payload_bytes)          # non-blocking
    if channel.is_evictable:
        # slow consumer — broadcaster will detach it
        ...
finally:
    await channel.stop(drain=True)
```
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

logger = logging.getLogger(__name__)


# ── Protocols ──────────────────────────────────────────────────────


class WebSocketLike(Protocol):
    """Minimal WebSocket surface this channel depends on.

    Declared as a Protocol so tests can inject plain mocks and real
    Starlette/FastAPI ``WebSocket`` instances both satisfy it without
    a compile-time dependency.
    """

    async def send_bytes(self, data: bytes) -> None:  # pragma: no cover - protocol
        ...


# ── Configuration ──────────────────────────────────────────────────


class DropPolicy(StrEnum):
    """How a full outbound queue handles a new ``offer()``.

    ``DROP_OLDEST`` is the right choice for market-data-like streams
    where freshness matters more than completeness. ``DROP_NEWEST`` is
    the right choice for critical event streams where the earliest
    signals must survive and tail updates are expendable.
    """

    DROP_OLDEST = "drop_oldest"
    DROP_NEWEST = "drop_newest"


@dataclass(frozen=True)
class ChannelConfig:
    """Declarative configuration for a ``BoundedOutboundChannel``.

    All fields are mandatory to name at construction time (no hidden
    globals). The defaults are tuned for the Tiingo market-data
    use case: 256 messages queued per client, 2-second hard wall on
    the ``send_bytes`` call, 3 consecutive failures before eviction.
    """

    max_queued: int = 256
    send_timeout_s: float = 2.0
    drop_policy: DropPolicy = DropPolicy.DROP_OLDEST
    eviction_threshold: int = 3
    # How long ``stop(drain=True)`` waits for the queue to empty before
    # force-cancelling the drain task. Defaults to ``send_timeout_s``
    # so a single stuck send cannot delay shutdown beyond the normal
    # send budget.
    drain_grace_s: float | None = None

    def __post_init__(self) -> None:
        if self.max_queued <= 0:
            raise ValueError("ChannelConfig.max_queued must be > 0")
        if self.send_timeout_s <= 0:
            raise ValueError("ChannelConfig.send_timeout_s must be > 0")
        if self.eviction_threshold <= 0:
            raise ValueError("ChannelConfig.eviction_threshold must be > 0")
        if self.drain_grace_s is not None and self.drain_grace_s < 0:
            raise ValueError("ChannelConfig.drain_grace_s must be >= 0")


# ── Metrics ────────────────────────────────────────────────────────


@dataclass
class ChannelMetrics:
    """Observable counters for a single channel.

    Mutable by the channel itself; read-only from the outside via
    ``BoundedOutboundChannel.metrics`` which returns the live object
    (callers should treat it as a snapshot and not mutate it).
    """

    queued: int = 0
    sent: int = 0
    accepted: int = 0
    dropped: int = 0
    timeouts: int = 0
    send_errors: int = 0
    consecutive_failures: int = 0
    evicted: bool = False


# ── Channel ────────────────────────────────────────────────────────


class BoundedOutboundChannel:
    """Per-connection write buffer with drop policy and slow-consumer eviction.

    Exactly one drain task is spawned per channel in ``start()`` and
    cancelled in ``stop()``. The channel is thread-unsafe by design —
    it lives entirely on a single asyncio event loop and relies on
    single-threaded cooperative scheduling for its invariants.
    """

    def __init__(self, ws: WebSocketLike, cfg: ChannelConfig) -> None:
        self._ws = ws
        self._cfg = cfg
        self._queue: deque[bytes] = deque()
        self._wakeup = asyncio.Event()
        self._drain_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._started = False
        self._sending = False  # True while a send is in flight (guards stop(drain=True))
        self._metrics = ChannelMetrics()

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Spawn the background drain task. Idempotent."""
        if self._started:
            return
        self._started = True
        self._stopped = False
        self._drain_task = asyncio.create_task(
            self._drain_loop(),
            name="outbound_channel_drain",
        )

    async def stop(self, *, drain: bool = False) -> None:
        """Stop accepting new offers and tear down the drain task.

        If ``drain`` is True, waits up to ``drain_grace_s`` (falling
        back to ``send_timeout_s``) for the current queue to flush
        before cancelling. If False, cancels immediately; queued
        payloads are discarded.
        """
        if not self._started:
            return
        self._stopped = True
        self._wakeup.set()  # unblock the drain loop so it can observe _stopped

        if drain and self._drain_task is not None and not self._drain_task.done():
            grace = self._cfg.drain_grace_s
            if grace is None:
                grace = self._cfg.send_timeout_s
            try:
                await asyncio.wait_for(self._wait_until_empty(), timeout=grace)
            except asyncio.TimeoutError:
                logger.debug(
                    "outbound_channel_drain_grace_exceeded queue_size=%d",
                    len(self._queue),
                )

        task = self._drain_task
        self._drain_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._started = False

    async def _wait_until_empty(self) -> None:
        """Poll until the queue is empty AND no send is in flight.

        Used only by ``stop(drain=True)``. Both conditions matter: a
        queue length of zero alone is not enough, because the drain
        loop pops before awaiting ``send_bytes`` and the final payload
        may still be mid-flight when the queue empties.
        """
        while self._queue or self._sending:
            await asyncio.sleep(0.005)

    # ── Publisher API ──────────────────────────────────────────

    def offer(self, payload: bytes) -> bool:
        """Non-blocking enqueue. Returns True if the payload was accepted.

        Semantics by drop policy when the queue is at capacity:

        - ``DROP_OLDEST``: pop the oldest payload, append ``payload``,
          return ``True``. The publisher's message survived; a stale
          one was dropped. Counts one drop toward eviction.
        - ``DROP_NEWEST``: reject ``payload``, return ``False``. The
          oldest queue contents are preserved. Counts one drop toward
          eviction.

        After ``stop()`` has been called, ``offer()`` always returns
        ``False`` and never touches the queue.
        """
        if self._stopped:
            return False

        if len(self._queue) >= self._cfg.max_queued:
            self._metrics.dropped += 1
            self._metrics.consecutive_failures += 1
            self._update_eviction()
            if self._cfg.drop_policy == DropPolicy.DROP_OLDEST:
                self._queue.popleft()
                self._queue.append(payload)
                self._metrics.queued = len(self._queue)
                self._wakeup.set()
                return True
            # DROP_NEWEST
            return False

        self._queue.append(payload)
        self._metrics.queued = len(self._queue)
        self._metrics.accepted += 1
        self._wakeup.set()
        return True

    # ── Read-only state ────────────────────────────────────────

    @property
    def is_evictable(self) -> bool:
        """Sticky flag: True once eviction threshold has been crossed.

        The broadcaster reads this to decide whether to detach the
        underlying connection. Resetting it is impossible from outside
        the channel — the only way back is a fresh ``BoundedOutboundChannel``
        instance.
        """
        return self._metrics.evicted

    @property
    def metrics(self) -> ChannelMetrics:
        """Return the live metrics object. Treat as a snapshot."""
        self._metrics.queued = len(self._queue)
        return self._metrics

    @property
    def is_running(self) -> bool:
        return self._started and not self._stopped

    # ── Internals ──────────────────────────────────────────────

    def _update_eviction(self) -> None:
        if self._metrics.consecutive_failures >= self._cfg.eviction_threshold:
            self._metrics.evicted = True

    async def _drain_loop(self) -> None:
        """Pop one payload at a time and send it with a bounded timeout.

        The loop is the **only** coroutine that pops from the queue and
        the **only** one that calls ``ws.send_bytes``. All other
        methods are publisher-side (non-blocking).
        """
        try:
            while True:
                if not self._queue:
                    if self._stopped:
                        return
                    await self._wakeup.wait()
                    self._wakeup.clear()
                    continue
                payload = self._queue.popleft()
                self._metrics.queued = len(self._queue)
                self._sending = True
                try:
                    try:
                        await asyncio.wait_for(
                            self._ws.send_bytes(payload),
                            timeout=self._cfg.send_timeout_s,
                        )
                    except asyncio.TimeoutError:
                        self._metrics.timeouts += 1
                        self._metrics.consecutive_failures += 1
                        self._update_eviction()
                        logger.debug(
                            "outbound_channel_send_timeout timeout_s=%.2f failures=%d",
                            self._cfg.send_timeout_s,
                            self._metrics.consecutive_failures,
                        )
                    except asyncio.CancelledError:
                        raise
                    except Exception:  # noqa: BLE001 — transport errors are opaque
                        self._metrics.send_errors += 1
                        self._metrics.consecutive_failures += 1
                        self._update_eviction()
                        logger.warning(
                            "outbound_channel_send_error failures=%d",
                            self._metrics.consecutive_failures,
                            exc_info=True,
                        )
                    else:
                        self._metrics.sent += 1
                        self._metrics.consecutive_failures = 0
                finally:
                    self._sending = False
        except asyncio.CancelledError:
            raise

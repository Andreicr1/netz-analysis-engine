"""Rate-limited WebSocket broadcaster — fan-out with per-connection
isolation and slow-consumer eviction.

Stability Guardrails §2.2 — satisfies P1 (Bounded), P3 (Isolated),
P4 (Lifecycle-correct).

Problem this solves
-------------------
The legacy ``ConnectionManager._fanout`` keyed connections by
``id(ws)`` — a Python identity that is **reusable** after garbage
collection, allowing silent cross-talk between recycled slots — and
iterated sequentially over all subscribers calling ``await
ws.send_bytes(payload)`` directly, with no per-connection buffering
and no send timeout. A single slow client could stall the fan-out of
every ticker it was subscribed to.

The broadcaster owns one ``BoundedOutboundChannel`` per connection,
keys them by a freshly-minted ``ConnectionId`` (UUID), and performs
fan-out by calling ``channel.offer(payload)`` on each target. Offer
is synchronous and non-blocking, so the fan-out cost is O(N) in
dictionary lookups — independent of client send latency.

Slow-consumer handling is decoupled from the hot path: a background
**eviction sweeper** task polls the ``is_evictable`` flag on each
channel once every ``eviction_poll_s`` seconds and detaches any
channel that has crossed its threshold. The publisher never waits on
a slow client, and the slow client never prevents fast clients from
seeing fresh data.

What this primitive guarantees
------------------------------
- **UUID identity.** Every attached connection gets a
  ``ConnectionId`` (fresh UUID). ``id(ws)`` is never used as a key.
  Recycled Python identities cannot cause collisions.
- **Per-connection isolation.** Each connection has its own
  ``BoundedOutboundChannel`` with its own drain task, its own queue,
  and its own timeouts. A stuck client cannot block any other client.
- **Bounded attachment.** ``max_connections`` caps the number of
  attached clients. ``attach()`` raises ``BroadcasterFullError`` when
  the cap is reached. No silent growth.
- **Snapshot iteration.** ``fanout()`` snapshots the current
  connection set before iterating, so concurrent ``attach``/``detach``
  calls cannot cause ``RuntimeError: dictionary changed size during
  iteration``. Lost updates during the snapshot window are acceptable —
  the new connection simply starts receiving from the next fan-out.
- **Background eviction.** A dedicated eviction task detaches slow
  consumers without coupling to the publisher loop.
- **Deterministic teardown.** ``close()`` stops the eviction task and
  drains every attached channel before returning.

Non-goals (v1)
--------------
- No fair scheduling / priority queues. Every connection is equal.
- No cross-connection deduplication. If the same payload is offered
  for N connections, it's N copies in N queues.
- No metrics export to Prometheus. ``metrics`` exposes counters
  locally — export is Milestone 3 observability work.

Usage
-----
```python
from app.core.runtime.broadcaster import (
    BroadcasterConfig, RateLimitedBroadcaster, make_connection_id,
)
from app.core.runtime.outbound_channel import ChannelConfig

broadcaster = RateLimitedBroadcaster(
    channel_cfg=ChannelConfig(max_queued=256, send_timeout_s=2.0),
    cfg=BroadcasterConfig(max_connections=64),
)
await broadcaster.start()

conn_id = make_connection_id()
await broadcaster.attach(conn_id, websocket)
try:
    result = broadcaster.fanout(payload, conn_ids={conn_id})
    # result.offered / result.dropped give per-fanout counts
finally:
    await broadcaster.detach(conn_id, drain=True)

await broadcaster.close()
```
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NewType

from app.core.runtime.outbound_channel import (
    BoundedOutboundChannel,
    ChannelConfig,
    WebSocketLike,
)

logger = logging.getLogger(__name__)


# ── Identity ───────────────────────────────────────────────────────


ConnectionId = NewType("ConnectionId", uuid.UUID)


def make_connection_id() -> ConnectionId:
    """Mint a fresh ``ConnectionId``. Callers use this in ``attach()``."""
    return ConnectionId(uuid.uuid4())


# ── Errors ─────────────────────────────────────────────────────────


class BroadcasterError(Exception):
    """Base class for broadcaster errors."""


class BroadcasterFullError(BroadcasterError):
    """Raised when ``attach()`` is called at ``max_connections`` capacity."""


class BroadcasterClosedError(BroadcasterError):
    """Raised when ``attach()``/``fanout()`` is called after ``close()``."""


# ── Config ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BroadcasterConfig:
    """Declarative broadcaster configuration.

    ``max_connections`` is the hard cap on attached connections. The
    default of 64 is intentionally conservative — raise it deliberately
    for deployments that demand more, and verify memory with the soak
    test from §6.5 C18 of the design spec.
    """

    max_connections: int = 64
    eviction_poll_s: float = 0.5
    # Whether to raise or silently skip when fanout targets a
    # ConnectionId that is not attached. Default is "lenient" because
    # fanout call sites may hold stale ID sets from a previous frame.
    strict_fanout_targets: bool = False

    def __post_init__(self) -> None:
        if self.max_connections <= 0:
            raise ValueError("BroadcasterConfig.max_connections must be > 0")
        if self.eviction_poll_s <= 0:
            raise ValueError("BroadcasterConfig.eviction_poll_s must be > 0")


# ── Result & metrics ───────────────────────────────────────────────


@dataclass(frozen=True)
class FanoutResult:
    """Return value of ``fanout()`` — per-call counters.

    ``offered`` counts payloads accepted by the target channels
    (a ``DROP_OLDEST`` acceptance still counts as offered).
    ``dropped`` counts channels whose ``offer()`` returned False
    (``DROP_NEWEST`` rejection). ``missing`` counts fanout targets
    that were not attached at snapshot time.
    """

    offered: int
    dropped: int
    missing: int


@dataclass
class BroadcasterMetrics:
    """Observable counters for a ``RateLimitedBroadcaster``."""

    attached: int = 0
    peak_attached: int = 0
    total_attached: int = 0
    total_detached: int = 0
    total_evicted: int = 0
    total_fanout_calls: int = 0
    total_fanout_offered: int = 0
    total_fanout_dropped: int = 0
    total_fanout_missing: int = 0


# ── Broadcaster ────────────────────────────────────────────────────


class RateLimitedBroadcaster:
    """Fan-out primitive that owns per-connection outbound channels."""

    def __init__(
        self,
        channel_cfg: ChannelConfig,
        cfg: BroadcasterConfig | None = None,
    ) -> None:
        self._channel_cfg = channel_cfg
        self._cfg = cfg or BroadcasterConfig()
        self._channels: dict[ConnectionId, BoundedOutboundChannel] = {}
        self._mutation_lock = asyncio.Lock()
        self._sweeper_task: asyncio.Task[None] | None = None
        self._started = False
        self._closed = False
        self._metrics = BroadcasterMetrics()

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Start the background eviction sweeper. Idempotent."""
        if self._started or self._closed:
            return
        self._started = True
        self._sweeper_task = asyncio.create_task(
            self._eviction_sweeper(),
            name="broadcaster_eviction_sweeper",
        )

    async def close(self) -> None:
        """Detach every attached channel and stop the sweeper.

        After ``close()``, the broadcaster cannot be reused. Create
        a new instance if you need one.
        """
        if self._closed:
            return
        self._closed = True

        task = self._sweeper_task
        self._sweeper_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        async with self._mutation_lock:
            conn_ids = list(self._channels.keys())
        for conn_id in conn_ids:
            await self.detach(conn_id, drain=True)
        self._started = False

    # ── Attach / detach ────────────────────────────────────────

    async def attach(self, conn_id: ConnectionId, ws: WebSocketLike) -> None:
        """Register a new connection. Spawns its drain task.

        Raises:
            BroadcasterClosedError: if called after ``close()``.
            BroadcasterFullError: if at ``max_connections`` capacity.
            ValueError: if ``conn_id`` is already attached.
        """
        if self._closed:
            raise BroadcasterClosedError("broadcaster is closed")

        async with self._mutation_lock:
            if conn_id in self._channels:
                raise ValueError(f"ConnectionId {conn_id} already attached")
            if len(self._channels) >= self._cfg.max_connections:
                raise BroadcasterFullError(
                    f"broadcaster at capacity ({self._cfg.max_connections})",
                )
            channel = BoundedOutboundChannel(ws, self._channel_cfg)
            await channel.start()
            self._channels[conn_id] = channel
            self._metrics.attached = len(self._channels)
            self._metrics.total_attached += 1
            if self._metrics.attached > self._metrics.peak_attached:
                self._metrics.peak_attached = self._metrics.attached

    async def detach(
        self,
        conn_id: ConnectionId,
        *,
        drain: bool = False,
    ) -> bool:
        """Remove a connection and tear down its channel.

        Returns True if a channel was detached, False if ``conn_id``
        was not attached.
        """
        async with self._mutation_lock:
            channel = self._channels.pop(conn_id, None)
            self._metrics.attached = len(self._channels)
        if channel is None:
            return False
        await channel.stop(drain=drain)
        self._metrics.total_detached += 1
        return True

    def is_attached(self, conn_id: ConnectionId) -> bool:
        return conn_id in self._channels

    @property
    def attached_count(self) -> int:
        return len(self._channels)

    @property
    def metrics(self) -> BroadcasterMetrics:
        self._metrics.attached = len(self._channels)
        return self._metrics

    # ── Fan-out ────────────────────────────────────────────────

    def fanout(
        self,
        payload: bytes,
        conn_ids: Iterable[ConnectionId],
    ) -> FanoutResult:
        """Offer ``payload`` to each target channel. Non-blocking.

        The set of targets is snapshotted before iteration, so
        concurrent ``attach``/``detach`` calls are safe. Targets not
        attached at snapshot time count toward ``missing`` in the
        result (and raise ``KeyError`` when ``strict_fanout_targets``
        is True).
        """
        if self._closed:
            raise BroadcasterClosedError("broadcaster is closed")

        # Snapshot: copy the channel map once to avoid iteration races.
        snapshot = dict(self._channels)
        offered = 0
        dropped = 0
        missing = 0

        for conn_id in conn_ids:
            channel = snapshot.get(conn_id)
            if channel is None:
                missing += 1
                if self._cfg.strict_fanout_targets:
                    raise KeyError(f"ConnectionId {conn_id} not attached")
                continue
            if channel.offer(payload):
                offered += 1
            else:
                dropped += 1

        self._metrics.total_fanout_calls += 1
        self._metrics.total_fanout_offered += offered
        self._metrics.total_fanout_dropped += dropped
        self._metrics.total_fanout_missing += missing

        return FanoutResult(offered=offered, dropped=dropped, missing=missing)

    def broadcast(self, payload: bytes) -> FanoutResult:
        """Fan-out to **every** attached connection. Convenience wrapper."""
        return self.fanout(payload, list(self._channels.keys()))

    # ── Eviction sweeper ──────────────────────────────────────

    async def _eviction_sweeper(self) -> None:
        """Periodically detach channels flagged as evictable."""
        try:
            while not self._closed:
                await asyncio.sleep(self._cfg.eviction_poll_s)
                if self._closed:
                    return
                evictable: list[ConnectionId] = [
                    cid
                    for cid, ch in list(self._channels.items())
                    if ch.is_evictable
                ]
                for cid in evictable:
                    detached = await self.detach(cid, drain=False)
                    if detached:
                        self._metrics.total_evicted += 1
                        logger.info(
                            "broadcaster_evicted_slow_consumer conn_id=%s",
                            cid,
                        )
        except asyncio.CancelledError:
            raise

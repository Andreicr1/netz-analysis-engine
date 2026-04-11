"""WebSocket Connection Manager — Redis Pub/Sub broadcast bridge.

Optimized for high-frequency market data:
  - ``orjson`` for sub-microsecond (de)serialization.
  - Per-ticker Redis channels (``market:prices:{TICKER}``) for selective
    subscription — clients only receive data they asked for, eliminating
    broadcast-to-all fan-out.
  - Batch publish: ``publish_price_ticks_batch()`` writes N ticks in a
    single Redis pipeline round-trip.
  - DEBUG-level latency tracing (``ingest_at`` → ``emit_at``) with zero
    overhead in production (guarded by ``logger.isEnabledFor``).

Stability Guardrails (Phase 2 retrofit, §4.1 B1.5/B1.6)
-------------------------------------------------------
The manager is now a thin orchestration layer over
``RateLimitedBroadcaster``. The broadcaster owns one
``BoundedOutboundChannel`` per connection and performs fan-out via
non-blocking ``offer()`` calls — a slow client can no longer stall the
delivery loop for any other client. Connections are keyed by
``ConnectionId`` (UUID) instead of the legacy ``id(ws)`` (a Python
identity that is reusable after garbage collection and would silently
allow cross-talk between recycled WebSocket slots).

Connection lifecycle:
  1. Client opens WS with JWT query param → authenticate_ws() validates.
  2. ``ConnectionManager.accept()`` mints a fresh ``ConnectionId``,
     attaches the connection to the broadcaster, and returns the
     ``ClientConnection`` (with ``conn_id`` field) to the route.
  3. Client sends ``{"action": "subscribe", "tickers": ["SPY", "QQQ"]}``
  4. Manager spawns per-ticker ``_channel_listener`` tasks for each
     subscribed ticker.  One asyncio.Task per channel, shared across
     all connections subscribed to that ticker.
  5. On each Redis message, the listener forwards to all connections
     watching that ticker via ``broadcaster.fanout()``.
  6. Heartbeat ping every 15s keeps the connection alive.
  7. ``disconnect(conn_id)`` detaches the channel and stops any
     orphaned per-ticker listeners.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import orjson
import redis.asyncio as aioredis
from fastapi import WebSocket, WebSocketDisconnect

from app.core.jobs.tracker import get_redis_pool
from app.core.runtime.broadcaster import (
    BroadcasterConfig,
    ConnectionId,
    RateLimitedBroadcaster,
    make_connection_id,
)
from app.core.runtime.outbound_channel import ChannelConfig, DropPolicy
from app.core.security.clerk_auth import Actor

logger = logging.getLogger(__name__)

MARKET_CHANNEL_PREFIX = "market:prices:"  # per-ticker: market:prices:SPY
HEARTBEAT_INTERVAL = 15  # seconds
_TRACE = logging.DEBUG  # Use DEBUG for latency traces

# ── Tunables for the per-connection outbound channels ──────────
# These defaults match §2.1 of the design spec: 256 messages queued
# per client, 2-second send timeout, drop the oldest tick when the
# queue is full (freshness > completeness for market data), and
# evict after 3 consecutive failures.
_DEFAULT_CHANNEL_CFG = ChannelConfig(
    max_queued=256,
    send_timeout_s=2.0,
    drop_policy=DropPolicy.DROP_OLDEST,
    eviction_threshold=3,
)
# Hard cap on simultaneously attached WS clients per process. Raised
# to 128 for Terminal Live Workspace density.
_DEFAULT_BROADCASTER_CFG = BroadcasterConfig(max_connections=128)

# Per-organization ceiling — prevents a single tenant from monopolising
# the WS pool. Exceeded → close with 1013 (Try Again Later).
_MAX_CONNECTIONS_PER_ORG = 16


def _channel_for(ticker: str) -> str:
    """Redis channel name for a single ticker."""
    return f"{MARKET_CHANNEL_PREFIX}{ticker}"


@dataclass
class ClientConnection:
    """Tracks a single authenticated WebSocket client.

    ``conn_id`` is the broadcaster identity — every call site that
    needs to address this connection (send_personal, disconnect,
    update_subscriptions) uses the UUID, never ``id(ws)``.
    """

    conn_id: ConnectionId
    ws: WebSocket
    actor: Actor
    tickers: set[str] = field(default_factory=set)


class ConnectionManager:
    """Manages WebSocket connections with per-ticker Redis Pub/Sub.

    Owns a ``RateLimitedBroadcaster`` for fan-out and a per-ticker
    Redis channel listener registry. Mutations of the connection /
    ticker maps are single-threaded by virtue of running on the
    asyncio event loop — no explicit lock is required because every
    public mutation is synchronous and the broadcaster handles its
    own internal serialisation.

    One instance per app (stored on ``app.state.ws_manager``).
    """

    def __init__(
        self,
        *,
        channel_cfg: ChannelConfig | None = None,
        broadcaster_cfg: BroadcasterConfig | None = None,
        max_per_org: int = _MAX_CONNECTIONS_PER_ORG,
    ) -> None:
        self._connections: dict[ConnectionId, ClientConnection] = {}
        # ticker -> set of conn_ids subscribed to it
        self._ticker_subs: dict[str, set[ConnectionId]] = {}
        # ticker -> asyncio.Task running the channel listener
        self._channel_tasks: dict[str, asyncio.Task[None]] = {}
        self._broadcaster = RateLimitedBroadcaster(
            channel_cfg=channel_cfg or _DEFAULT_CHANNEL_CFG,
            cfg=broadcaster_cfg or _DEFAULT_BROADCASTER_CFG,
        )
        self._started = False
        self._max_per_org = max_per_org
        # org_id -> set of conn_ids belonging to that org
        self._org_connections: dict[str, set[ConnectionId]] = {}

    @property
    def active_count(self) -> int:
        return len(self._connections)

    @property
    def active_channels(self) -> int:
        return len(self._channel_tasks)

    @property
    def broadcaster(self) -> RateLimitedBroadcaster:
        """Expose the underlying broadcaster (read-only — for metrics/tests)."""
        return self._broadcaster

    # ── Lifecycle ──────────────────────────────────────────────

    async def start(self) -> None:
        """Start the broadcaster's eviction sweeper. Idempotent.

        Safe to call multiple times. The lifespan handler in
        ``main.py`` calls this before any client can connect.
        """
        if self._started:
            return
        await self._broadcaster.start()
        self._started = True

    async def accept(self, ws: WebSocket, actor: Actor) -> ClientConnection:
        """Accept a new WebSocket connection and register it.

        Mints a fresh ``ConnectionId``, attaches the connection to the
        broadcaster (which spawns its drain task), and returns the
        ``ClientConnection`` so the route can hold the conn_id for the
        rest of the handler.

        Per-org limit: if the organization already has
        ``_max_per_org`` active connections the socket is closed with
        code **1013** (Try Again Later) before accepting.
        """
        # ── Per-org connection ceiling ────────────────────────────
        org_id = str(actor.organization_id) if actor.organization_id else "__none__"
        org_conns = self._org_connections.get(org_id)
        if org_conns is not None and len(org_conns) >= self._max_per_org:
            logger.warning(
                "ws_org_limit_reached org=%s limit=%d — closing 1013",
                org_id,
                self._max_per_org,
            )
            await ws.close(code=1013, reason="Too many connections for this organization")
            raise WebSocketDisconnect(code=1013)

        await ws.accept()
        # Lazy-start the broadcaster on first accept so test fixtures
        # that construct a fresh manager don't need to remember to
        # call start() before exercising the WS endpoint.
        if not self._started:
            await self.start()

        conn_id = make_connection_id()
        await self._broadcaster.attach(conn_id, ws)
        conn = ClientConnection(conn_id=conn_id, ws=ws, actor=actor)
        self._connections[conn_id] = conn

        # Track per-org
        if org_id not in self._org_connections:
            self._org_connections[org_id] = set()
        self._org_connections[org_id].add(conn_id)

        logger.info(
            "ws_connected conn_id=%s actor=%s org=%s active=%d org_active=%d",
            conn_id,
            actor.actor_id,
            actor.organization_id,
            self.active_count,
            len(self._org_connections[org_id]),
        )
        return conn

    async def disconnect(self, conn_id: ConnectionId) -> None:
        """Remove a connection and clean up its ticker subscriptions.

        Asynchronous because the broadcaster's ``detach`` cancels and
        joins the per-connection drain task — synchronous teardown
        would leak the task on busy event loops.
        """
        conn = self._connections.pop(conn_id, None)
        if conn is None:
            return

        # Remove from per-org tracking
        org_id = str(conn.actor.organization_id) if conn.actor.organization_id else "__none__"
        org_conns = self._org_connections.get(org_id)
        if org_conns is not None:
            org_conns.discard(conn_id)
            if not org_conns:
                del self._org_connections[org_id]

        # Remove from all ticker subscription sets
        for ticker in list(conn.tickers):
            subs = self._ticker_subs.get(ticker)
            if subs:
                subs.discard(conn_id)
                if not subs:
                    # No more subscribers — stop the channel listener
                    self._stop_channel(ticker)

        await self._broadcaster.detach(conn_id, drain=False)

        logger.info(
            "ws_disconnected conn_id=%s actor=%s active=%d",
            conn_id,
            conn.actor.actor_id,
            self.active_count,
        )

    def update_subscriptions(
        self,
        conn_id: ConnectionId,
        new_tickers: set[str],
    ) -> None:
        """Update the ticker subscriptions for a connection.

        Starts/stops per-ticker Redis channel listeners as needed.
        Synchronous — no I/O happens here, only dict mutations and
        ``asyncio.create_task`` for the listener spawn.
        """
        conn = self._connections.get(conn_id)
        if not conn:
            return

        old_tickers = conn.tickers
        added = new_tickers - old_tickers
        removed = old_tickers - new_tickers

        # Remove from old ticker sets
        for ticker in removed:
            subs = self._ticker_subs.get(ticker)
            if subs:
                subs.discard(conn_id)
                if not subs:
                    self._stop_channel(ticker)

        # Add to new ticker sets — start channel listeners if needed
        for ticker in added:
            if ticker not in self._ticker_subs:
                self._ticker_subs[ticker] = set()
            self._ticker_subs[ticker].add(conn_id)
            if ticker not in self._channel_tasks:
                self._channel_tasks[ticker] = asyncio.create_task(
                    self._channel_listener(ticker),
                    name=f"ws_channel_listener_{ticker}",
                )

        conn.tickers = set(new_tickers)

        logger.debug(
            "ws_subscriptions_updated conn_id=%s tickers=%s (+%d -%d)",
            conn_id,
            new_tickers,
            len(added),
            len(removed),
        )

    def _stop_channel(self, ticker: str) -> None:
        """Cancel the channel listener for a ticker with no subscribers."""
        self._ticker_subs.pop(ticker, None)
        task = self._channel_tasks.pop(ticker, None)
        if task and not task.done():
            task.cancel()

    async def _channel_listener(self, ticker: str) -> None:
        """Listen to a single ticker's Redis channel and forward to subscribers.

        One task per ticker, shared across all WS connections watching it.
        Auto-reconnects on Redis errors with exponential backoff.
        """
        backoff = 1
        max_backoff = 30
        channel = _channel_for(ticker)

        while ticker in self._ticker_subs and self._ticker_subs[ticker]:
            pool = get_redis_pool()
            r = aioredis.Redis(connection_pool=pool)
            pubsub = r.pubsub()

            try:
                await pubsub.subscribe(channel)
                logger.debug("channel_listener_started channel=%s", channel)
                backoff = 1

                async for raw_message in pubsub.listen():
                    if raw_message["type"] != "message":
                        continue

                    # Check if ticker still has subscribers
                    subs = self._ticker_subs.get(ticker)
                    if not subs:
                        break

                    try:
                        message = orjson.loads(raw_message["data"])
                    except (orjson.JSONDecodeError, TypeError) as e:
                        logger.warning("redis_message_parse_error channel=%s: %s", channel, e)
                        continue

                    # Latency trace
                    if logger.isEnabledFor(_TRACE):
                        ingest_at = message.get("_ingest_at")
                        if ingest_at:
                            emit_at = time.monotonic_ns()
                            latency_us = (emit_at - ingest_at) / 1_000
                            logger.debug(
                                "ws_emit ticker=%s latency_us=%.1f subscribers=%d",
                                ticker,
                                latency_us,
                                len(subs),
                            )
                            # Strip internal field before sending to client
                            message.pop("_ingest_at", None)

                    self._fanout(message, subs)

            except asyncio.CancelledError:
                logger.debug("channel_listener_cancelled channel=%s", channel)
                break
            except Exception:
                logger.exception("channel_listener_error channel=%s backoff=%ds", channel, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
            finally:
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.aclose()
                    await r.aclose()
                except Exception:
                    pass

    def _fanout(self, message: dict[str, Any], conn_ids: set[ConnectionId]) -> None:
        """Offer a serialized message to every subscriber via the broadcaster.

        Non-blocking. Eviction of slow consumers happens in the
        broadcaster's background sweeper, not on this hot path.
        """
        if not conn_ids:
            return
        payload = orjson.dumps(message)
        # Snapshot to avoid concurrent-mutation surprises during the
        # broadcaster's own iteration.
        targets = list(conn_ids)
        result = self._broadcaster.fanout(payload, targets)
        if result.dropped or result.missing:
            logger.debug(
                "ws_fanout_partial offered=%d dropped=%d missing=%d",
                result.offered,
                result.dropped,
                result.missing,
            )

    async def broadcast_to_subscribers(self, message: dict[str, Any]) -> None:
        """Send a price message to all connections subscribed to its ticker.

        Kept for backward compatibility with the legacy single-channel
        ``redis_subscriber`` and direct-publish scenarios. Prefer
        per-ticker Redis channels for production traffic.
        """
        ticker = str(message.get("ticker", ""))
        if not ticker:
            return
        subs = self._ticker_subs.get(ticker)
        if not subs:
            return
        self._fanout(message, subs)

    async def send_personal(
        self,
        conn_id: ConnectionId,
        data: dict[str, Any],
    ) -> None:
        """Send a message to a single connection through its outbound channel.

        Routed through the broadcaster so a slow client cannot block
        the caller — the message lands in the per-connection queue
        and is sent (or dropped) by the drain task.
        """
        if conn_id not in self._connections:
            return
        payload = orjson.dumps(data)
        self._broadcaster.fanout(payload, [conn_id])

    async def shutdown(self) -> None:
        """Cancel all channel listeners and tear down the broadcaster.

        Called from the application lifespan only.
        """
        for ticker in list(self._channel_tasks):
            self._stop_channel(ticker)
        # Detach every connection through the broadcaster (drains
        # in-flight queues up to the per-channel send timeout).
        await self._broadcaster.close()
        self._connections.clear()
        self._started = False


# ── Legacy single-channel subscriber (kept for rollback) ───────


async def redis_subscriber(manager: ConnectionManager) -> None:
    """Background task: subscribe to ``market:prices`` Redis channel
    and broadcast to WebSocket clients.

    DEPRECATED — per-ticker channels are now used.  This subscriber handles
    the legacy ``market:prices`` global channel for any callers that still
    use ``publish_price_tick()`` directly.
    """
    backoff = 1
    max_backoff = 30

    while True:
        pool = get_redis_pool()
        r = aioredis.Redis(connection_pool=pool)
        pubsub = r.pubsub()

        try:
            await pubsub.subscribe("market:prices")
            logger.info("redis_subscriber_started channel=market:prices (legacy)")
            backoff = 1

            async for raw_message in pubsub.listen():
                if raw_message["type"] != "message":
                    continue
                try:
                    message = orjson.loads(raw_message["data"])
                    await manager.broadcast_to_subscribers(message)
                except (orjson.JSONDecodeError, TypeError) as e:
                    logger.warning("redis_message_parse_error: %s", e)

        except asyncio.CancelledError:
            logger.info("redis_subscriber_cancelled")
            break
        except Exception:
            logger.exception("redis_subscriber_error backoff=%ds", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)
        finally:
            try:
                await pubsub.unsubscribe("market:prices")
                await pubsub.aclose()
                await r.aclose()
            except Exception:
                pass


# ── Publish helpers ────────────────────────────────────────────


async def publish_price_tick(tick: dict[str, Any]) -> None:
    """Publish a single price tick to the per-ticker Redis channel.

    Also publishes to the legacy ``market:prices`` channel for backward
    compatibility.
    """
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        # Inject monotonic timestamp for latency tracing
        if logger.isEnabledFor(_TRACE):
            tick["_ingest_at"] = time.monotonic_ns()

        payload = orjson.dumps(tick)
        ticker = tick.get("ticker", "")

        async with r.pipeline(transaction=False) as pipe:
            pipe.publish(_channel_for(ticker), payload)
            pipe.publish("market:prices", payload)  # legacy
            await pipe.execute()
    finally:
        await r.aclose()


async def publish_price_ticks_batch(ticks: list[dict[str, Any]]) -> None:
    """Publish multiple price ticks in a single Redis pipeline round-trip.

    Called by the Tiingo WS ingestion worker after accumulating a batch
    (e.g., 50-100ms window).  One pipeline.execute() for N ticks is O(1)
    network round-trips vs O(N) for individual publishes.

    Each tick is published to its per-ticker channel AND the legacy global
    channel.
    """
    if not ticks:
        return

    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        trace = logger.isEnabledFor(_TRACE)
        now_ns = time.monotonic_ns() if trace else 0

        async with r.pipeline(transaction=False) as pipe:
            for tick in ticks:
                if trace:
                    tick["_ingest_at"] = now_ns

                payload = orjson.dumps(tick)
                ticker = tick.get("ticker", "")
                pipe.publish(_channel_for(ticker), payload)
                pipe.publish("market:prices", payload)  # legacy

            await pipe.execute()

        if trace:
            logger.debug(
                "batch_published count=%d tickers=%s",
                len(ticks),
                {t.get("ticker") for t in ticks},
            )
    finally:
        await r.aclose()

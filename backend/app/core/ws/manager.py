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

Connection lifecycle:
  1. Client opens WS with JWT query param → authenticate_ws() validates.
  2. Client sends ``{"action": "subscribe", "tickers": ["SPY", "QQQ"]}``
  3. Manager spawns per-ticker ``_channel_listener`` tasks for each
     subscribed ticker.  One asyncio.Task per channel, shared across
     all connections subscribed to that ticker.
  4. On each Redis message, forward to all connections watching that ticker.
  5. Heartbeat ping every 15s keeps the connection alive.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import orjson
import redis.asyncio as aioredis
from fastapi import WebSocket

from app.core.jobs.tracker import get_redis_pool
from app.core.security.clerk_auth import Actor

logger = logging.getLogger(__name__)

MARKET_CHANNEL_PREFIX = "market:prices:"  # per-ticker: market:prices:SPY
HEARTBEAT_INTERVAL = 15  # seconds
_TRACE = logging.DEBUG  # Use DEBUG for latency traces


def _channel_for(ticker: str) -> str:
    """Redis channel name for a single ticker."""
    return f"{MARKET_CHANNEL_PREFIX}{ticker}"


@dataclass
class ClientConnection:
    """Tracks a single authenticated WebSocket client."""

    ws: WebSocket
    actor: Actor
    tickers: set[str] = field(default_factory=set)


class ConnectionManager:
    """Manages WebSocket connections with per-ticker Redis Pub/Sub.

    Thread-safe: all mutations go through asyncio — no threading.Lock needed.
    One instance per app (stored on ``app.state``).
    """

    def __init__(self) -> None:
        self._connections: dict[int, ClientConnection] = {}
        # ticker -> set of ws ids subscribed to it
        self._ticker_subs: dict[str, set[int]] = {}
        # ticker -> asyncio.Task running the channel listener
        self._channel_tasks: dict[str, asyncio.Task] = {}

    @property
    def active_count(self) -> int:
        return len(self._connections)

    @property
    def active_channels(self) -> int:
        return len(self._channel_tasks)

    async def accept(self, ws: WebSocket, actor: Actor) -> ClientConnection:
        """Accept a new WebSocket connection and register it."""
        await ws.accept()
        conn = ClientConnection(ws=ws, actor=actor)
        self._connections[id(ws)] = conn
        logger.info(
            "ws_connected actor=%s org=%s active=%d",
            actor.actor_id,
            actor.organization_id,
            self.active_count,
        )
        return conn

    def disconnect(self, ws: WebSocket) -> None:
        """Remove a connection and clean up its ticker subscriptions."""
        conn = self._connections.pop(id(ws), None)
        if not conn:
            return

        ws_id = id(ws)
        # Remove from all ticker subscription sets
        for ticker in list(conn.tickers):
            subs = self._ticker_subs.get(ticker)
            if subs:
                subs.discard(ws_id)
                if not subs:
                    # No more subscribers — stop the channel listener
                    self._stop_channel(ticker)

        logger.info(
            "ws_disconnected actor=%s active=%d",
            conn.actor.actor_id,
            self.active_count,
        )

    def update_subscriptions(self, ws: WebSocket, new_tickers: set[str]) -> None:
        """Update the ticker subscriptions for a connection.

        Starts/stops per-ticker Redis channel listeners as needed.
        """
        conn = self._connections.get(id(ws))
        if not conn:
            return

        ws_id = id(ws)
        old_tickers = conn.tickers
        added = new_tickers - old_tickers
        removed = old_tickers - new_tickers

        # Remove from old ticker sets
        for ticker in removed:
            subs = self._ticker_subs.get(ticker)
            if subs:
                subs.discard(ws_id)
                if not subs:
                    self._stop_channel(ticker)

        # Add to new ticker sets — start channel listeners if needed
        for ticker in added:
            if ticker not in self._ticker_subs:
                self._ticker_subs[ticker] = set()
            self._ticker_subs[ticker].add(ws_id)
            if ticker not in self._channel_tasks:
                self._channel_tasks[ticker] = asyncio.create_task(
                    self._channel_listener(ticker),
                )

        conn.tickers = new_tickers

        logger.debug(
            "ws_subscriptions_updated actor=%s tickers=%s (+%d -%d)",
            conn.actor.actor_id,
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

                    await self._fanout(message, subs)

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

    async def _fanout(self, message: dict[str, Any], ws_ids: set[int]) -> None:
        """Send a message to all connections in the subscriber set."""
        stale: list[WebSocket] = []
        payload = orjson.dumps(message)

        for ws_id in list(ws_ids):
            conn = self._connections.get(ws_id)
            if not conn:
                ws_ids.discard(ws_id)
                continue
            try:
                await conn.ws.send_bytes(payload)
            except Exception:
                stale.append(conn.ws)

        for ws in stale:
            self.disconnect(ws)

    async def broadcast_to_subscribers(self, message: dict[str, Any]) -> None:
        """Send a price message to all connections subscribed to its ticker.

        Kept for backward compatibility with tests and direct-publish scenarios.
        Prefer per-ticker Redis channels for production traffic.
        """
        ticker = message.get("ticker", "")
        stale: list[WebSocket] = []
        payload = orjson.dumps(message)

        for ws_id, conn in self._connections.items():
            if ticker in conn.tickers:
                try:
                    await conn.ws.send_bytes(payload)
                except Exception:
                    stale.append(conn.ws)

        for ws in stale:
            self.disconnect(ws)

    async def send_personal(self, ws: WebSocket, data: dict[str, Any]) -> None:
        """Send a message to a single connection."""
        try:
            await ws.send_bytes(orjson.dumps(data))
        except Exception:
            self.disconnect(ws)

    async def shutdown(self) -> None:
        """Cancel all channel listeners on app shutdown."""
        for ticker in list(self._channel_tasks):
            self._stop_channel(ticker)


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

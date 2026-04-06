"""WebSocket Connection Manager — Redis Pub/Sub broadcast bridge.

Follows the same Redis Pub/Sub pattern as ``app.core.jobs.tracker``:
  - Workers publish price ticks to ``market:prices`` Redis channel.
  - Each WebSocket connection subscribes to that channel and forwards
    only tickers the client requested.

Connection lifecycle:
  1. Client opens WS with JWT query param → authenticate_ws() validates.
  2. Client sends ``{"action": "subscribe", "tickers": ["SPY", "QQQ"]}``
  3. Manager subscribes to ``market:prices`` Redis channel (shared across
     all connections — one subscriber per WS connection).
  4. On each Redis message, filter by client's ticker set and forward.
  5. Heartbeat ping every 15s keeps the connection alive.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import redis.asyncio as aioredis
from fastapi import WebSocket

from app.core.jobs.tracker import get_redis_pool
from app.core.security.clerk_auth import Actor

logger = logging.getLogger(__name__)

MARKET_PRICES_CHANNEL = "market:prices"
HEARTBEAT_INTERVAL = 15  # seconds


@dataclass
class ClientConnection:
    """Tracks a single authenticated WebSocket client."""

    ws: WebSocket
    actor: Actor
    tickers: set[str] = field(default_factory=set)


class ConnectionManager:
    """Manages WebSocket connections with Redis Pub/Sub price broadcast.

    Thread-safe: all mutations go through asyncio — no threading.Lock needed.
    One instance per app (stored on ``app.state``).
    """

    def __init__(self) -> None:
        self._connections: dict[int, ClientConnection] = {}

    @property
    def active_count(self) -> int:
        return len(self._connections)

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
        """Remove a connection from the registry."""
        conn = self._connections.pop(id(ws), None)
        if conn:
            logger.info(
                "ws_disconnected actor=%s active=%d",
                conn.actor.actor_id,
                self.active_count,
            )

    def update_subscriptions(self, ws: WebSocket, tickers: set[str]) -> None:
        """Update the ticker subscriptions for a connection."""
        conn = self._connections.get(id(ws))
        if conn:
            conn.tickers = tickers
            logger.debug(
                "ws_subscriptions_updated actor=%s tickers=%s",
                conn.actor.actor_id,
                tickers,
            )

    async def broadcast_to_subscribers(self, message: dict[str, Any]) -> None:
        """Send a price message to all connections subscribed to its ticker."""
        ticker = message.get("ticker", "")
        stale: list[WebSocket] = []

        for ws_id, conn in self._connections.items():
            if ticker in conn.tickers:
                try:
                    await conn.ws.send_json(message)
                except Exception:
                    stale.append(conn.ws)

        for ws in stale:
            self.disconnect(ws)

    async def send_personal(self, ws: WebSocket, data: dict[str, Any]) -> None:
        """Send a message to a single connection."""
        try:
            await ws.send_json(data)
        except Exception:
            self.disconnect(ws)


async def redis_subscriber(manager: ConnectionManager) -> None:
    """Background task: subscribe to ``market:prices`` Redis channel
    and broadcast to WebSocket clients.

    Runs for the lifetime of the app (started in lifespan, cancelled on shutdown).
    Auto-reconnects on Redis errors with exponential backoff.
    """
    backoff = 1
    max_backoff = 30

    while True:
        pool = get_redis_pool()
        r = aioredis.Redis(connection_pool=pool)
        pubsub = r.pubsub()

        try:
            await pubsub.subscribe(MARKET_PRICES_CHANNEL)
            logger.info("redis_subscriber_started channel=%s", MARKET_PRICES_CHANNEL)
            backoff = 1  # Reset on successful connect

            async for raw_message in pubsub.listen():
                if raw_message["type"] != "message":
                    continue
                try:
                    message = json.loads(raw_message["data"])
                    await manager.broadcast_to_subscribers(message)
                except (json.JSONDecodeError, TypeError) as e:
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
                await pubsub.unsubscribe(MARKET_PRICES_CHANNEL)
                await pubsub.aclose()
                await r.aclose()
            except Exception:
                pass


async def publish_price_tick(tick: dict[str, Any]) -> None:
    """Publish a single price tick to the ``market:prices`` Redis channel.

    Called by background workers / ingestion tasks — NOT by user-facing code.
    """
    pool = get_redis_pool()
    r = aioredis.Redis(connection_pool=pool)
    try:
        payload = json.dumps(tick)
        await r.publish(MARKET_PRICES_CHANNEL, payload)
    finally:
        await r.aclose()

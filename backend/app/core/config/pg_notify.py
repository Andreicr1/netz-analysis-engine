"""
PgNotifier — Dedicated asyncpg listener for pg_notify cache invalidation.

Uses a dedicated connection (NOT from pool — pool drops listeners on release).
TCP keepalives for health, exponential backoff reconnect.
On reconnection: flush entire config cache (prevents stale data during reconnect window).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


class PgNotifier:
    """Listen for PostgreSQL NOTIFY events and dispatch to handlers."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._handlers: dict[str, list[Callable[[dict], Any]]] = {}
        self._connection: Any = None  # asyncpg.Connection
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def subscribe(self, channel: str, handler: Callable[[dict], Any]) -> None:
        """Register a handler for a channel. Call before start()."""
        self._handlers.setdefault(channel, []).append(handler)

    async def start(self) -> None:
        """Start listening. Creates dedicated asyncpg connection."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._listen_loop())

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._connection:
            try:
                await self._connection.close()
            except Exception:
                pass
            self._connection = None

    async def _listen_loop(self) -> None:
        """Main loop — connect, listen, reconnect on failure."""
        backoff = 1.0

        while self._running:
            try:
                await self._connect_and_listen()
                backoff = 1.0  # Reset on successful connection
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("PgNotifier connection lost, reconnecting in %.1fs", backoff)
                # Flush all caches on reconnection (prevents stale data)
                self._flush_all_caches()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30.0)

    async def _connect_and_listen(self) -> None:
        """Connect with TCP keepalives and listen."""
        import asyncpg

        self._connection = await asyncpg.connect(
            self._dsn,
            server_settings={
                "tcp_keepalives_idle": "30",
                "tcp_keepalives_interval": "10",
                "tcp_keepalives_count": "3",
            },
        )

        def _notification_handler(conn: Any, pid: int, channel: str, payload: str) -> None:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"raw": payload}

            handlers = self._handlers.get(channel, [])
            for handler in handlers:
                try:
                    if inspect.iscoroutinefunction(handler):
                        asyncio.ensure_future(self._invoke_async_handler(handler, data, channel))
                    else:
                        handler(data)
                except Exception:
                    logger.exception("PgNotifier handler error on channel %s", channel)

        for channel in self._handlers:
            await self._connection.add_listener(channel, _notification_handler)
            logger.info("PgNotifier: listening on channel '%s'", channel)

        # Keep connection alive — asyncpg listens until connection drops
        while self._running:
            await asyncio.sleep(1)

    @staticmethod
    async def _invoke_async_handler(
        handler: Callable[[dict], Any], data: dict, channel: str
    ) -> None:
        """Await an async handler and log failures explicitly."""
        try:
            await handler(data)
        except Exception:
            logger.exception("PgNotifier async handler error on channel %s", channel)

    def _flush_all_caches(self) -> None:
        """Flush entire config cache on reconnection."""
        try:
            from app.core.config.config_service import _config_cache
            _config_cache.clear()
            logger.info("PgNotifier: flushed config cache on reconnection")
        except Exception:
            logger.exception("PgNotifier: failed to flush config cache")

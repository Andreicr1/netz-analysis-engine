"""
PgNotifyListener — Cross-Process Cache Invalidation via pg_notify
==================================================================

Listens for `netz_config_changed` notifications on a dedicated asyncpg
connection (NOT from the pool — pooled connections drop listeners on release).

On notification: invalidates the specific TTLCache key in ConfigService.

Register in FastAPI lifespan via start() / stop().
"""

from __future__ import annotations

import asyncio
import json
import logging
from urllib.parse import urlparse, urlunparse

from app.core.config.config_service import ConfigService
from app.core.config.settings import settings

logger = logging.getLogger(__name__)

CHANNEL = "netz_config_changed"
HEALTH_CHECK_INTERVAL = 30  # seconds
RECONNECT_BASE = 1.0  # seconds
RECONNECT_CAP = 30.0  # seconds


def _asyncpg_dsn() -> str:
    """Convert SQLAlchemy DATABASE_URL to raw asyncpg DSN.

    SQLAlchemy uses 'postgresql+asyncpg://...'
    asyncpg wants 'postgresql://...'
    """
    url = settings.database_url
    parsed = urlparse(url)
    # Replace scheme: postgresql+asyncpg → postgresql
    clean_scheme = parsed.scheme.replace("+asyncpg", "")
    return urlunparse(parsed._replace(scheme=clean_scheme))


class PgNotifyListener:
    """Background listener for pg_notify config change events.

    Uses a dedicated asyncpg connection (not from pool) because
    LISTEN requires a persistent connection — pool connections
    drop listeners when returned.
    """

    def __init__(self) -> None:
        self._conn = None
        self._task: asyncio.Task | None = None
        self._health_task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        """Start listening in background. Safe to call from lifespan."""
        self._stopping = False
        self._task = asyncio.create_task(self._listen_loop())
        self._health_task = asyncio.create_task(self._health_loop())
        logger.info("PgNotifyListener started — channel=%s", CHANNEL)

    async def stop(self) -> None:
        """Stop listener and close connection."""
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass
        await self._close_conn()
        logger.info("PgNotifyListener stopped")

    async def _listen_loop(self) -> None:
        """Main listener loop with exponential backoff reconnect."""
        import asyncpg

        backoff = RECONNECT_BASE

        while not self._stopping:
            try:
                dsn = _asyncpg_dsn()
                self._conn = await asyncpg.connect(dsn)
                backoff = RECONNECT_BASE  # Reset on successful connect

                await self._conn.add_listener(CHANNEL, self._on_notification)
                logger.info("pg_notify LISTEN registered on %s", CHANNEL)

                # Keep connection alive — asyncpg listener runs callbacks
                # in the connection's event loop. We just wait until stopped.
                while not self._stopping:
                    await asyncio.sleep(1)

            except asyncio.CancelledError:
                break
            except Exception:
                if self._stopping:
                    break
                logger.warning(
                    "PgNotifyListener connection lost — reconnecting in %.1fs",
                    backoff,
                    exc_info=True,
                )
                await self._close_conn()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_CAP)

    async def _health_loop(self) -> None:
        """Periodic health check to detect dead TCP connections."""
        while not self._stopping:
            try:
                await asyncio.sleep(HEALTH_CHECK_INTERVAL)
                if self._conn and not self._conn.is_closed():
                    await self._conn.fetchval("SELECT 1")
            except asyncio.CancelledError:
                break
            except Exception:
                logger.warning(
                    "PgNotifyListener health check failed — connection may be dead",
                    exc_info=True,
                )
                # Close the dead connection — listen_loop will reconnect
                await self._close_conn()

    def _on_notification(
        self,
        connection: object,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        """Handle pg_notify callback — invalidate cache entry."""
        try:
            data = json.loads(payload)
            vertical = data["vertical"]
            config_type = data["config_type"]
            org_id = data.get("org_id")

            ConfigService.invalidate(vertical, config_type, org_id)
            logger.debug(
                "Cache invalidated via pg_notify: %s/%s/%s",
                vertical,
                config_type,
                org_id,
            )
        except Exception:
            logger.warning(
                "Failed to process pg_notify payload: %s",
                payload,
                exc_info=True,
            )

    async def _close_conn(self) -> None:
        """Safely close the dedicated connection."""
        if self._conn and not self._conn.is_closed():
            try:
                await self._conn.close()
            except Exception:
                pass
        self._conn = None


# Module-level singleton — created lazily, NOT at import time
_listener: PgNotifyListener | None = None


def get_pg_notify_listener() -> PgNotifyListener:
    """Get or create the singleton PgNotifyListener."""
    global _listener
    if _listener is None:
        _listener = PgNotifyListener()
    return _listener

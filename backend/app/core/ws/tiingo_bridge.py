"""Tiingo WebSocket → Redis bridge.

Connects to Tiingo's IEX WebSocket and republishes trade ticks to
per-ticker Redis channels so that ``ConnectionManager`` can forward
them to frontend WebSocket clients.

Lifecycle:
  - Created in ``main.py`` lifespan, stored on ``app.state.tiingo_bridge``.
  - ``subscribe(tickers)`` / ``unsubscribe(tickers)`` called by the WS
    endpoint when clients change their ticker sets.
  - ``shutdown()`` called on app teardown.

For mutual funds: Tiingo WS only streams equities/ETFs (IEX exchange).
MF NAV updates daily via the ``instrument_ingestion`` worker and
``nav_timeseries`` table.  The bridge gracefully ignores tickers
that don't produce WS trades.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import orjson

from app.core.config.settings import settings
from app.core.ws.manager import publish_price_ticks_batch

logger = logging.getLogger(__name__)

# Buffer window — accumulate ticks before flushing to Redis.
# 50 ms keeps perceived latency low; the size cap below is the real
# backpressure guard once the IEX firehose is firing thousands of ticks/sec.
BUFFER_WINDOW_S = 0.05  # 50ms
# Hard cap on buffer size — flushes early if a tick burst exceeds this,
# protecting Redis publish latency from quadratic batch growth.
BUFFER_MAX_SIZE = 5000

# Tiingo IEX WS thresholdLevel:
#   0  = ALL data (Q + T) — institutional firehose
#   5  = Top-of-book trades only — free-tier restriction
# Institutional plan grants firehose access; free-tier subscription cap removed.
WS_THRESHOLD_LEVEL = 0

TIINGO_WS_IEX_URL = "wss://api.tiingo.com/iex"


class TiingoStreamBridge:
    """Bridges Tiingo IEX WebSocket to Redis per-ticker channels.

    Thread-safe: all mutations go through asyncio.  One instance per app.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or settings.tiingo_api_key
        self._subscribed: set[str] = set()
        self._ws: object | None = None  # websockets.WebSocketClientProtocol
        self._ws_task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        self._buffer: list[dict] = []
        self._running = False

        if not self._api_key:
            logger.warning("TIINGO_API_KEY not set — TiingoStreamBridge disabled")

    @property
    def active_tickers(self) -> set[str]:
        return self._subscribed.copy()

    async def subscribe(self, tickers: list[str]) -> None:
        """Add tickers to the Tiingo WS subscription.

        Called by the WS endpoint when clients subscribe.
        Starts the WS connection if not already running.
        """
        if not self._api_key:
            return

        new = {t.upper() for t in tickers} - self._subscribed
        if not new:
            return

        self._subscribed |= new
        logger.info("tiingo_bridge_subscribe new=%s total=%d", new, len(self._subscribed))

        # Start WS loop if not running
        if not self._running:
            self._running = True
            self._ws_task = asyncio.create_task(self._ws_loop())
            self._flush_task = asyncio.create_task(self._flush_loop())
        elif self._ws is not None:
            # WS already connected — send subscribe for new tickers
            await self._send_subscribe(list(new))

    async def unsubscribe(self, tickers: list[str]) -> None:
        """Remove tickers from the Tiingo WS subscription."""
        removed = {t.upper() for t in tickers} & self._subscribed
        if not removed:
            return

        self._subscribed -= removed
        logger.info("tiingo_bridge_unsubscribe removed=%s remaining=%d", removed, len(self._subscribed))

        # If no more tickers, stop everything
        if not self._subscribed:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Close Tiingo WS and stop background tasks."""
        self._running = False

        if self._ws is not None:
            try:
                await self._ws.close()  # type: ignore[union-attr]
            except Exception:
                pass
            self._ws = None

        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None

        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        # Final flush
        await self._drain_buffer()
        self._subscribed.clear()
        logger.info("tiingo_bridge_shutdown")

    # ── Flush loop ───────────────────────────────────────────

    async def _flush_loop(self) -> None:
        """Drain buffer every BUFFER_WINDOW_S seconds."""
        try:
            while self._running:
                await asyncio.sleep(BUFFER_WINDOW_S)
                await self._drain_buffer()
        except asyncio.CancelledError:
            await self._drain_buffer()

    async def _drain_buffer(self) -> None:
        """Publish accumulated ticks to Redis in a single pipeline."""
        if not self._buffer:
            return

        batch = self._buffer
        self._buffer = []

        try:
            await publish_price_ticks_batch(batch)
        except Exception:
            logger.exception("tiingo_bridge_publish_error count=%d", len(batch))

    # ── WebSocket loop ───────────────────────────────────────

    async def _ws_loop(self) -> None:
        """Background loop: connect to Tiingo WS, read messages, auto-reconnect."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed — TiingoStreamBridge disabled")
            self._running = False
            return

        reconnect_delay = 1

        while self._running and self._subscribed:
            try:
                async with websockets.connect(
                    TIINGO_WS_IEX_URL,
                    # Handshake budget — Tiingo's edge can be sluggish from
                    # cold POPs. 30s is well above the 10s default and
                    # eliminates false-positive `timed out during opening
                    # handshake` reconnect storms.
                    open_timeout=30,
                    # Application-level keepalive — Tiingo doesn't send
                    # heartbeats during quiet windows, and corporate proxies
                    # / NAT tables drop idle WS after ~60s. Pinging every
                    # 20s keeps the path warm.
                    ping_interval=20,
                    ping_timeout=20,
                    # Disable size limit — IEX firehose burst messages can
                    # exceed the 1 MiB default during opening auctions.
                    max_size=4 * 1024 * 1024,
                ) as ws:
                    self._ws = ws
                    reconnect_delay = 1
                    logger.info("tiingo_bridge_connected")

                    # Subscribe to all current tickers
                    await self._send_subscribe(list(self._subscribed))

                    # Read loop
                    async for raw_msg in ws:
                        if not self._running:
                            break
                        try:
                            msg = orjson.loads(
                                raw_msg if isinstance(raw_msg, bytes) else raw_msg.encode(),
                            )
                            self._handle_message(msg)
                        except (orjson.JSONDecodeError, TypeError):
                            continue

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._ws = None
                if not self._running:
                    break
                logger.warning(
                    "tiingo_bridge_disconnected error=%s reconnect=%ds",
                    e, reconnect_delay,
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)

        self._ws = None

    async def subscribe_approved_universe(self) -> int:
        """Pre-subscribe to every approved instrument across all orgs.

        Used at app startup so the IEX firehose is hot before the first
        frontend client connects. Free-tier subscription caps are gone, so
        we can fan out the entire approved universe in one shot.

        Returns the number of new tickers subscribed.
        """
        if not self._api_key:
            return 0

        # Imported here to avoid a circular import on bridge module load.
        from sqlalchemy import select

        from app.core.db.engine import async_session_factory
        from app.domains.wealth.models.instrument import Instrument
        from app.domains.wealth.models.instrument_org import InstrumentOrg

        async with async_session_factory() as db:
            db.expire_on_commit = False  # type: ignore[attr-defined]
            stmt = (
                select(Instrument.ticker)
                .join(InstrumentOrg, InstrumentOrg.instrument_id == Instrument.instrument_id)
                .where(InstrumentOrg.approval_status == "approved")
                .where(Instrument.ticker.isnot(None))
                .where(Instrument.ticker != "")
            )
            result = await db.execute(stmt)
            tickers = sorted({(t or "").strip().upper() for (t,) in result.all() if t})

        if not tickers:
            logger.info("tiingo_bridge_universe_empty")
            return 0

        before = len(self._subscribed)
        await self.subscribe(tickers)
        added = len(self._subscribed) - before
        logger.info(
            "tiingo_bridge_universe_subscribed total=%d added=%d",
            len(self._subscribed), added,
        )
        return added

    async def _send_subscribe(self, tickers: list[str]) -> None:
        """Send subscription message to Tiingo WS."""
        if self._ws is None:
            return
        msg = {
            "eventName": "subscribe",
            "authorization": self._api_key,
            "eventData": {"thresholdLevel": WS_THRESHOLD_LEVEL, "tickers": tickers},
        }
        try:
            await self._ws.send(orjson.dumps(msg).decode())  # type: ignore[union-attr]
            logger.info("tiingo_bridge_subscribed tickers=%s", tickers)
        except Exception:
            logger.exception("tiingo_bridge_subscribe_send_error")

    def _handle_message(self, msg: dict) -> None:
        """Parse Tiingo IEX message and buffer as a Redis-ready tick.

        Only trade messages (messageType "A", updateType "T") are processed.
        Heartbeats ("H") and info ("I") are silently ignored.
        """
        msg_type = msg.get("messageType")

        if msg_type != "A":
            return

        data = msg.get("data", [])
        if not data or len(data) < 6:
            return

        update_type = data[0]
        if update_type != "T":
            return

        ticker = str(data[3]).upper()
        price = float(data[5])
        size = int(data[4])
        timestamp = str(data[1])

        # Build a tick dict matching the PriceTick schema
        tick = {
            "type": "price",
            "data": {
                "ticker": ticker,
                "price": price,
                "change": 0,  # Delta from previous close — computed by frontend
                "change_pct": 0,
                "volume": size,
                "aum_usd": None,
                "timestamp": timestamp,
                "source": "tiingo",
            },
            "ticker": ticker,  # Top-level for channel routing
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._buffer.append(tick)

        # Backpressure: if firehose floods us between flush ticks, drain
        # immediately rather than letting the buffer grow unbounded.
        if len(self._buffer) >= BUFFER_MAX_SIZE:
            asyncio.create_task(self._drain_buffer())

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tiingo_tick ticker=%s price=%.4f size=%d buffer=%d",
                ticker, price, size, len(self._buffer),
            )

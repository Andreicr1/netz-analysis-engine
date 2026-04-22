"""Tiingo WebSocket → Redis bridge.

Connects to Tiingo's IEX WebSocket and republishes trade ticks to
per-ticker Redis channels so that ``ConnectionManager`` can forward
them to frontend WebSocket clients.

Stability Guardrails (Phase 2 retrofit, §4.1 B1.1–B1.4)
------------------------------------------------------
The bridge now inherits from ``IdleBridgePolicy``. Demand and
liveness are decoupled — when no client is subscribed the bridge
transitions to ``IDLE`` (transport closed but task alive) and resumes
when demand returns. The only place that may call ``shutdown()`` is
the application lifespan in ``main.py``, with ``_from_lifespan=True``.

The buffer drain is serialised through a ``SingleFlightLock`` so the
overflow path (``len(buffer) >= BUFFER_MAX_SIZE``) cannot race with
the periodic flush loop and corrupt ``self._buffer`` via overlapping
``self._buffer = []`` swaps.

For mutual funds: Tiingo WS only streams equities/ETFs (IEX exchange).
MF NAV updates daily via the ``instrument_ingestion`` worker and
``nav_timeseries`` table.  The bridge gracefully ignores tickers
that don't produce WS trades.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

import orjson

from app.core.config.settings import settings
from app.core.runtime.idle_bridge import IdleBridgeConfig, IdleBridgePolicy
from app.core.runtime.single_flight import SingleFlightLock
from app.core.ws._tick_persist import persist_ticks_batch
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

# How long to keep the WS connection open after the last client
# unsubscribes before tearing the transport down. Tuned so a user
# tab-switching back within a minute does not pay the reconnect
# handshake cost.
_IDLE_DISCONNECT_DELAY_S = 60.0

_DRAIN_KEY = "drain"


class TiingoStreamBridge(IdleBridgePolicy):
    """Bridges Tiingo IEX WebSocket to Redis per-ticker channels.

    State machine inherited from :class:`IdleBridgePolicy`:

        STOPPED → STARTING → RUNNING ⇄ IDLE → STOPPING → STOPPED

    Subclass hooks:
        - ``_on_start``: open the WS, spawn read + flush loops.
        - ``_on_resume``: re-open the transport without recreating
          the policy. Default delegates to ``_on_start``.
        - ``_on_demand_added`` / ``_on_demand_removed``: forward
          subscribe/unsubscribe to the live WS.
        - ``_on_idle_disconnect``: close the WS but keep the bridge
          alive, waiting for demand to return.
        - ``_on_shutdown``: terminal cleanup from the lifespan only.
    """

    def __init__(self, api_key: str | None = None, db_pool: Any | None = None) -> None:
        super().__init__(
            cfg=IdleBridgeConfig(
                name="tiingo_bridge",
                idle_disconnect_delay_s=_IDLE_DISCONNECT_DELAY_S,
            ),
        )
        self._api_key = api_key or settings.tiingo_api_key
        self._db_pool = db_pool
        # ``websockets.WebSocketClientProtocol`` — typed as ``Any`` to
        # avoid coupling the bridge to the optional ``websockets``
        # dependency at type-check time.
        self._ws: Any | None = None
        self._ws_task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._buffer: list[dict[str, Any]] = []
        # Single-flight lock for the drain coroutine. The overflow
        # path and the periodic flush loop both call ``_drain_buffer``;
        # the lock guarantees only one drain executes at a time and
        # extra callers join the in-flight one rather than racing on
        # ``self._buffer = []``.
        self._drain_lock: SingleFlightLock[str, None] = SingleFlightLock()

        if not self._api_key:
            logger.warning("TIINGO_API_KEY not set — TiingoStreamBridge disabled")

    @property
    def active_tickers(self) -> set[str]:
        """Snapshot of currently subscribed tickers (the demand set)."""
        return set(self.demand)

    # ── Public façade — preserves the legacy call sites ───────

    async def subscribe(self, tickers: list[str]) -> None:
        """Add tickers to the Tiingo WS subscription.

        Thin wrapper around ``request_demand`` for backwards
        compatibility with the WS endpoint. Starts the bridge on
        first call (or resumes it from IDLE).
        """
        if not self._api_key:
            return
        normalized = {t.upper() for t in tickers if t}
        if not normalized:
            return
        await self.request_demand(normalized)

    async def unsubscribe(self, tickers: list[str]) -> None:
        """Remove tickers from the Tiingo WS subscription.

        Wrapper around ``release_demand``. When the demand set
        empties the policy transitions to IDLE and starts the
        idle-disconnect timer; it does **not** call shutdown — that
        is reserved for the application lifespan.
        """
        normalized = {t.upper() for t in tickers if t}
        if not normalized:
            return
        await self.release_demand(normalized)

    # ── IdleBridgePolicy hooks ────────────────────────────────

    async def _on_start(self) -> None:
        """Spawn the WS read loop and the periodic flush loop.

        Called both on cold start (``STOPPED → RUNNING``) and on
        resume from IDLE — the legacy bridge had a single ``_running``
        flag and the same code path served both, so we don't override
        ``_on_resume`` here either.
        """
        if self._ws_task is None or self._ws_task.done():
            self._ws_task = asyncio.create_task(
                self._ws_loop(),
                name="tiingo_bridge_ws_loop",
            )
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(
                self._flush_loop(),
                name="tiingo_bridge_flush_loop",
            )

    async def _on_demand_added(self, items: set[str]) -> None:
        """Forward new subscriptions to the live WS.

        If the WS is still connecting (``self._ws is None``), the
        ``_ws_loop`` will pick up the demand set on its initial
        ``_send_subscribe`` call so nothing is lost.
        """
        if self._ws is not None:
            await self._send_subscribe(sorted(items))
        logger.info(
            "tiingo_bridge_subscribe added=%s total=%d",
            sorted(items),
            len(self.demand),
        )

    async def _on_demand_removed(self, items: set[str]) -> None:
        """Log the unsubscribe event.

        Tiingo's IEX WS does not expose a per-ticker unsubscribe
        primitive — to remove tickers we would have to drop the WS
        entirely and re-subscribe to the remaining set. We accept
        the wasted bandwidth (the per-ticker Redis listener filter
        downstream is what protects each client) and only log here.
        """
        logger.info(
            "tiingo_bridge_unsubscribe removed=%s remaining=%d",
            sorted(items),
            len(self.demand),
        )

    async def _on_idle_disconnect(self) -> None:
        """Close the underlying WS but keep the bridge instance alive.

        Triggered ``_IDLE_DISCONNECT_DELAY_S`` seconds after the last
        client unsubscribes. The next ``request_demand`` call will
        re-spawn the loops via ``_on_start``.
        """
        logger.info("tiingo_bridge_idle_disconnect")
        await self._teardown_transport(drain_buffer=True)

    async def _on_shutdown(self) -> None:
        """Terminal teardown — only the lifespan can reach this path."""
        await self._teardown_transport(drain_buffer=True)
        logger.info("tiingo_bridge_shutdown")

    async def _teardown_transport(self, *, drain_buffer: bool) -> None:
        """Close the WS, cancel the read/flush tasks, optionally
        drain the buffer one last time.

        Used by both ``_on_idle_disconnect`` and ``_on_shutdown`` so
        the lifecycle policy can keep the bridge object alive while
        still releasing the underlying transport.
        """
        if self._ws is not None:
            try:
                await self._ws.close()
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

        if drain_buffer:
            await self._drain_buffer()

    # ── Flush loop ───────────────────────────────────────────

    async def _flush_loop(self) -> None:
        """Drain buffer every BUFFER_WINDOW_S seconds.

        Continues until the task is cancelled. Final drain is
        guaranteed by ``_teardown_transport`` so cancellation here
        does not need its own flush.
        """
        try:
            while True:
                await asyncio.sleep(BUFFER_WINDOW_S)
                await self._drain_buffer()
        except asyncio.CancelledError:
            return

    async def _drain_buffer(self) -> None:
        """Publish accumulated ticks to Redis through a single-flight lock.

        Multiple call sites (the periodic flush loop and the overflow
        guard in ``_handle_message``) can race here on a busy bridge.
        ``SingleFlightLock`` ensures only one drain runs at a time —
        any concurrent caller observes the same coroutine completion
        and exits without touching the buffer twice.
        """
        await self._drain_lock.run(_DRAIN_KEY, self._drain_buffer_inner)

    async def _drain_buffer_inner(self) -> None:
        if not self._buffer:
            return

        # The swap is now race-free because the surrounding
        # SingleFlightLock guarantees this coroutine is the only one
        # touching ``self._buffer`` at this instant.
        batch = self._buffer
        self._buffer = []

        try:
            await publish_price_ticks_batch(batch)
        except Exception:
            logger.exception("tiingo_bridge_publish_error count=%d", len(batch))

        try:
            await persist_ticks_batch(self._db_pool, batch)
        except Exception:
            logger.warning(
                "tiingo_bridge_persist_error count=%d",
                len(batch),
                exc_info=True,
            )

    # ── WebSocket loop ───────────────────────────────────────

    async def _ws_loop(self) -> None:
        """Background loop: connect to Tiingo WS, read messages, auto-reconnect."""
        try:
            import websockets
        except ImportError:
            logger.error("websockets package not installed — TiingoStreamBridge disabled")
            return

        reconnect_delay = 1

        # Loop while we have demand. The IdleBridgePolicy state is the
        # source of truth for "should we be connected" — when demand
        # drops to zero the policy will fire ``_on_idle_disconnect``,
        # which cancels this task; until then we keep reconnecting.
        while self._demand:
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
                    await self._send_subscribe(sorted(self._demand))

                    # Read loop
                    async for raw_msg in ws:
                        if not self._demand:
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
                if not self._demand:
                    break
                logger.warning(
                    "tiingo_bridge_disconnected error=%s reconnect=%ds",
                    e, reconnect_delay,
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)

        self._ws = None

    async def _send_subscribe(self, tickers: list[str]) -> None:
        """Send subscription message to Tiingo WS."""
        if self._ws is None or not tickers:
            return
        msg = {
            "eventName": "subscribe",
            "authorization": self._api_key,
            "eventData": {"thresholdLevel": WS_THRESHOLD_LEVEL, "tickers": tickers},
        }
        try:
            await self._ws.send(orjson.dumps(msg).decode())
            logger.info("tiingo_bridge_subscribed tickers=%s", tickers)
        except Exception:
            logger.exception("tiingo_bridge_subscribe_send_error")

    def _handle_message(self, msg: dict[str, Any]) -> None:
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
        # immediately rather than letting the buffer grow unbounded. The
        # SingleFlightLock makes this safe to fire without coordination —
        # if a drain is already in flight the spawned task will join it
        # and exit without double-processing the buffer.
        if len(self._buffer) >= BUFFER_MAX_SIZE:
            asyncio.create_task(
                self._drain_buffer(),
                name="tiingo_bridge_overflow_drain",
            )

        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "tiingo_tick ticker=%s price=%.4f size=%d buffer=%d",
                ticker, price, size, len(self._buffer),
            )

"""
Market Data Provider -- Tiingo (REST + WebSocket)

Single provider for all asset classes and delivery modes:
  - EOD daily prices (equities, ETFs, mutual funds)  -> REST
  - Real-time IEX quotes (equities, ETFs)            -> WebSocket
  - Real-time crypto quotes                           -> WebSocket

Tiingo WebSocket docs: https://www.tiingo.com/documentation/websockets/iex
Tiingo EOD docs:       https://www.tiingo.com/documentation/end-of-day

Auth: TIINGO_API_KEY env var.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date
from typing import Any, Callable, Coroutine, List, Optional, Protocol

import httpx
import websockets
from pydantic import BaseModel

logger = logging.getLogger(__name__)

TIINGO_BASE_URL = "https://api.tiingo.com"
TIINGO_WS_IEX_URL = "wss://api.tiingo.com/iex"
TIINGO_WS_CRYPTO_URL = "wss://api.tiingo.com/crypto"

# Institutional plan: 10,000 req/h, 100k req/day, unlimited symbols, 15y+ history.
# Concurrency cap chosen to stay well below TCP/connection-pool limits while
# saturating Tiingo's REST capacity. Free-tier throttling (sleeps, semaphores
# of 1-2, hourly token buckets) is intentionally absent.
TIINGO_MAX_CONCURRENT_REQUESTS = 50
TIINGO_BATCH_SIZE = 100


# -- Data Models ---------------------------------------------------------------


class MarketDataPoint(BaseModel):
    """Standardized EOD OHLCV point."""
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class LiveQuote(BaseModel):
    """Real-time quote from WebSocket stream."""
    ticker: str
    price: float
    size: int
    timestamp: str
    source: str  # "iex" | "crypto"


# -- Provider Protocol ---------------------------------------------------------


class InstrumentDataProvider(Protocol):
    """Unified interface for market data providers."""

    async def get_historical_data(
        self, ticker: str, start_date: date, end_date: date,
    ) -> List[MarketDataPoint]: ...

    async def get_latest_price(self, ticker: str) -> Optional[float]: ...


# -- Tiingo Provider -----------------------------------------------------------

# Callback type: async function receiving a LiveQuote
LiveQuoteCallback = Callable[[LiveQuote], Coroutine[Any, Any, None]]


class TiingoProvider:
    """Tiingo REST + WebSocket client.

    REST:      EOD daily bars for any ticker (equity, ETF, mutual fund).
    WebSocket: Real-time IEX trades for equities/ETFs.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("TIINGO_API_KEY", "")
        # Fallback: try pydantic-settings (reads .env properly)
        if not self._api_key:
            try:
                from app.core.config.settings import settings
                self._api_key = settings.tiingo_api_key
            except Exception:
                pass
        if not self._api_key:
            logger.warning("TIINGO_API_KEY not set -- all requests will fail")
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Token {self._api_key}",
        }
        # WebSocket state
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._ws_task: asyncio.Task | None = None
        self._subscribed_tickers: set[str] = set()
        self._quote_callback: LiveQuoteCallback | None = None
        # Lazy-init: created in the running event loop, never at module import.
        self._rest_semaphore: asyncio.Semaphore | None = None

    def _get_rest_semaphore(self) -> asyncio.Semaphore:
        """Lazy semaphore — must be created inside the running event loop."""
        if self._rest_semaphore is None:
            self._rest_semaphore = asyncio.Semaphore(TIINGO_MAX_CONCURRENT_REQUESTS)
        return self._rest_semaphore

    # -- REST: Historical EOD --------------------------------------------------

    async def get_historical_data(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> List[MarketDataPoint]:
        """Fetch daily OHLCV bars for any ticker."""
        url = f"{TIINGO_BASE_URL}/tiingo/daily/{ticker}/prices"
        params = {
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        }
        sem = self._get_rest_semaphore()
        async with sem, httpx.AsyncClient(timeout=15) as client:
            try:
                resp = await client.get(url, headers=self._headers, params=params)
                if resp.status_code == 404:
                    logger.info("Tiingo: ticker %s not found", ticker)
                    return []
                if resp.status_code == 429:
                    logger.warning("Tiingo: rate limited on %s", ticker)
                    return []
                resp.raise_for_status()
                return _parse_eod(resp.json())
            except httpx.HTTPStatusError as e:
                logger.warning("Tiingo HTTP %s for %s", e.response.status_code, ticker)
                return []
            except httpx.RequestError as e:
                logger.warning("Tiingo request error for %s: %s", ticker, e)
                return []

    # -- REST: Latest Price ----------------------------------------------------

    async def get_latest_price(self, ticker: str) -> Optional[float]:
        """Fetch the most recent closing price."""
        url = f"{TIINGO_BASE_URL}/tiingo/daily/{ticker}/prices"
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(url, headers=self._headers)
                if resp.status_code in (404, 429):
                    return None
                resp.raise_for_status()
                rows = resp.json()
                if rows:
                    return float(rows[-1]["close"])
                return None
            except (httpx.HTTPError, KeyError, IndexError, ValueError):
                return None

    # -- REST: Concurrent Batch Historical -------------------------------------

    async def fetch_batch_history(
        self,
        tickers: list[str],
        start_date: date,
        end_date: date,
    ) -> dict[str, List[MarketDataPoint]]:
        """Fetch EOD history for many tickers concurrently.

        Tiingo REST has no batch endpoint, so we fan out one request per
        ticker, capped by ``TIINGO_MAX_CONCURRENT_REQUESTS``. With the
        institutional plan (10k req/h, 100k req/day) this saturates the
        wire instead of the rate limit. Errors per ticker are isolated:
        a failed ticker yields ``[]`` and the rest still complete.
        """
        # Per-call semaphore is held inside ``get_historical_data`` itself,
        # so we just gather here — concurrency is naturally bounded.
        async def _one(ticker: str) -> tuple[str, List[MarketDataPoint]]:
            points = await self.get_historical_data(ticker, start_date, end_date)
            return ticker, points

        results = await asyncio.gather(
            *(_one(t) for t in tickers),
            return_exceptions=True,
        )

        out: dict[str, List[MarketDataPoint]] = {}
        for item in results:
            if isinstance(item, BaseException):
                logger.warning("Tiingo batch entry failed: %s", item)
                continue
            ticker, points = item
            out[ticker] = points
        return out

    # -- WebSocket: Real-Time IEX Stream ---------------------------------------

    async def subscribe(
        self,
        tickers: list[str],
        callback: LiveQuoteCallback,
    ) -> None:
        """Subscribe to real-time IEX trade updates.

        Starts a background task that maintains the WebSocket connection,
        auto-reconnects on failure, and invokes `callback(LiveQuote)` for
        every trade event.

        Can be called multiple times to add tickers to an active stream.
        """
        self._quote_callback = callback

        new_tickers = set(t.upper() for t in tickers) - self._subscribed_tickers
        if not new_tickers:
            return

        self._subscribed_tickers |= new_tickers

        # If WS is already running, send subscribe message for new tickers
        if self._ws is not None:
            await self._ws_subscribe(list(new_tickers))
            return

        # First call -- start the background listener
        self._ws_task = asyncio.create_task(self._ws_loop())

    async def unsubscribe(self, tickers: list[str]) -> None:
        """Remove tickers from the live stream."""
        remove = set(t.upper() for t in tickers) & self._subscribed_tickers
        if not remove:
            return
        self._subscribed_tickers -= remove
        # Tiingo doesn't support per-ticker unsubscribe; if all gone, close WS
        if not self._subscribed_tickers:
            await self.disconnect()

    async def disconnect(self) -> None:
        """Close WebSocket connection and stop the background task."""
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._ws_task is not None:
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
            self._ws_task = None
        self._subscribed_tickers.clear()

    async def _ws_loop(self) -> None:
        """Background loop: connect, subscribe, read messages, auto-reconnect."""
        reconnect_delay = 1
        while self._subscribed_tickers:
            try:
                url = f"{TIINGO_WS_IEX_URL}"
                async with websockets.connect(url) as ws:
                    self._ws = ws
                    reconnect_delay = 1  # reset on successful connect
                    logger.info("Tiingo WS connected")

                    # Send subscribe message
                    await self._ws_subscribe(list(self._subscribed_tickers))

                    # Read loop
                    async for raw_msg in ws:
                        try:
                            msg = json.loads(raw_msg)
                            await self._handle_ws_message(msg)
                        except json.JSONDecodeError:
                            continue

            except (websockets.ConnectionClosed, OSError, Exception) as e:
                logger.warning("Tiingo WS disconnected: %s -- reconnecting in %ds", e, reconnect_delay)
                self._ws = None
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)

    async def _ws_subscribe(self, tickers: list[str]) -> None:
        """Send subscription message to Tiingo WebSocket."""
        if self._ws is None:
            return
        sub_msg = {
            "eventName": "subscribe",
            "authorization": self._api_key,
            "eventData": {"thresholdLevel": 5, "tickers": tickers},
        }
        await self._ws.send(json.dumps(sub_msg))
        logger.info("Tiingo WS subscribed: %s", tickers)

    async def _handle_ws_message(self, msg: dict) -> None:
        """Parse Tiingo IEX WebSocket message and invoke callback.

        Message format (trade update, messageType "T"):
            {"messageType": "A",
             "data": ["T", "2026-04-05T...", timestamp_ns, "AAPL", size, price]}

        Heartbeat messages (messageType "H") are silently ignored.
        """
        msg_type = msg.get("messageType")

        # Heartbeat
        if msg_type == "H":
            return

        # Trade/quote update
        if msg_type == "A":
            data = msg.get("data", [])
            if not data or len(data) < 6:
                return
            update_type = data[0]  # "T" = trade, "Q" = quote
            if update_type != "T":
                return

            ticker = str(data[3])
            price = float(data[5])
            size = int(data[4])
            timestamp = str(data[1])

            quote = LiveQuote(
                ticker=ticker,
                price=price,
                size=size,
                timestamp=timestamp,
                source="iex",
            )
            if self._quote_callback:
                try:
                    await self._quote_callback(quote)
                except Exception:
                    logger.exception("Error in quote callback for %s", ticker)


# -- EOD Parser ----------------------------------------------------------------


def _parse_eod(rows: list[dict]) -> List[MarketDataPoint]:
    """Convert Tiingo JSON array -> list[MarketDataPoint].

    Uses adjClose/adjOpen/... when present (split/dividend adjusted).
    Falls back to raw OHLCV for mutual funds (no adjustments).
    """
    points: list[MarketDataPoint] = []
    for r in rows:
        try:
            raw_date = str(r["date"])[:10]
            points.append(
                MarketDataPoint(
                    date=date.fromisoformat(raw_date),
                    open=float(r.get("adjOpen") or r["open"]),
                    high=float(r.get("adjHigh") or r["high"]),
                    low=float(r.get("adjLow") or r["low"]),
                    close=float(r.get("adjClose") or r["close"]),
                    volume=int(r.get("adjVolume") or r.get("volume") or 0),
                ),
            )
        except (KeyError, ValueError, TypeError) as e:
            logger.debug("Tiingo: skipping malformed row: %s -- %s", r, e)
    return points


# -- Factory -------------------------------------------------------------------


def get_market_data_provider() -> TiingoProvider:
    """Factory -- single provider for dev and prod."""
    return TiingoProvider()


# -- Integration Test ----------------------------------------------------------

if __name__ == "__main__":
    from datetime import timedelta

    async def _test() -> None:
        provider = TiingoProvider()
        end = date.today()
        start = end - timedelta(days=30)

        # -- Test 1: REST EOD --
        tickers = {"AAPL": "equity", "SPY": "etf", "OAKMX": "mutual_fund", "VFINX": "mutual_fund"}

        print(f"\n{'=' * 60}")
        print("  Tiingo Provider -- Integration Test")
        print(f"  Range: {start} -> {end}")
        print(f"{'=' * 60}")

        for ticker, asset_type in tickers.items():
            points = await provider.get_historical_data(ticker, start, end)
            latest = await provider.get_latest_price(ticker)
            status = "OK" if points else "EMPTY"
            print(f"\n  [{status}] {ticker} ({asset_type})")
            print(f"       Bars: {len(points)}")
            if points:
                first, last = points[0], points[-1]
                print(f"       First: {first.date} -> ${first.close:.2f}")
                print(f"       Last:  {last.date} -> ${last.close:.2f}")
            print(f"       Latest: ${latest:.2f}" if latest else "       Latest: N/A")

        # -- Test 2: WebSocket (5 seconds) --
        print(f"\n{'=' * 60}")
        print("  WebSocket Test (5 seconds of AAPL + SPY)")
        print(f"{'=' * 60}\n")

        received: list[LiveQuote] = []

        async def on_quote(q: LiveQuote) -> None:
            received.append(q)
            print(f"  >> {q.ticker}  ${q.price:.2f}  x{q.size}  {q.timestamp[:19]}")

        await provider.subscribe(["AAPL", "SPY"], on_quote)
        await asyncio.sleep(5)
        await provider.disconnect()

        print(f"\n  Received {len(received)} trade updates in 5s")
        if not received:
            print("  (Market may be closed -- trades only stream during market hours)")
        print(f"\n{'=' * 60}\n")

    asyncio.run(_test())

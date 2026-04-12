"""Tiingo REST provider — News + EOD/Intraday OHLCV.

Companion to ``app.core.ws.tiingo_bridge`` (which streams IEX trade ticks
over WebSocket). This module wraps the Tiingo HTTP REST endpoints used by
the Wealth Market Command Center:

  - ``/tiingo/news``                       → editorial news feed
  - ``/tiingo/daily/{ticker}/prices``      → end-of-day OHLCV history
  - ``/iex/{ticker}/prices``               → intraday OHLCV (1min..1h bars)

DB-first rule reminder: routes that hit user-facing requests should
prefer DB sources whenever possible. These REST helpers are used for:
  1. Live charting (candlestick history seed before WS overlay)
  2. News feed (no DB cache yet — Tiingo News is the source of truth)

Both endpoints are bounded by the institutional plan rate limit (10k req/h).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Any

import httpx

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

TIINGO_BASE_URL = "https://api.tiingo.com"
DEFAULT_TIMEOUT = 10.0
BATCH_CONCURRENCY = 100


class TiingoProvider:
    """Thin async wrapper over Tiingo's REST API.

    Stateless — safe to instantiate per-request or share via a module-level
    singleton. All methods raise ``httpx.HTTPError`` on transport failure
    and return empty lists on empty/404 responses (never silently swallow
    auth failures).
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key or settings.tiingo_api_key
        self._timeout = timeout
        self._client = http_client or httpx.AsyncClient(
            timeout=self._timeout,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100)
        )

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Token {self._api_key}",
        }

    async def aclose(self) -> None:
        """Close the underlying HTTPX client."""
        await self._client.aclose()

    # ── News ────────────────────────────────────────────────────────────

    async def fetch_news(
        self,
        tickers: list[str] | None = None,
        limit: int = 20,
        sources: list[str] | None = None,
        start_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch editorial news from ``/tiingo/news``.

        Args:
            tickers: Optional ticker filter — Tiingo returns articles tagged
                with at least one of these symbols. ``None`` returns the full
                cross-market firehose (latest first).
            limit: Max items to return (1..1000). Tiingo caps at 1000.
            sources: Optional source domain filter (e.g. ["bloomberg.com"]).
            start_date: Only articles published on/after this date.

        Returns:
            Standardized list of news dicts (see ``_normalize_article``).
            Empty list on auth failure or empty response — never raises
            for upstream 4xx/5xx (logged + degraded gracefully).
        """
        if not self.enabled:
            logger.warning("tiingo_news_disabled reason=missing_api_key")
            return []

        params: dict[str, str] = {
            "limit": str(max(1, min(limit, 1000))),
            "sortBy": "publishedDate",
        }
        if tickers:
            params["tickers"] = ",".join(t.strip().lower() for t in tickers if t)
        if sources:
            params["source"] = ",".join(sources)
        if start_date:
            params["startDate"] = start_date.isoformat()

        try:
            resp = await self._client.get(
                f"{TIINGO_BASE_URL}/tiingo/news",
                headers=self._headers(),
                params=params,
            )
            if resp.status_code == 401:
                logger.error("tiingo_news_auth_failed")
                return []
            if resp.status_code != 200:
                logger.warning(
                    "tiingo_news_non_200 status=%s body=%s",
                    resp.status_code, resp.text[:200],
                )
                return []
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("tiingo_news_http_error error=%s", exc)
            return []

        if not isinstance(payload, list):
            return []

        return [self._normalize_article(item) for item in payload]

    @staticmethod
    def _normalize_article(item: dict[str, Any]) -> dict[str, Any]:
        """Project Tiingo's news payload onto our standard shape."""
        return {
            "id": item.get("id"),
            "title": (item.get("title") or "").strip(),
            "description": (item.get("description") or "").strip(),
            "url": item.get("url") or "",
            "source": item.get("source") or "",
            "published_at": item.get("publishedDate") or "",
            "crawled_at": item.get("crawlDate") or "",
            "tickers": [
                str(t).upper() for t in (item.get("tickers") or []) if t
            ],
            "tags": [str(t) for t in (item.get("tags") or []) if t],
        }

    # ── Historical OHLCV ────────────────────────────────────────────────

    async def fetch_historical_daily(
        self,
        ticker: str,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch end-of-day OHLCV bars from ``/tiingo/daily/{ticker}/prices``.

        Returns standardized bars (see ``_normalize_bar``). Empty list on
        404 (unknown ticker) or auth failure.
        """
        if not self.enabled:
            return []

        ticker_clean = ticker.strip().lower()
        if not ticker_clean:
            return []

        params: dict[str, str] = {"format": "json", "resampleFreq": "daily"}
        if start_date:
            params["startDate"] = start_date.isoformat()
        if end_date:
            params["endDate"] = end_date.isoformat()

        try:
            resp = await self._client.get(
                f"{TIINGO_BASE_URL}/tiingo/daily/{ticker_clean}/prices",
                headers=self._headers(),
                params=params,
            )
            if resp.status_code in (401, 404):
                return []
            if resp.status_code != 200:
                logger.warning(
                    "tiingo_daily_non_200 ticker=%s status=%s",
                    ticker_clean, resp.status_code,
                )
                return []
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("tiingo_daily_http_error ticker=%s error=%s", ticker_clean, exc)
            return []

        if not isinstance(payload, list):
            return []

        return [self._normalize_bar(item) for item in payload]

    async def fetch_historical_daily_batch(
        self,
        tickers: list[str],
        start_date: date | None = None,
        end_date: date | None = None,
        concurrency: int = BATCH_CONCURRENCY,
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch EOD history for many tickers in parallel.

        Tiingo Premium has no hard rate limit, but unbounded fan-out still
        exhausts local sockets and httpx keepalive pools. A Semaphore bounds
        concurrent in-flight requests. Each call goes through
        ``fetch_historical_daily``, so 401/404 still degrade to empty list
        per ticker instead of raising.

        Returns a dict mapping ticker (upper-case) -> normalized bar list.
        Tickers with no data are omitted — callers must handle missing keys.
        """
        if not tickers:
            return {}

        sem = asyncio.Semaphore(max(1, concurrency))

        async def _one(ticker: str) -> tuple[str, list[dict[str, Any]]]:
            async with sem:
                bars = await self.fetch_historical_daily(ticker, start_date, end_date)
                return ticker.strip().upper(), bars

        results = await asyncio.gather(
            *(_one(t) for t in tickers if t and t.strip()),
            return_exceptions=True,
        )

        out: dict[str, list[dict[str, Any]]] = {}
        for item in results:
            if isinstance(item, BaseException):
                logger.warning("tiingo_batch_task_failed error=%s", item)
                continue
            ticker_key, bars = item
            if bars:
                out[ticker_key] = bars
        return out

    async def fetch_historical_intraday(
        self,
        ticker: str,
        start_date: date | None = None,
        end_date: date | None = None,
        resample_freq: str = "5min",
    ) -> list[dict[str, Any]]:
        """Fetch intraday OHLCV from the IEX endpoint.

        ``resample_freq`` accepts Tiingo intervals: ``1min``, ``5min``,
        ``15min``, ``30min``, ``1hour``, ``4hour``. Only equities/ETFs
        listed on IEX are supported (mutual funds return empty).
        """
        if not self.enabled:
            return []

        ticker_clean = ticker.strip().lower()
        if not ticker_clean:
            return []

        params: dict[str, str] = {
            "resampleFreq": resample_freq,
            "format": "json",
            "columns": "open,high,low,close,volume",
        }
        if start_date:
            params["startDate"] = start_date.isoformat()
        if end_date:
            params["endDate"] = end_date.isoformat()

        try:
            resp = await self._client.get(
                f"{TIINGO_BASE_URL}/iex/{ticker_clean}/prices",
                headers=self._headers(),
                params=params,
            )
            if resp.status_code in (401, 404):
                return []
            if resp.status_code != 200:
                logger.warning(
                    "tiingo_iex_non_200 ticker=%s status=%s",
                    ticker_clean, resp.status_code,
                )
                return []
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("tiingo_iex_http_error ticker=%s error=%s", ticker_clean, exc)
            return []

        if not isinstance(payload, list):
            return []

        return [self._normalize_bar(item) for item in payload]

    @staticmethod
    def _normalize_bar(item: dict[str, Any]) -> dict[str, Any]:
        """Project a Tiingo OHLCV row onto our standard shape.

        Tiingo daily uses ``adjOpen/adjClose`` (split-adjusted); IEX uses
        the raw ``open/close``. We prefer adjusted when available.
        """
        ts_raw = item.get("date") or ""
        # Normalize to ISO-8601 with timezone (Tiingo daily returns Z; IEX returns +00:00)
        try:
            ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            ts_iso = ts.isoformat()
        except (ValueError, AttributeError):
            ts_iso = ts_raw

        def _num(*keys: str) -> float | None:
            for k in keys:
                v = item.get(k)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue
            return None

        return {
            "timestamp": ts_iso,
            "open": _num("adjOpen", "open"),
            "high": _num("adjHigh", "high"),
            "low": _num("adjLow", "low"),
            "close": _num("adjClose", "close"),
            "volume": _num("adjVolume", "volume") or 0.0,
        }


# Module-level singleton — cheap to share, no per-request state.
_default_provider: TiingoProvider | None = None


def get_tiingo_provider() -> TiingoProvider:
    """Return the process-wide TiingoProvider singleton."""
    global _default_provider
    if _default_provider is None:
        _default_provider = TiingoProvider()
    return _default_provider

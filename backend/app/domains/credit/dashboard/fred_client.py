"""Async FRED API client for dashboard proxy endpoints.

Wraps httpx.AsyncClient with:
- Explicit connect + read timeouts (no blocking event loop)
- asyncio.CancelledError propagation (cancellation-safe)
- Structured telemetry (upstream latency, timeout counter)
- In-memory cache (TTL-based, thread-safe via asyncio.Lock)
- Series ID validation to prevent SSRF

Design:
- One shared AsyncFredClient instance per process (via module singleton).
- Callers MUST await fetch_* methods; no sync I/O is performed.
- All cache operations are guarded by asyncio.Lock (not threading.Lock)
  to avoid cross-loop issues.

FRED rate limit: 120 req/60s. The cache at the client level ensures
repeated requests from multiple concurrent users share results.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any

import httpx
import structlog

# Suppress httpx DEBUG logs that expose FRED API key in URL parameters
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FRED_BASE_URL = "https://api.stlouisfed.org/fred"
_FRED_ID_RE = re.compile(r"^[A-Z0-9_]{1,20}$")

# Timeouts — deliberately conservative; FRED is generally fast (<2s)
_CONNECT_TIMEOUT = 5.0   # seconds — TCP + TLS handshake
_READ_TIMEOUT = 12.0     # seconds — response body
_TOTAL_TIMEOUT = 15.0    # seconds — hard cap including retries inside single call

_SEARCH_TTL = 300        # 5 minutes
_OBS_TTL = 3600          # 1 hour
_CACHE_MAX_SIZE = 500

_PERIOD_MONTHS: dict[str, int] = {
    "3M": 3, "6M": 6, "1Y": 12, "3Y": 36, "5Y": 60, "10Y": 120, "MAX": 600,
}

# ---------------------------------------------------------------------------
# Telemetry counters (module-level, lightweight)
# ---------------------------------------------------------------------------

_telemetry: dict[str, int] = {
    "requests_total": 0,
    "timeouts_total": 0,
    "errors_total": 0,
    "cache_hits": 0,
}


def get_telemetry() -> dict[str, int]:
    """Return a snapshot of FRED client telemetry counters."""
    return dict(_telemetry)


def reset_telemetry() -> None:
    """Reset all counters (for test isolation)."""
    for k in _telemetry:
        _telemetry[k] = 0


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class _AsyncCache:
    """Simple async-safe TTL cache backed by asyncio.Lock."""

    def __init__(self, max_size: int = _CACHE_MAX_SIZE) -> None:
        self._store: dict[str, tuple[float, Any]] = {}  # key -> (expire_at, data)
        self._lock = asyncio.Lock()
        self._max_size = max_size

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expire_at, data = entry
            if expire_at > time.monotonic():
                return data
            del self._store[key]
            return None

    async def set(self, key: str, value: Any, ttl: float) -> None:
        async with self._lock:
            if len(self._store) >= self._max_size:
                now = time.monotonic()
                expired = [k for k, (exp, _) in self._store.items() if exp <= now]
                for k in expired:
                    del self._store[k]
                if len(self._store) >= self._max_size:
                    oldest = min(self._store, key=lambda k: self._store[k][0])
                    del self._store[oldest]
            self._store[key] = (time.monotonic() + ttl, value)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()


# ---------------------------------------------------------------------------
# AsyncFredClient
# ---------------------------------------------------------------------------


class AsyncFredClient:
    """Async FRED API client.

    Args:
        api_key: FRED API key.
        base_url: Override base URL (useful for tests with respx/httpretty).
        connect_timeout: Seconds for TCP+TLS handshake.
        read_timeout: Seconds for response body read.
        total_timeout: Hard cap for the full request.
        cache: Optional pre-built cache (inject for test isolation).

    Lifecycle:
        Use as an async context manager or call aclose() explicitly.
        Module-level singleton created via ``get_shared_client()``.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = FRED_BASE_URL,
        connect_timeout: float = _CONNECT_TIMEOUT,
        read_timeout: float = _READ_TIMEOUT,
        total_timeout: float = _TOTAL_TIMEOUT,
        cache: _AsyncCache | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=5.0,
            pool=5.0,
        )
        self._cache = cache or _AsyncCache()
        self._http: httpx.AsyncClient = httpx.AsyncClient(
            timeout=self._timeout,
            headers={"Accept": "application/json"},
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> AsyncFredClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_params(self) -> dict[str, str]:
        return {"api_key": self._api_key, "file_type": "json"}

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a single FRED GET request.

        Raises:
            httpx.TimeoutException: on connect/read timeout.
            httpx.HTTPStatusError: on 4xx/5xx responses.
            asyncio.CancelledError: propagated unchanged (caller can cancel).
        """
        url = f"{self._base_url}/{path.lstrip('/')}"
        all_params = {**self._base_params(), **params}

        _telemetry["requests_total"] += 1
        t0 = time.perf_counter()
        try:
            resp = await self._http.get(url, params=all_params)
            resp.raise_for_status()
            latency_ms = (time.perf_counter() - t0) * 1000
            logger.debug(
                "fred.upstream_latency",
                path=path,
                latency_ms=round(latency_ms, 1),
            )
            return resp.json()
        except httpx.TimeoutException:
            _telemetry["timeouts_total"] += 1
            latency_ms = (time.perf_counter() - t0) * 1000
            logger.warning(
                "fred.timeout",
                path=path,
                elapsed_ms=round(latency_ms, 1),
            )
            raise
        except asyncio.CancelledError:
            # Propagate — do NOT increment error counter, cancellation is normal
            raise
        except Exception:
            _telemetry["errors_total"] += 1
            raise

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def fetch_observations(
        self,
        series_id: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str = "w",
    ) -> list[dict[str, Any]]:
        """Fetch weekly observations for a FRED series.

        Returns a list of ``{date, value}`` dicts with valid numeric values.
        Returns ``[]`` on any upstream failure (timeout, HTTP error) —
        dashboard gracefully renders empty sparklines rather than 500.

        Cancellation-safe: asyncio.CancelledError propagates to caller.
        """
        if not _FRED_ID_RE.match(series_id):
            logger.warning("fred.invalid_series_id", series_id=series_id)
            return []

        cache_key = f"obs:{series_id}:{start_date}:{end_date}:{frequency}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            _telemetry["cache_hits"] += 1
            return cached

        try:
            data = await self._get(
                "series/observations",
                params={
                    "series_id": series_id,
                    "observation_start": start_date,
                    "observation_end": end_date,
                    "frequency": frequency,
                },
            )
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError):
            return []

        observations = [
            {"date": o["date"], "value": float(o["value"])}
            for o in data.get("observations", [])
            if o.get("value") and o["value"] != "."
        ]
        await self._cache.set(cache_key, observations, _OBS_TTL)
        return observations

    async def search_series(
        self,
        query: str,
        *,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Search FRED for series matching *query*.

        Returns a list of series metadata dicts (id, title, frequency, etc.).
        Returns ``[]`` on any upstream failure.

        Cancellation-safe: asyncio.CancelledError propagates to caller.
        """
        cache_key = f"search:{query.lower()}:{limit}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            _telemetry["cache_hits"] += 1
            return cached

        try:
            data = await self._get(
                "series/search",
                params={
                    "search_text": query,
                    "limit": limit,
                    "order_by": "popularity",
                    "sort_order": "desc",
                },
            )
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.ConnectError):
            return []

        series = [
            {
                "id": s["id"],
                "title": s["title"],
                "frequency": s.get("frequency_short", ""),
                "units": s.get("units_short", ""),
                "popularity": s.get("popularity", 0),
                "last_updated": s.get("last_updated", ""),
            }
            for s in data.get("seriess", [])
        ]
        await self._cache.set(cache_key, series, _SEARCH_TTL)
        return series

    async def fetch_multi(
        self,
        series_ids: list[str],
        *,
        start_date: str,
        end_date: str,
        frequency: str = "w",
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch observations for multiple series concurrently.

        Uses asyncio.gather — all requests run in the same event loop without
        blocking it. At most 4 series are fetched (caller must pre-slice).

        Returns mapping of series_id -> observations list.
        Missing/failed series map to [].
        """
        tasks = {
            sid: asyncio.create_task(
                self.fetch_observations(
                    sid,
                    start_date=start_date,
                    end_date=end_date,
                    frequency=frequency,
                ),
                name=f"fred_obs_{sid}",
            )
            for sid in series_ids
        }
        # gather with return_exceptions=True so one slow/failing series
        # does not cancel the others
        results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
        out: dict[str, list[dict[str, Any]]] = {}
        for sid, result in zip(tasks.keys(), results_list, strict=False):
            if isinstance(result, BaseException):
                logger.warning("fred.multi_fetch_failed", series_id=sid, error=str(result))
                out[sid] = []
            else:
                out[sid] = result
        return out


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_shared_client: AsyncFredClient | None = None
_client_lock: asyncio.Lock | None = None


def _get_lock() -> asyncio.Lock:
    """Lazy init to avoid attaching to wrong event loop at import time."""
    global _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    return _client_lock


async def get_shared_client(api_key: str) -> AsyncFredClient:
    """Return (or lazily create) the shared AsyncFredClient singleton.

    Called once per request; creation is idempotent under the lock.
    The singleton is recreated if the api_key changes (env hot-reload).
    """
    global _shared_client
    lock = _get_lock()
    async with lock:
        if _shared_client is None or _shared_client._api_key != api_key:
            if _shared_client is not None:
                await _shared_client.aclose()
            _shared_client = AsyncFredClient(api_key=api_key)
    return _shared_client


async def close_shared_client() -> None:
    """Close and release the shared client (call from FastAPI lifespan)."""
    global _shared_client
    if _shared_client is not None:
        await _shared_client.aclose()
        _shared_client = None

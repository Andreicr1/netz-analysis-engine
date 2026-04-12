"""Tiingo instrument data provider — synchronous, worker-facing.

Implements ``InstrumentDataProvider`` for Netz background workers that
ingest end-of-day NAV history into ``nav_timeseries`` and ``benchmark_nav``.

Design notes
------------
- **Synchronous on purpose.** The NAV ingestion worker dispatches provider
  calls through a ``ThreadPoolExecutor``, so the public surface must be
  ordinary blocking methods. Mixing an async client here would force
  ``asyncio.run()`` inside worker threads — a known reentrancy trap.
- **Bounded fan-out.** Tiingo Premium has no hard REST rate limit, but the
  local httpx connection pool and open file descriptors still cap throughput.
  A per-call ``ThreadPoolExecutor(max_workers=BATCH_CONCURRENCY)`` bounds
  concurrent HTTP requests to a single value tuned for a ~5k ticker universe.
- **Metadata parity with yfinance is intentionally partial.** Production
  workers only call ``fetch_batch_history``; ``fetch_instrument`` / ``fetch_batch``
  exist for Protocol conformance and return a minimal ``RawInstrumentData``
  from Tiingo's ``/tiingo/daily/{ticker}`` meta endpoint. Fund-level attributes
  (AUM, expense ratio, category) are authoritative in SEC N-CEN + XBRL and
  ESMA ingestion — this provider does not attempt to duplicate them.
"""

from __future__ import annotations

import concurrent.futures
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx
import pandas as pd

from app.core.config.settings import settings
from app.services.providers.protocol import RawInstrumentData

logger = logging.getLogger(__name__)

TIINGO_BASE_URL = "https://api.tiingo.com"
DEFAULT_TIMEOUT = 30.0
BATCH_CONCURRENCY = 50

# yfinance period literals → calendar-day lookbacks. Preserves the
# ``instrument_ingestion`` worker contract so migrating workers is a
# single-line factory swap instead of rewiring the period vocabulary.
_PERIOD_TO_DAYS: dict[str, int] = {
    "1mo": 30,
    "3mo": 90,
    "6mo": 180,
    "1y": 365,
    "2y": 730,
    "3y": 1095,
    "5y": 1825,
    "10y": 3650,
    "ytd": 366,  # Upper bound; Tiingo honors startDate precisely.
}

# Tiingo's daily history begins 1962-01-02 for the longest-lived tickers.
# Any earlier date is silently clamped server-side.
_MAX_LOOKBACK_START = date(1970, 1, 1)


class TiingoInstrumentProvider:
    """Synchronous InstrumentDataProvider backed by the Tiingo REST API."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        batch_concurrency: int = BATCH_CONCURRENCY,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key or settings.tiingo_api_key
        self._timeout = timeout
        self._batch_concurrency = max(1, batch_concurrency)
        self._client = http_client or httpx.Client(
            timeout=self._timeout,
            limits=httpx.Limits(
                max_keepalive_connections=batch_concurrency,
                max_connections=batch_concurrency * 2,
            ),
        )

    @property
    def enabled(self) -> bool:
        return bool(self._api_key)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> TiingoInstrumentProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Token {self._api_key}",
        }

    # ── InstrumentDataProvider Protocol ────────────────────────────────

    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None:
        """Fetch minimal metadata for a single ticker.

        Returns ``None`` on 401/404 or empty response. Production workers
        do not call this method — it exists for Protocol conformance and
        one-shot scripts.
        """
        if not self.enabled:
            return None

        ticker_clean = ticker.strip().lower()
        if not ticker_clean:
            return None

        try:
            resp = self._client.get(
                f"{TIINGO_BASE_URL}/tiingo/daily/{ticker_clean}",
                headers=self._headers(),
            )
            if resp.status_code in (401, 404):
                return None
            if resp.status_code != 200:
                logger.warning(
                    "tiingo_meta_non_200 ticker=%s status=%s",
                    ticker_clean, resp.status_code,
                )
                return None
            payload = resp.json()
        except httpx.HTTPError as exc:
            logger.warning("tiingo_meta_http_error ticker=%s error=%s", ticker_clean, exc)
            return None

        if not isinstance(payload, dict):
            return None

        name = (payload.get("name") or payload.get("ticker") or ticker).strip()
        exchange = payload.get("exchangeCode") or ""

        return RawInstrumentData(
            ticker=ticker.strip().upper(),
            isin=None,
            name=name or ticker,
            instrument_type="fund",
            asset_class="equity",
            geography="US" if exchange.upper() in {"NYSE", "NASDAQ", "AMEX", "BATS"} else "unknown",
            currency="USD",
            source="tiingo",
            raw_attributes={
                "exchange": exchange,
                "description": payload.get("description") or "",
                "start_date": payload.get("startDate") or "",
                "end_date": payload.get("endDate") or "",
            },
        )

    def fetch_batch(self, tickers: list[str]) -> list[RawInstrumentData]:
        """Fetch metadata for many tickers. Fans out through the thread pool."""
        if not self.enabled or not tickers:
            return []

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._batch_concurrency,
            thread_name_prefix="tiingo-meta",
        ) as pool:
            results = list(pool.map(self.fetch_instrument, tickers))

        return [r for r in results if r is not None]

    def fetch_batch_history(
        self,
        tickers: list[str],
        period: str = "3y",
    ) -> dict[str, pd.DataFrame]:
        """Fetch EOD history for many tickers and return yfinance-shaped DataFrames.

        The NAV ingestion worker consumes this as ``dict[ticker, DataFrame]``
        where each DataFrame has a ``Close`` column and a ``DatetimeIndex``.
        """
        if not self.enabled or not tickers:
            return {}

        start_date, end_date = self._resolve_window(period)

        unique_tickers = sorted({t.strip().upper() for t in tickers if t and t.strip()})
        if not unique_tickers:
            return {}

        def _fetch_one(ticker: str) -> tuple[str, pd.DataFrame | None]:
            bars = self._fetch_single_history(ticker, start_date, end_date)
            if not bars:
                return ticker, None
            df = self._bars_to_dataframe(bars)
            if df.empty:
                return ticker, None
            return ticker, df

        result: dict[str, pd.DataFrame] = {}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self._batch_concurrency,
            thread_name_prefix="tiingo-history",
        ) as pool:
            for ticker, df in pool.map(_fetch_one, unique_tickers):
                if df is not None:
                    result[ticker] = df

        return result

    # ── Internals ──────────────────────────────────────────────────────

    def _fetch_single_history(
        self,
        ticker: str,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, Any]]:
        ticker_clean = ticker.strip().lower()
        if not ticker_clean:
            return []

        params: dict[str, str] = {
            "format": "json",
            "resampleFreq": "daily",
            "startDate": start_date.isoformat(),
            "endDate": end_date.isoformat(),
        }

        try:
            resp = self._client.get(
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
            logger.warning(
                "tiingo_daily_http_error ticker=%s error=%s",
                ticker_clean, exc,
            )
            return []

        if not isinstance(payload, list):
            return []
        return payload

    @staticmethod
    def _bars_to_dataframe(bars: list[dict[str, Any]]) -> pd.DataFrame:
        """Project Tiingo bar dicts onto a yfinance-compatible DataFrame.

        Tiingo daily returns both raw and ``adj*`` columns. We prefer adjusted
        OHLCV because the risk engine computes log returns downstream and
        dividends/splits would otherwise create spurious jumps.
        """
        rows: list[dict[str, Any]] = []
        for item in bars:
            ts_raw = item.get("date") or ""
            try:
                ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except (ValueError, AttributeError):
                continue

            close = _first_float(item, "adjClose", "close")
            if close is None:
                continue

            rows.append({
                "date": ts,
                "Open": _first_float(item, "adjOpen", "open"),
                "High": _first_float(item, "adjHigh", "high"),
                "Low": _first_float(item, "adjLow", "low"),
                "Close": close,
                "Volume": _first_float(item, "adjVolume", "volume") or 0.0,
            })

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        df = df.set_index("date").sort_index()
        df.index = pd.to_datetime(df.index).tz_convert("UTC")
        return df

    @staticmethod
    def _resolve_window(period: str) -> tuple[date, date]:
        """Translate a yfinance-style period string into (start, end) dates."""
        today = date.today()
        if period == "max":
            return _MAX_LOOKBACK_START, today
        days = _PERIOD_TO_DAYS.get(period)
        if days is None:
            logger.warning("tiingo_unknown_period period=%s fallback=3y", period)
            days = _PERIOD_TO_DAYS["3y"]
        start = today - timedelta(days=days)
        return max(start, _MAX_LOOKBACK_START), today


def _first_float(item: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = item.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None

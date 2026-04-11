# Tiingo Migration — Full Yahoo Finance Retirement

**Created:** 2026-04-11
**Status:** Plan locked, PR-A partially implemented (WIP branch), PR-B / PR-C / post-merge pending
**Owner:** Andrei
**Driver:** `blended_momentum_score` and `peer_sharpe_pctl` dropped to 0% in `fund_risk_metrics` on 2026-04-10 after the global worker was interrupted mid-run. Root cause investigation showed the NAV ingestion path has been silently degrading for months because the Yahoo-backed `nav_timeseries.aum_usd` column has **never** been populated (0 / 265k rows since January). Rather than patch Yahoo again, we are retiring it entirely in favor of the already-available Tiingo Premium REST API (no rate limit).

---

## 1. Decisions already locked

| Decision | Value | Rationale |
|---|---|---|
| Provider | Tiingo Premium (no hard rate limit) | Already paid, used for Terminal Live Workspace |
| Concurrency bound | 50 sync threads / 100 async tasks | httpx socket budget, not rate limit |
| Rollback window | None | Andrei: "retirar Yahoo de uma vez por todas" |
| Sector enrichment fallback | Dropped | 13F holdings rely on OpenFIGI + SEC CIK; Yahoo `.info["sector"]` was noisy fallback for ~5% of cases |
| Feature flag | None | Clean cutover |
| PR count | 3 PRs + 1 operational step | Fewer, fatter PRs for less ceremony |
| Historical `source='yfinance'` rows | Preserved | Migration 0110 only changes the `DEFAULT`; existing rows keep their label for audit trail |

## 2. Surface being replaced

### Yahoo touchpoints (23 backend files)

**Production code paths — must migrate:**
- `backend/app/services/providers/yahoo_finance_provider.py` — primary provider, 218 lines
- `backend/app/domains/wealth/workers/benchmark_ingest.py` — lock 900_004, **bypasses provider abstraction** and imports `yfinance` directly (`yf.download(threads=True)`)
- `backend/app/domains/wealth/workers/instrument_ingestion.py` — lock 900_010, uses `provider.fetch_batch_history` via factory
- `backend/app/domains/wealth/workers/ingestion.py` — **deprecated** (lock 900_006), delete entirely in PR-C (or PR-B as cleanup)
- `backend/data_providers/sec/shared.py` — sector enrichment fallback for 13F holdings
- `backend/data_providers/esma/seed/populate_seed.py` — ESMA seed data NAV backfill
- `backend/scripts/backfill_nav.py` — one-shot NAV backfill script
- `backend/app/services/providers/__init__.py` — factory
- `backend/app/domains/wealth/routes/instruments.py` — `POST /instruments/import-from-yahoo` endpoint (uses `provider.fetch_batch`)

**Schema/catalog references:**
- `backend/app/core/db/migrations/versions/0013_benchmark_nav.py` — `server_default: yfinance` on `benchmark_nav.source`
- `backend/app/core/db/migrations/versions/0045_instruments_global.py` — `server_default: yfinance` on `instruments_global.source`
- `backend/app/domains/wealth/models/benchmark_nav.py` — `server_default: yfinance`
- `backend/app/domains/wealth/schemas/catalog.py:30-31` — `nav_source: Literal["yfinance"] | None`, `aum_source: Literal["yfinance"] | None`
- `backend/app/domains/wealth/routes/screener.py:1063,1089-1090` — assigns `nav_source="yfinance"`

**Test mocks to rewrite (7 files):**
- `backend/tests/test_benchmark_ingest.py` — has `_make_price_df()` / `_make_multi_ticker_df()` helpers mimicking `yf.download` output
- `backend/tests/test_instrument_ingestion.py` — mocks `get_instrument_provider`; one test asserts `"YahooFinanceProvider()" not in source` — update or delete
- `backend/tests/test_fefundinfo_provider.py` — factory test already updated in WIP PR-A (line 506 → `test_returns_tiingo_when_fefundinfo_disabled`)
- `backend/tests/test_screener.py:564` — `provider = YahooFinanceProvider()` direct import
- `backend/tests/test_catalog.py` — asserts `nav_source="yfinance"` in fixtures
- `backend/tests/test_data_providers_shared.py` — sector enrichment tests
- `backend/tests/e2e_smoke_test.py:347-373` — factory smoke test

### Tiingo surface (already present)

- `backend/app/services/providers/tiingo_provider.py` — async REST wrapper, used by `routes/market_data.py` for charting seed + news
- `backend/app/core/ws/tiingo_bridge.py` — WebSocket bridge for IEX trade ticks → Redis
- `backend/app/core/config/settings.py:77` — `tiingo_api_key: str = ""` (already declared)

**No Tiingo code touches workers or NAV ingestion yet.** The entire worker path is fresh surface.

## 3. Tiingo capability audit

| Need | Tiingo endpoint | Status | Notes |
|---|---|---|---|
| EOD OHLCV (5,517 instruments, ~15y) | `GET /tiingo/daily/{ticker}/prices` | Available | Returns raw + adjusted OHLCV; prefer `adjClose` for log-return continuity over splits/dividends |
| Ticker metadata (name, exchange) | `GET /tiingo/daily/{ticker}` | Available | Returns name, exchangeCode, description, startDate, endDate — far sparser than yfinance `.info` |
| Intraday (Terminal Live) | `GET /iex/{ticker}/prices?resampleFreq=5min` | Already in use | IEX only, no mutual funds |
| News feed | `GET /tiingo/news` | Already in use | |
| **AUM / shares outstanding** | **None** | Not available | Yahoo also never populated this. Not a regression. `flow_momentum_score` will remain structurally None until we add N-CEN/XBRL quarterly → daily interpolation (out of scope). |
| Sector / industry | `/tiingo/fundamentals/{ticker}/meta` (premium) | Dropping fallback | OpenFIGI + SEC CIK + `sec_registered_funds` cover 95%+ of 13F holdings; remaining stay as `sector=None` |
| UCITS European funds | Partial via LSE/Xetra | Same as Yahoo | No regression |

## 4. Work package — PR-A (Provider layer)

**Status:** Implemented on local-only branch `feat/tiingo-migration-pr-a` in worktree `c:/Users/andre/projetos/netz-tiingo-migration`, commit `3ab773c1` (marked WIP, NOT pushed). You can either `git fetch` the worktree branch when ready or recreate from the file specs below.

**5 files touched:**
1. Modified: `backend/app/services/providers/tiingo_provider.py` (+53 lines) — async batch helper
2. New: `backend/app/services/providers/tiingo_instrument_provider.py` (280 lines) — sync worker-facing provider
3. Modified: `backend/app/services/providers/__init__.py` — factory default swapped
4. New: `backend/tests/test_tiingo_provider_layer.py` (281 lines, 17 tests) — httpx.MockTransport unit tests
5. Modified: `backend/tests/test_fefundinfo_provider.py` (1 test renamed, 1 assertion updated)

### 4.1 `tiingo_provider.py` — add async batch helper

At the top of the file, add imports and a constant:

```python
import asyncio  # add next to existing imports
...
BATCH_CONCURRENCY = 100  # add near TIINGO_BASE_URL
```

Change the constructor to accept an injectable client (for tests):

```python
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
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
    )
```

Add this method **between `fetch_historical_daily` and `fetch_historical_intraday`**:

```python
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
```

### 4.2 `tiingo_instrument_provider.py` — full file

Create `backend/app/services/providers/tiingo_instrument_provider.py` with this content:

```python
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

# yfinance period literals -> calendar-day lookbacks. Preserves the
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
    "ytd": 366,
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

    # InstrumentDataProvider Protocol

    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None:
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

    # Internals

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

        Prefer adjusted OHLCV because the risk engine computes log returns
        downstream and dividends/splits would otherwise create spurious jumps.
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
```

### 4.3 `providers/__init__.py` — factory swap

Replace the existing `get_instrument_provider()` body:

```python
from app.services.providers.csv_import_adapter import CsvImportAdapter
from app.services.providers.protocol import InstrumentDataProvider, RawInstrumentData
from app.services.providers.tiingo_instrument_provider import TiingoInstrumentProvider
from app.services.providers.yahoo_finance_provider import YahooFinanceProvider

__all__ = [
    "CsvImportAdapter",
    "InstrumentDataProvider",
    "RawInstrumentData",
    "TiingoInstrumentProvider",
    "YahooFinanceProvider",  # kept until PR-C deletes the module
    "get_instrument_provider",
]


def get_instrument_provider() -> InstrumentDataProvider:
    """Factory — returns FEFundInfo when enabled, Tiingo otherwise."""
    from app.core.config.settings import settings

    if settings.feature_fefundinfo_enabled:
        from app.services.providers.fefundinfo_client import (
            FEFundInfoClient,
            FEFundInfoTokenManager,
        )
        from app.services.providers.fefundinfo_provider import FEFundInfoProvider

        token_mgr = FEFundInfoTokenManager(
            client_id=settings.fefundinfo_client_id,
            client_secret=settings.fefundinfo_client_secret,
            token_url=settings.fefundinfo_token_url,
        )
        client = FEFundInfoClient(
            token_manager=token_mgr,
            subscription_key=settings.fefundinfo_subscription_key,
        )
        return FEFundInfoProvider(client)
    return TiingoInstrumentProvider()
```

### 4.4 Test file — `test_tiingo_provider_layer.py`

Full content is in the WIP branch commit `3ab773c1`. 17 tests covering:
- `TestAsyncBatchHistory` — happy path, partial 404, auth failure, empty input (4 tests)
- `TestSyncBatchHistory` — DataFrame contract, period translation, `max` clamps to 1970, unknown period fallback, missing close rows dropped, empty tickers, case-insensitive dedup (7 tests)
- `TestSyncMetadata` — `fetch_instrument` happy path + 404, `fetch_batch` filters failures (3 tests)
- `TestFactoryWiring` — factory returns Tiingo by default, Protocol conformance, context manager (3 tests)

All use `httpx.MockTransport` — no real HTTP. Runtime 0.84s.

### 4.5 `test_fefundinfo_provider.py` — existing test update

Only one test needs adjustment (line ~506):

```python
class TestProviderFactory:
    def test_returns_tiingo_when_fefundinfo_disabled(self) -> None:
        from app.services.providers import get_instrument_provider
        from app.services.providers.tiingo_instrument_provider import (
            TiingoInstrumentProvider,
        )

        with patch("app.core.config.settings.settings") as mock_settings:
            mock_settings.feature_fefundinfo_enabled = False
            mock_settings.tiingo_api_key = "test-key"
            provider = get_instrument_provider()

        assert isinstance(provider, TiingoInstrumentProvider)
```

`test_returns_fefundinfo_when_enabled` is unchanged.

### 4.6 Gate PR-A

```bash
cd backend
python -m ruff check app/services/providers/ tests/test_tiingo_provider_layer.py tests/test_fefundinfo_provider.py
python -m mypy app/services/providers/tiingo_provider.py app/services/providers/tiingo_instrument_provider.py app/services/providers/__init__.py --ignore-missing-imports
python -m pytest tests/test_tiingo_provider_layer.py tests/test_fefundinfo_provider.py tests/test_instrument_ingestion.py tests/test_market_data_ws.py -x
cd .. && lint-imports --config pyproject.toml  # expect "Contracts: 31 kept, 0 broken"
```

**Known pre-existing mypy issue** (not caused by PR-A, exists on main): `backend/app/services/providers/protocol.py:46` — `Missing type parameters for generic type "dict"`. Also `backend/app/domains/wealth/workers/benchmark_ingest.py:45,96,167,222` has similar pre-existing errors. Leave them alone — they are not regressions and fixing them conflicts with parallel work on routes.

## 5. Work package — PR-B (Worker cutover + migration 0110)

**Depends on:** PR-A merged.

### 5.1 Migration 0110 — default source label

`backend/app/core/db/migrations/versions/0110_tiingo_default_source.py`:

```python
"""Tiingo default source label on benchmark_nav and nav_timeseries.

Revision ID: 0110_tiingo_default_source
Revises: 0109_risk_metrics_audit_trail  # check current head with `alembic heads`
Create Date: 2026-04-11

Only the DEFAULT is changed. Existing rows keep source='yfinance' as a
historical record of which provider ingested them. Future rows written
after PR-B ships will carry source='tiingo'.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0110_tiingo_default_source"
down_revision = "0109_risk_metrics_audit_trail"  # verify with `alembic heads`
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "benchmark_nav",
        "source",
        server_default=sa.text("'tiingo'"),
    )
    op.alter_column(
        "nav_timeseries",
        "source",
        server_default=sa.text("'tiingo'"),
    )


def downgrade() -> None:
    op.alter_column(
        "benchmark_nav",
        "source",
        server_default=sa.text("'yfinance'"),
    )
    op.alter_column(
        "nav_timeseries",
        "source",
        server_default=sa.text("'yfinance'"),
    )
```

**Before writing, verify the revision chain:**
```bash
cd backend && alembic heads
```
The current head at plan-write time is `0105_portfolio_calibration_fk_on_construction_runs` per CLAUDE.md, but by the time PR-B runs the head will have advanced. Update `down_revision` accordingly.

**Safety:** `ALTER COLUMN ... SET DEFAULT` is metadata-only in PostgreSQL — no table rewrite, no locks beyond an instant ACCESS EXCLUSIVE on the catalog row. Safe on a 265k-row `nav_timeseries` hypertable.

### 5.2 Worker cutover — `instrument_ingestion.py`

The worker already goes through `get_instrument_provider()`, so **the factory swap in PR-A already routes it to Tiingo**. The only change in PR-B is cleanup of Yahoo-specific artifacts:

1. Docstring on line 1-9: "using Yahoo Finance" → "using Tiingo"
2. Line 8: "one Yahoo call per unique ticker" → "one Tiingo call per unique ticker"
3. Line 42-43, 62: rename `_LOOKBACK_TO_PERIOD` / `_resolve_period` docstring references from "yfinance period strings" to "period strings" (the Tiingo provider handles the same vocabulary)
4. Line 279: `"source": "yahoo"` → `"source": "tiingo"`

### 5.3 Worker cutover — `benchmark_ingest.py` (the hard one)

**This worker bypasses the provider abstraction** and imports `yfinance` directly. It needs to be rewritten to use `TiingoInstrumentProvider`.

Current structure (lines 45-170 roughly):
```python
import yfinance as yf

def _batch_download(tickers, period):
    return yf.download(tickers, period=period, group_by="ticker", threads=True, progress=False)

async def run_benchmark_ingest():
    ...
    df = _batch_download(tickers, period)
    for ticker in df.columns.get_level_values(0):
        ticker_df = df[ticker]
        # ... write to benchmark_nav ...
```

Target rewrite:
```python
from app.services.providers.tiingo_instrument_provider import TiingoInstrumentProvider

async def run_benchmark_ingest():
    ...
    tickers = [block.benchmark_ticker for block in blocks if block.benchmark_ticker]
    loop = asyncio.get_event_loop()

    def _fetch() -> dict[str, pd.DataFrame]:
        with TiingoInstrumentProvider() as provider:
            return provider.fetch_batch_history(tickers, period=period)

    history = await loop.run_in_executor(_io_executor, _fetch)

    for ticker, ticker_df in history.items():
        if ticker_df.empty or "Close" not in ticker_df.columns:
            logger.warning("benchmark_ticker_not_found", ticker=ticker)
            continue
        # ... same upsert logic as before ...
```

Dedicated thread pool at module level:
```python
_io_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="benchmark-io")
```

Line 255: `"source": "yfinance"` → `"source": "tiingo"`.

### 5.4 Deprecated worker — delete `ingestion.py`

`backend/app/domains/wealth/workers/ingestion.py` is marked deprecated (lock 900_006). In PR-B:

1. `git rm backend/app/domains/wealth/workers/ingestion.py`
2. Search for any remaining references: `grep -r "wealth.workers.ingestion\|run_ingestion\|900_006" backend/`
3. Remove references from `backend/manifests/workers.json` if present
4. Remove from any route that triggers it manually

### 5.5 Catalog + schema updates

`backend/app/domains/wealth/schemas/catalog.py` lines 30-31:
```python
nav_source: Literal["yfinance", "tiingo"] | None = None
aum_source: Literal["yfinance", "tiingo"] | None = None
```

Keeping `"yfinance"` in the Literal preserves deserialization of historical rows. New code paths write `"tiingo"`.

`backend/app/domains/wealth/routes/screener.py` lines 1063, 1089-1090:
```python
nav_source="tiingo",  # was "yfinance"
```

`backend/app/domains/wealth/models/benchmark_nav.py` line 37:
```python
source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="tiingo")
```

### 5.6 Gate PR-B

```bash
cd backend
python -m alembic upgrade head  # apply 0110 on dev DB
python -m ruff check app/domains/wealth/workers/ app/domains/wealth/schemas/catalog.py app/domains/wealth/routes/screener.py
python -m mypy app/domains/wealth/workers/benchmark_ingest.py app/domains/wealth/workers/instrument_ingestion.py --ignore-missing-imports
python -m pytest tests/test_benchmark_ingest.py tests/test_instrument_ingestion.py -x  # will fail — PR-C rewrites mocks
```

**Expected test failures in PR-B:** `test_benchmark_ingest.py` and `test_instrument_ingestion.py` fixtures still build yfinance-shaped DataFrames. They will break when the worker calls Tiingo. Two options:

- **Option 1 (recommended):** update the fixtures in PR-B at the same time as the worker rewrite. The DataFrame shape is the same (`Close` column + DatetimeIndex), so fixtures need only a renaming of `_make_price_df` to a Tiingo-shaped mock and patching `TiingoInstrumentProvider` instead of `yf.download`.
- **Option 2:** mark failing tests xfail in PR-B, fix in PR-C. Less clean, but smaller PR-B.

Go with Option 1.

## 6. Work package — PR-C (Cleanup)

**Depends on:** PR-B merged and stable in production for at least one worker cycle (verify `benchmark_nav` and `nav_timeseries` show fresh rows with `source='tiingo'`).

### 6.1 Delete Yahoo provider

```bash
git rm backend/app/services/providers/yahoo_finance_provider.py
```

Update `backend/app/services/providers/__init__.py`:
- Remove `from app.services.providers.yahoo_finance_provider import YahooFinanceProvider`
- Remove `"YahooFinanceProvider"` from `__all__`

### 6.2 Remove `yfinance` dependency

`pyproject.toml`:
- Remove `"yfinance>=0.2.40",` (or whatever version) from `dependencies`
- Remove `"yfinance.*",` from `[[tool.mypy.overrides]]`

Then `pip install -e .` to purge the package locally and confirm no import errors.

### 6.3 Drop sector fallback

`backend/data_providers/sec/shared.py` lines ~522-870 — there are multiple functions using `yf.Ticker(ticker).info.get("sector")` as fallback after OpenFIGI resolution fails.

Replace each fallback block with:
```python
# Sector left None when OpenFIGI + SEC CIK cannot resolve.
# Previously fell back to yfinance .info["sector"] but the data was noisy
# and covered only ~5% of remaining cases.
sector = None
```

Delete the `import yfinance` at the top of the file.

### 6.4 Backfill + seed scripts

`backend/scripts/backfill_nav.py`:
- Replace `yf.download()` calls with `TiingoInstrumentProvider.fetch_batch_history()`
- Update the `--help` docstring

`backend/data_providers/esma/seed/populate_seed.py` lines 17, 542-563:
- Same replacement pattern
- Remove noise-suppression code that was specific to yfinance warnings

### 6.5 Rewrite test mocks (7 files)

General pattern: replace `patch("yfinance.download", ...)` with `patch.object(TiingoInstrumentProvider, "fetch_batch_history", return_value={...})`.

For each file:

**`test_benchmark_ingest.py`** — `_make_price_df()` / `_make_multi_ticker_df()` helpers already return `dict[ticker, DataFrame]` shape that's compatible. Just:
- Rename the mock target from `yf.download` to `TiingoInstrumentProvider.fetch_batch_history`
- Drop the `MultiIndex` column construction (Tiingo returns flat per-ticker DataFrames already)

**`test_instrument_ingestion.py`:**
- Line 414: delete `test_import_from_yahoo_uses_factory` or rename to `test_import_uses_factory`
- Line 421: delete `assert "YahooFinanceProvider()" not in source`
- All `@patch("app.domains.wealth.workers.instrument_ingestion.get_instrument_provider")` mocks continue to work — just make sure the mock `.fetch_batch_history.return_value` returns yfinance-shaped DataFrames (same as today)

**`test_screener.py` line 564:** delete `provider = YahooFinanceProvider()` and the surrounding test, or replace with `TiingoInstrumentProvider`.

**`test_catalog.py`:** replace `nav_source="yfinance"` with `nav_source="tiingo"` in fixtures (or keep both as a parametrize since the Literal still accepts both).

**`test_data_providers_shared.py`:** update sector enrichment tests to assert `sector is None` when OpenFIGI fails, instead of yfinance fallback.

**`test_fefundinfo_provider.py`:** already updated in PR-A.

**`e2e_smoke_test.py`:** lines 347-373 — update factory smoke test to expect `TiingoInstrumentProvider`.

### 6.6 Gate PR-C

```bash
make check  # full gate must pass — this is the final sign-off
```

## 7. Post-merge operations (not a PR)

After PR-A + PR-B + PR-C are merged and deployed:

### 7.1 Re-ingest NAV via Tiingo

```bash
cd backend
python scripts/run_global_worker.py instrument_ingestion  # or whatever the correct entrypoint is
```

Monitor logs for:
- `tiingo_daily_non_200` warnings (expected: a handful for delisted/unknown tickers)
- `instrument_ingestion_complete` summary — target ~5,500 unique tickers processed

Verify:
```sql
SELECT source, COUNT(*), MAX(nav_date)
FROM nav_timeseries
WHERE nav_date >= CURRENT_DATE - INTERVAL '2 days'
GROUP BY source;
```
Expect `source='tiingo'` with `MAX(nav_date) = CURRENT_DATE` (or previous trading day).

### 7.2 Re-run global_risk_metrics

```bash
cd backend
python scripts/run_global_risk_metrics.py
```

Runtime: ~15-30 min for 28 batches of 200 instruments. Watch for the `global_risk_metrics.peer_ranking_done` log line at the end — that confirms Pass 2 (peer percentiles) ran to completion.

### 7.3 Validate coverage

```sql
WITH stats AS (
  SELECT
    COUNT(*) AS t,
    COUNT(blended_momentum_score) AS blended_cnt,
    COUNT(peer_sharpe_pctl) AS peer_cnt,
    COUNT(nav_momentum_score) AS nav_cnt,
    COUNT(rsi_14) AS rsi_cnt
  FROM fund_risk_metrics
  WHERE calc_date = CURRENT_DATE
)
SELECT
  t AS total_rows,
  ROUND(100.0 * blended_cnt / NULLIF(t, 0), 1) AS blended_pct,
  ROUND(100.0 * peer_cnt / NULLIF(t, 0), 1) AS peer_pct,
  ROUND(100.0 * nav_cnt / NULLIF(t, 0), 1) AS nav_pct,
  ROUND(100.0 * rsi_cnt / NULLIF(t, 0), 1) AS rsi_pct
FROM stats;
```

**Success criteria:**
- `total_rows` ≥ 5,400 (instruments with sufficient NAV history)
- `blended_pct` ≥ 85% (momentum signals populated)
- `peer_pct` ≥ 95% (Pass 2 ran)
- `nav_pct` ≥ 85%
- `rsi_pct` ≥ 85%

### 7.4 Known remaining gap — `flow_momentum_score`

`flow_momentum_score` will remain structurally None because Tiingo does not provide daily AUM / shares outstanding. The code path is in `risk_calc.py:446` — `compute_flow_momentum()` is called only when `aum.any()` is truthy, and the `nav_timeseries.aum_usd` column will stay at 0% coverage.

**Not in scope for this migration.** Follow-up options if needed later:
1. Accept the limitation and document in `fund-risk-metrics-state-*.md`
2. Interpolate quarterly N-PORT total_assets / N-CEN net_assets to daily — adds accounting noise but gives a monthly-ish signal
3. Remove the `flow_momentum_score` column, `compute_flow_momentum()` function, and the flow branch in `_compute_momentum_from_nav()` — cleanest if we never plan to add a daily AUM source

Decision deferred to Andrei after this migration lands.

## 8. Open items before execution

1. **Verify current alembic head** — update `down_revision` in migration 0110 before applying
2. **Confirm Tiingo Premium is live** — check `settings.tiingo_api_key` is set in Railway prod env vars
3. **Decide fixtures rewrite scope** — Option 1 (in PR-B) vs Option 2 (in PR-C). Plan recommends Option 1.
4. **`flow_momentum_score`** — keep or remove post-migration (section 7.4)
5. **Import endpoint rename** — `POST /instruments/import-from-yahoo` in `routes/instruments.py:290` — cosmetic rename to `/instruments/import` in PR-C? Or leave for backward compat with any external callers?

## 9. Rollback plan

None of the PRs are reversible in the sense that "Yahoo is gone forever" — but each PR has a safe revert path until post-merge operations run:

- **PR-A revert:** Delete `tiingo_instrument_provider.py`, revert `__init__.py`. Factory goes back to Yahoo. Zero impact on running workers.
- **PR-B revert:** Revert the worker cutover commits. Migration 0110 can be downgraded with `alembic downgrade -1`. All existing data rows keep their source labels.
- **PR-C revert:** Restore `yahoo_finance_provider.py` + `yfinance` dep from git history. All production data paths still work because PR-B's Tiingo cutover is separate.

After post-merge re-ingest (section 7.1), rollback is still possible but `nav_timeseries` will have a mix of `source='tiingo'` and `source='yfinance'` rows. Reverting does not delete the Tiingo rows — they just become historical.

## 10. State on 2026-04-11 (plan creation)

- Worktree: `c:/Users/andre/projetos/netz-tiingo-migration` on branch `feat/tiingo-migration-pr-a`, commit `3ab773c1` (local-only WIP, NOT pushed, NOT merged)
- Main checkout: `c:/Users/andre/projetos/netz-analysis-engine` on `feat/terminal-unification` with 21 uncommitted Svelte files and a few reference docs from parallel sessions — do not touch
- Current `fund_risk_metrics` gap: `blended_momentum_score` 0%, `peer_sharpe_pctl` 0% on `calc_date=2026-04-10`. Will self-heal when post-merge section 7.2 runs.
- Current NAV freshness: `nav_timeseries` stops at 2026-03-29 (12 days stale). Yahoo ingestion has been broken since then.

## 11. When you are ready to execute

From the main checkout:
```bash
git fetch origin main
git worktree remove c:/Users/andre/projetos/netz-tiingo-migration --force  # only if you want a fresh start
git worktree add -b feat/tiingo-migration-pr-a c:/Users/andre/projetos/netz-tiingo-migration-v2 origin/main
```

Or to continue from the WIP branch:
```bash
cd c:/Users/andre/projetos/netz-tiingo-migration
git log --oneline -1  # should show 3ab773c1 WIP: PR-A Tiingo provider layer
# Squash the WIP into a real PR-A commit when ready:
git reset --soft origin/main
git commit -m "feat(providers): Tiingo instrument provider layer for NAV ingestion"
git push -u origin feat/tiingo-migration-pr-a
gh pr create --base main --title "feat(providers): Tiingo instrument provider layer" --body "See docs/plans/2026-04-11-tiingo-migration-plan.md section 4"
```

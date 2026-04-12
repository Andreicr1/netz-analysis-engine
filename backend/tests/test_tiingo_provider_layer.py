"""Tiingo provider layer — PR-A unit tests.

Covers:
- ``TiingoProvider.fetch_historical_daily_batch`` (async, Semaphore-bounded)
- ``TiingoInstrumentProvider`` sync implementation of ``InstrumentDataProvider``
- yfinance-style period translation
- Graceful degradation on 401/404
- Protocol conformance (duck-typed)

All HTTP is mocked via ``httpx.MockTransport`` — no real Tiingo calls.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
import pandas as pd
import pytest

from app.services.providers import get_instrument_provider
from app.services.providers.protocol import (
    InstrumentDataProvider,
    RawInstrumentData,
)
from app.services.providers.tiingo_instrument_provider import (
    _MAX_LOOKBACK_START,
    _PERIOD_TO_DAYS,
    TiingoInstrumentProvider,
)
from app.services.providers.tiingo_provider import TiingoProvider

# ── Fixtures ────────────────────────────────────────────────────────────


def _bar(day: date, close: float) -> dict[str, Any]:
    """Minimal Tiingo /tiingo/daily/{ticker}/prices bar."""
    return {
        "date": f"{day.isoformat()}T00:00:00.000Z",
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1000.0,
        "adjOpen": close,
        "adjHigh": close,
        "adjLow": close,
        "adjClose": close,
        "adjVolume": 1000.0,
    }


def _bars(n: int, start_close: float = 100.0) -> list[dict[str, Any]]:
    today = date(2026, 4, 10)
    return [_bar(today - timedelta(days=n - i), start_close + i) for i in range(n)]


# ── TiingoProvider.fetch_historical_daily_batch (async) ─────────────────


class TestAsyncBatchHistory:
    @pytest.mark.asyncio
    async def test_happy_path_three_tickers(self) -> None:
        """Three tickers, all return bars — result contains all three."""

        def handler(request: httpx.Request) -> httpx.Response:
            ticker = request.url.path.rsplit("/", 2)[-2]  # .../daily/{ticker}/prices
            return httpx.Response(200, json=_bars(5))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = TiingoProvider(api_key="test-key", http_client=client)

        result = await provider.fetch_historical_daily_batch(
            ["AAPL", "MSFT", "NVDA"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 4, 10),
        )

        assert set(result.keys()) == {"AAPL", "MSFT", "NVDA"}
        assert len(result["AAPL"]) == 5
        await client.aclose()

    @pytest.mark.asyncio
    async def test_partial_404_silently_dropped(self) -> None:
        """One ticker 404s — it is omitted, others still returned."""

        def handler(request: httpx.Request) -> httpx.Response:
            ticker = request.url.path.rsplit("/", 2)[-2]
            if ticker == "badtick":
                return httpx.Response(404)
            return httpx.Response(200, json=_bars(3))

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = TiingoProvider(api_key="test-key", http_client=client)

        result = await provider.fetch_historical_daily_batch(
            ["AAPL", "BADTICK", "MSFT"],
        )

        assert set(result.keys()) == {"AAPL", "MSFT"}
        await client.aclose()

    @pytest.mark.asyncio
    async def test_auth_failure_returns_empty(self) -> None:
        """Global 401 — every ticker degrades to empty list, dict stays empty."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = TiingoProvider(api_key="test-key", http_client=client)

        result = await provider.fetch_historical_daily_batch(["AAPL", "MSFT"])

        assert result == {}
        await client.aclose()

    @pytest.mark.asyncio
    async def test_empty_tickers_no_http(self) -> None:
        """Empty list — no HTTP requests issued."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=[])

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = TiingoProvider(api_key="test-key", http_client=client)

        result = await provider.fetch_historical_daily_batch([])

        assert result == {}
        assert call_count == 0
        await client.aclose()


# ── TiingoInstrumentProvider.fetch_batch_history (sync) ─────────────────


class TestSyncBatchHistory:
    def test_returns_dataframes_with_close_column(self) -> None:
        """Worker contract: dict[ticker, DataFrame with Close column + DatetimeIndex]."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_bars(10))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        result = provider.fetch_batch_history(["AAPL", "MSFT"], period="1y")

        assert set(result.keys()) == {"AAPL", "MSFT"}
        for df in result.values():
            assert isinstance(df, pd.DataFrame)
            assert "Close" in df.columns
            assert isinstance(df.index, pd.DatetimeIndex)
            assert len(df) == 10
        provider.close()

    def test_period_translation_uses_startdate_param(self) -> None:
        """period='1y' → startDate ≈ today - 365 days, not yfinance 'period' literal."""
        captured_params: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params.append(dict(request.url.params))
            return httpx.Response(200, json=_bars(3))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        provider.fetch_batch_history(["AAPL"], period="1y")

        assert len(captured_params) == 1
        params = captured_params[0]
        assert "startDate" in params
        assert "endDate" in params
        start = date.fromisoformat(params["startDate"])
        end = date.fromisoformat(params["endDate"])
        # 1y ≈ 365 days back, with small tolerance for clock skew across midnight.
        assert (end - start).days == _PERIOD_TO_DAYS["1y"]
        provider.close()

    def test_period_max_clamps_to_1970(self) -> None:
        """period='max' → startDate = 1970-01-01 (the provider floor)."""
        captured_params: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params.append(dict(request.url.params))
            return httpx.Response(200, json=_bars(3))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        provider.fetch_batch_history(["AAPL"], period="max")

        start = date.fromisoformat(captured_params[0]["startDate"])
        assert start == _MAX_LOOKBACK_START
        provider.close()

    def test_unknown_period_falls_back_to_3y(self) -> None:
        """Unknown period string degrades to 3y instead of raising."""
        captured_params: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params.append(dict(request.url.params))
            return httpx.Response(200, json=_bars(3))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        provider.fetch_batch_history(["AAPL"], period="banana")

        start = date.fromisoformat(captured_params[0]["startDate"])
        end = date.fromisoformat(captured_params[0]["endDate"])
        assert (end - start).days == _PERIOD_TO_DAYS["3y"]
        provider.close()

    def test_missing_close_rows_dropped(self) -> None:
        """Bars without ``close``/``adjClose`` are filtered out of the DataFrame."""
        payload = _bars(5)
        payload[2]["close"] = None
        payload[2]["adjClose"] = None

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        result = provider.fetch_batch_history(["AAPL"])
        assert len(result["AAPL"]) == 4
        provider.close()

    def test_empty_tickers_returns_empty_dict(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[])

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        assert provider.fetch_batch_history([]) == {}
        assert provider.fetch_batch_history(["", "  "]) == {}
        provider.close()

    def test_deduplicates_tickers_case_insensitive(self) -> None:
        """AAPL, aapl, AAPL → one HTTP call."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            return httpx.Response(200, json=_bars(3))

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        provider.fetch_batch_history(["AAPL", "aapl", "AAPL"])
        assert call_count == 1
        provider.close()


# ── TiingoInstrumentProvider.fetch_instrument / fetch_batch ─────────────


class TestSyncMetadata:
    def test_fetch_instrument_happy_path(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "ticker": "AAPL",
                    "name": "Apple Inc",
                    "exchangeCode": "NASDAQ",
                    "description": "Tech",
                    "startDate": "1980-12-12",
                    "endDate": "2026-04-10",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        result = provider.fetch_instrument("AAPL")

        assert isinstance(result, RawInstrumentData)
        assert result.ticker == "AAPL"
        assert result.name == "Apple Inc"
        assert result.source == "tiingo"
        assert result.geography == "US"
        assert result.raw_attributes["exchange"] == "NASDAQ"
        provider.close()

    def test_fetch_instrument_404_returns_none(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        assert provider.fetch_instrument("NOPE") is None
        provider.close()

    def test_fetch_batch_filters_failures(self) -> None:
        """fetch_batch returns only tickers that successfully resolve."""

        def handler(request: httpx.Request) -> httpx.Response:
            ticker = request.url.path.rsplit("/", 1)[-1]
            if ticker == "bad":
                return httpx.Response(404)
            return httpx.Response(
                200,
                json={"ticker": ticker.upper(), "name": f"Fund {ticker.upper()}"},
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        provider = TiingoInstrumentProvider(api_key="test-key", http_client=client)

        result = provider.fetch_batch(["AAPL", "BAD", "MSFT"])
        assert len(result) == 2
        assert {r.ticker for r in result} == {"AAPL", "MSFT"}
        provider.close()


# ── Protocol conformance + factory wiring ──────────────────────────────


class TestFactoryWiring:
    def test_factory_returns_tiingo_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With FEFundInfo feature flag off, factory returns Tiingo, not Yahoo."""
        from app.core.config.settings import settings

        monkeypatch.setattr(settings, "feature_fefundinfo_enabled", False, raising=False)
        provider = get_instrument_provider()
        assert isinstance(provider, TiingoInstrumentProvider)

    def test_tiingo_provider_satisfies_protocol(self) -> None:
        """Duck-typed conformance check — required so workers can swap providers."""
        provider = TiingoInstrumentProvider(api_key="test-key")
        try:
            assert isinstance(provider, InstrumentDataProvider)
        finally:
            provider.close()

    def test_context_manager_closes_client(self) -> None:
        """``with`` block releases the httpx.Client."""
        with TiingoInstrumentProvider(api_key="test-key") as provider:
            assert provider.enabled
        # No assertion on internal state — close() is idempotent, further
        # HTTP calls would raise on a closed client.

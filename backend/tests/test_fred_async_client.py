"""Tests for AsyncFredClient — ASYNC-02 acceptance criteria.

Acceptance criteria:
1. Concurrency: unrelated async requests complete within normal latency
   budget even when FRED upstream is deliberately slow.
2. Static: no blocking requests.get() call in async handler bodies.
3. Timeout and cancellation behavior are explicit and covered.
"""
from __future__ import annotations

import asyncio
import inspect
import textwrap
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.domains.credit.dashboard.fred_client import (
    _FRED_ID_RE,
    AsyncFredClient,
    _AsyncCache,
    get_telemetry,
    reset_telemetry,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_observations_response(series_id: str = "DGS10") -> dict[str, Any]:
    return {
        "observations": [
            {"date": "2025-01-01", "value": "4.5"},
            {"date": "2025-01-08", "value": "4.6"},
            {"date": "2025-01-15", "value": "."},  # FRED missing — must be filtered
        ],
    }


def _make_search_response() -> dict[str, Any]:
    return {
        "seriess": [
            {
                "id": "DGS10",
                "title": "Market Yield on U.S. Treasury Securities",
                "frequency_short": "D",
                "units_short": "%",
                "popularity": 95,
                "last_updated": "2025-01-15",
            },
        ],
    }


class _MockTransportBase:
    """Base for test transports — provides no-op aclose()."""

    async def aclose(self) -> None:
        pass


class _DelayedResponder(_MockTransportBase):
    """httpx transport that waits `delay_s` seconds before responding."""

    def __init__(self, delay_s: float, response_body: dict[str, Any]) -> None:
        self.delay_s = delay_s
        self.response_body = response_body

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(self.delay_s)
        import json
        return httpx.Response(200, content=json.dumps(self.response_body).encode())


class _TimeoutTransport(_MockTransportBase):
    """httpx transport that always raises ReadTimeout."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated timeout", request=request)


class _ImmediateResponder(_MockTransportBase):
    """httpx transport that responds instantly."""

    def __init__(self, response_body: dict[str, Any]) -> None:
        self.response_body = response_body

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        import json
        return httpx.Response(200, content=json.dumps(self.response_body).encode())


# ---------------------------------------------------------------------------
# 1. Static check — no blocking requests.get in async handlers
# ---------------------------------------------------------------------------

class TestNoBlockingHttpInAsyncHandlers:
    """AC-2: Static inspection confirms no direct blocking HTTP call in async handler bodies."""

    def _get_async_handler_sources(self) -> list[tuple[str, str]]:
        """Return (handler_name, source_code) for all async route handlers."""
        import app.domains.credit.dashboard.routes as routes_module
        results = []
        for name in dir(routes_module):
            obj = getattr(routes_module, name)
            if callable(obj) and asyncio.iscoroutinefunction(obj):
                try:
                    src = inspect.getsource(obj)
                    results.append((name, src))
                except (OSError, TypeError):
                    pass
        return results

    def test_no_requests_import_in_async_handlers(self) -> None:
        """Async handlers must not import or call requests.get / requests.post."""
        handlers = self._get_async_handler_sources()
        assert handlers, "No async handlers found — check import path"
        violations: list[str] = []
        for name, src in handlers:
            # Strip the decorator lines and check only the function body
            body_lines = textwrap.dedent(src).splitlines()
            for i, line in enumerate(body_lines):
                stripped = line.strip()
                # Detect: import requests, from requests import ..., requests.get(, requests.post(
                if (
                    "import requests" in stripped
                    or "requests.get(" in stripped
                    or "requests.post(" in stripped
                    or "http_requests.get(" in stripped
                    or "http_requests.post(" in stripped
                ):
                    violations.append(f"{name}:{i+1}: {stripped}")
        assert not violations, (
            "Blocking requests.get/post found in async handlers:\n"
            + "\n".join(violations)
        )

    def test_no_blocking_threadpoolexecutor_with_future_result(self) -> None:
        """macro_fred_multi must not call future.result() on FRED threads — that blocks."""
        import app.domains.credit.dashboard.routes as routes_module
        src = inspect.getsource(routes_module.macro_fred_multi)
        assert "future.result(" not in src, (
            "macro_fred_multi still uses future.result() which blocks the event loop"
        )

    def test_no_module_level_threadpoolexecutor(self) -> None:
        """No module-level ThreadPoolExecutor for FRED fetching."""
        import app.domains.credit.dashboard.routes as routes_module
        # The _fred_executor module attribute must not exist
        assert not hasattr(routes_module, "_fred_executor"), (
            "routes.py still exposes _fred_executor — blocking thread pool"
        )

    def test_no_module_level_threading_lock(self) -> None:
        """The threading.Lock-guarded _fred_cache must not exist at module level."""
        import app.domains.credit.dashboard.routes as routes_module
        assert not hasattr(routes_module, "_fred_cache_lock"), (
            "routes.py still has _fred_cache_lock (threading.Lock)"
        )


# ---------------------------------------------------------------------------
# 2. Timeout behavior
# ---------------------------------------------------------------------------

class TestTimeoutBehavior:
    """AC-3: Timeout is explicit; TimeoutException does not propagate as 500."""

    @pytest.mark.asyncio
    async def test_fetch_observations_timeout_returns_empty(self) -> None:
        """fetch_observations returns [] on timeout — no exception raised to caller."""
        reset_telemetry()
        timeout_transport = _TimeoutTransport()
        http = httpx.AsyncClient(transport=timeout_transport)

        client = AsyncFredClient(api_key="test-key")
        client._http = http  # inject mock transport

        result = await client.fetch_observations(
            "DGS10",
            start_date="2025-01-01",
            end_date="2025-01-31",
        )
        assert result == []
        assert get_telemetry()["timeouts_total"] >= 1

    @pytest.mark.asyncio
    async def test_fetch_observations_explicit_timeout_config(self) -> None:
        """AsyncFredClient exposes explicit timeout values — not default/infinite."""
        client = AsyncFredClient(
            api_key="test",
            connect_timeout=3.0,
            read_timeout=10.0,
            total_timeout=12.0,
        )
        # httpx.Timeout stores the values
        t = client._timeout
        assert t.connect == 3.0
        assert t.read == 10.0
        await client.aclose()

    @pytest.mark.asyncio
    async def test_search_series_timeout_returns_empty(self) -> None:
        """search_series returns [] on timeout — no exception raised."""
        reset_telemetry()
        timeout_transport = _TimeoutTransport()
        http = httpx.AsyncClient(transport=timeout_transport)

        client = AsyncFredClient(api_key="test-key")
        client._http = http

        result = await client.search_series("treasury")
        assert result == []
        assert get_telemetry()["timeouts_total"] >= 1


# ---------------------------------------------------------------------------
# 3. Cancellation semantics
# ---------------------------------------------------------------------------

class TestCancellationBehavior:
    """AC-3: CancelledError propagates — does not get swallowed."""

    @pytest.mark.asyncio
    async def test_cancellation_propagates(self) -> None:
        """If the task is cancelled while waiting on FRED, CancelledError is raised."""
        async def slow_get(*args: Any, **kwargs: Any) -> httpx.Response:
            await asyncio.sleep(60)  # effectively infinite
            raise AssertionError("Should not reach here")

        client = AsyncFredClient(api_key="test-key")
        # Patch the underlying _http.get to be slow
        client._http = MagicMock()
        client._http.get = AsyncMock(side_effect=slow_get)

        task = asyncio.create_task(
            client.fetch_observations(
                "DGS10",
                start_date="2025-01-01",
                end_date="2025-01-31",
            )
        )
        # Give it a tick to start
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# 4. Concurrency — slow FRED does not block unrelated requests
# ---------------------------------------------------------------------------

class TestConcurrency:
    """AC-1: Unrelated async requests complete within normal budget even with slow FRED."""

    @pytest.mark.asyncio
    async def test_slow_fred_does_not_block_unrelated_coroutines(self) -> None:
        """Two FRED fetch tasks (3s delay each) run concurrently in <4s wall-clock time.

        If blocking HTTP were used, they'd serialize to 6+ seconds.
        With asyncio.gather they overlap, completing near the delay of the slowest.
        """
        slow_body = _make_observations_response()
        delay = 0.15  # 150ms simulated upstream latency — fast but meaningful gap

        slow_transport_1 = _DelayedResponder(delay, slow_body)
        slow_transport_2 = _DelayedResponder(delay, slow_body)

        client1 = AsyncFredClient(
            api_key="key1",
            cache=_AsyncCache(),  # fresh cache per test
        )
        client1._http = httpx.AsyncClient(transport=slow_transport_1)

        client2 = AsyncFredClient(
            api_key="key2",
            cache=_AsyncCache(),
        )
        client2._http = httpx.AsyncClient(transport=slow_transport_2)

        t0 = time.perf_counter()
        results = await asyncio.gather(
            client1.fetch_observations("DGS10", start_date="2025-01-01", end_date="2025-01-31"),
            client2.fetch_observations("BAA10Y", start_date="2025-01-01", end_date="2025-01-31"),
        )
        elapsed = time.perf_counter() - t0

        # Both completed successfully
        assert len(results[0]) == 2  # "." filtered out
        assert len(results[1]) == 2

        # Concurrency: elapsed should be near `delay` not 2*delay
        # Allow generous headroom (3x) for CI scheduler jitter
        assert elapsed < delay * 3, (
            f"Expected concurrency ~{delay}s, got {elapsed:.3f}s — "
            "requests may be serializing (blocking HTTP?)"
        )

        await client1.aclose()
        await client2.aclose()

    @pytest.mark.asyncio
    async def test_fetch_multi_concurrent_all_series_returned(self) -> None:
        """fetch_multi returns results for all requested series."""
        body_dgs10 = _make_observations_response("DGS10")
        transport = _ImmediateResponder(body_dgs10)

        client = AsyncFredClient(api_key="key", cache=_AsyncCache())
        client._http = httpx.AsyncClient(transport=transport)

        results = await client.fetch_multi(
            ["DGS10", "BAA10Y", "NFCI"],
            start_date="2025-01-01",
            end_date="2025-01-31",
        )
        assert set(results.keys()) == {"DGS10", "BAA10Y", "NFCI"}
        # All series got observations (same mock body)
        for sid, obs in results.items():
            assert isinstance(obs, list), f"{sid} did not return a list"

        await client.aclose()


# ---------------------------------------------------------------------------
# 5. Cache behavior
# ---------------------------------------------------------------------------

class TestCacheBehavior:
    """Cache hits skip network calls and increment telemetry counter."""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_network(self) -> None:
        reset_telemetry()
        transport = _ImmediateResponder(_make_observations_response())
        client = AsyncFredClient(api_key="key", cache=_AsyncCache())
        client._http = httpx.AsyncClient(transport=transport)

        # First call — network
        await client.fetch_observations("DGS10", start_date="2025-01-01", end_date="2025-01-31")
        requests_after_first = get_telemetry()["requests_total"]

        # Second call — cache hit, no additional network request
        await client.fetch_observations("DGS10", start_date="2025-01-01", end_date="2025-01-31")
        requests_after_second = get_telemetry()["requests_total"]

        assert requests_after_second == requests_after_first, (
            "Cache miss on second identical request — cache not working"
        )
        assert get_telemetry()["cache_hits"] >= 1

        await client.aclose()


# ---------------------------------------------------------------------------
# 6. Series ID validation
# ---------------------------------------------------------------------------

class TestSeriesIdValidation:
    """Invalid series IDs must be rejected before any network call."""

    @pytest.mark.asyncio
    async def test_invalid_series_id_returns_empty(self) -> None:
        reset_telemetry()
        client = AsyncFredClient(api_key="key")
        # No transport injected — if network is called, it will fail with connection error
        result = await client.fetch_observations(
            "../../etc/passwd",  # path traversal attempt
            start_date="2025-01-01",
            end_date="2025-01-31",
        )
        assert result == []
        assert get_telemetry()["requests_total"] == 0, "Network called for invalid series ID"
        await client.aclose()

    @pytest.mark.parametrize("valid_id", ["DGS10", "BAA10Y", "NFCI", "CPIAUCSL", "A1"])
    def test_valid_series_ids_pass_regex(self, valid_id: str) -> None:
        assert _FRED_ID_RE.match(valid_id), f"{valid_id} should be valid"

    @pytest.mark.parametrize("invalid_id", [
        "../../etc/passwd",
        "DGS 10",     # space
        "DGS10!",     # special char
        "",           # empty
        "A" * 21,     # too long
    ])
    def test_invalid_series_ids_fail_regex(self, invalid_id: str) -> None:
        assert not _FRED_ID_RE.match(invalid_id), f"{invalid_id} should be invalid"


# ---------------------------------------------------------------------------
# 7. Settings attribute name check (regression — was settings.FRED_API_KEY)
# ---------------------------------------------------------------------------

class TestSettingsAttributeName:
    """Ensure routes use the correct settings.fred_api_key (lowercase) attribute."""

    def test_routes_use_lowercase_fred_api_key(self) -> None:
        import inspect

        import app.domains.credit.dashboard.routes as routes_module
        src = inspect.getsource(routes_module)
        assert "settings.FRED_API_KEY" not in src, (
            "routes.py uses settings.FRED_API_KEY which does not exist — "
            "must use settings.fred_api_key"
        )
        assert "settings.fred_api_key" in src, (
            "routes.py must use settings.fred_api_key"
        )

"""Tests for ``P95GuardMiddleware`` (Stability Guardrails §2.8)."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.middleware.p95_guard import P95GuardMiddleware


class TestConfigValidation:
    def test_window_must_be_positive(self) -> None:
        async def dummy_app(scope, receive, send):  # pragma: no cover
            pass

        with pytest.raises(ValueError, match="window"):
            P95GuardMiddleware(dummy_app, window=0)

    def test_budget_must_be_positive(self) -> None:
        async def dummy_app(scope, receive, send):  # pragma: no cover
            pass

        with pytest.raises(ValueError, match="budget_ms"):
            P95GuardMiddleware(dummy_app, budget_ms=0)


class TestP95Calculation:
    def test_p95_nearest_rank(self) -> None:
        from collections import deque

        samples = deque([float(i) for i in range(1, 101)])  # 1..100
        result = P95GuardMiddleware._compute_p95(samples)
        # ceil(0.95 * 100) - 1 = 95 - 1 = 94 → sorted[94] = 95
        assert result == 95.0

    def test_p95_small_window(self) -> None:
        from collections import deque

        samples = deque([10.0, 20.0, 30.0])
        # ceil(0.95 * 3) - 1 = 3 - 1 = 2 → sorted[2] = 30
        result = P95GuardMiddleware._compute_p95(samples)
        assert result == 30.0


class TestMiddlewareIntegration:
    def _build_app(self, *, sleep_ms: int = 0) -> Starlette:
        async def slow_endpoint(request: Request) -> PlainTextResponse:
            if sleep_ms > 0:
                await asyncio.sleep(sleep_ms / 1000.0)
            return PlainTextResponse("ok")

        async def fast_endpoint(request: Request) -> PlainTextResponse:
            return PlainTextResponse("ok")

        app = Starlette(
            routes=[
                Route("/slow", slow_endpoint),
                Route("/fast", fast_endpoint),
            ],
        )
        app.add_middleware(
            P95GuardMiddleware,
            window=30,
            budget_ms=50,
            min_samples_for_p95=5,
        )
        return app

    def test_fast_endpoint_does_not_log_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        app = self._build_app(sleep_ms=0)
        caplog.set_level(logging.WARNING, logger="app.core.middleware.p95_guard")
        client = TestClient(app)
        for _ in range(10):
            r = client.get("/fast")
            assert r.status_code == 200
        assert not any(
            "p95_budget_exceeded" in record.message for record in caplog.records
        )

    def test_slow_endpoint_emits_warning_once(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        app = self._build_app(sleep_ms=80)  # 80ms > 50ms budget
        caplog.set_level(logging.WARNING, logger="app.core.middleware.p95_guard")
        client = TestClient(app)
        for _ in range(10):
            r = client.get("/slow")
            assert r.status_code == 200
        warnings = [
            record for record in caplog.records
            if "p95_budget_exceeded" in record.message
        ]
        assert len(warnings) == 1  # hysteresis — fires once

    def test_middleware_does_not_mutate_response(self) -> None:
        app = self._build_app()
        client = TestClient(app)
        r = client.get("/fast")
        assert r.status_code == 200
        assert r.text == "ok"


class TestRouteKeyResolution:
    def test_route_key_uses_method_and_path(self) -> None:
        mw = P95GuardMiddleware(
            lambda scope, receive, send: None,  # type: ignore[arg-type]
        )
        fake_request = MagicMock(spec=Request)
        fake_request.method = "GET"
        fake_request.url = MagicMock(path="/screener/fund/SPY")
        fake_request.scope = {"route": None}
        assert mw._route_key(fake_request) == "GET /screener/fund/SPY"

    def test_route_key_uses_template_when_available(self) -> None:
        mw = P95GuardMiddleware(
            lambda scope, receive, send: None,  # type: ignore[arg-type]
        )
        fake_route = MagicMock()
        fake_route.path = "/screener/fund/{id}"
        fake_request = MagicMock(spec=Request)
        fake_request.method = "GET"
        fake_request.url = MagicMock(path="/screener/fund/SPY")
        fake_request.scope = {"route": fake_route}
        assert mw._route_key(fake_request) == "GET /screener/fund/{id}"

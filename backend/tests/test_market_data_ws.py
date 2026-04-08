"""Tests for Market Data WebSocket endpoint + JWT authentication.

Covers:
  - WebSocket connection with valid dev token → accepted
  - WebSocket connection without token → closed 1008
  - WebSocket connection with invalid token → closed 1008
  - Subscribe/unsubscribe protocol
  - Ping/pong heartbeat
  - Price tick broadcast via ConnectionManager (orjson bytes)
  - Per-ticker channel subscription lifecycle
  - Batch publish pipeline
  - Dashboard snapshot REST endpoint (auth required)
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import orjson
import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.config.settings import settings
from app.core.ws.manager import ConnectionManager
from app.main import app
from tests.conftest import DEV_ACTOR_HEADER

# Resolve the dev token from settings so local .env overrides (non-default
# tokens) still match the WebSocket auth bypass. Tests previously hardcoded
# "dev-token-change-me" which broke as soon as DEV_TOKEN was set in .env.
_DEV_TOKEN = settings.dev_token
_WS_URL = f"/api/v1/market-data/live/ws?token={_DEV_TOKEN}"

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def test_client():
    """Sync test client for WebSocket testing (starlette TestClient).

    Initializes ws_manager and tiingo_bridge directly on app.state since
    TestClient does not run the FastAPI lifespan in synchronous mode.
    """
    if not hasattr(app.state, "ws_manager"):
        app.state.ws_manager = ConnectionManager()
    if not hasattr(app.state, "tiingo_bridge"):
        from app.core.ws.tiingo_bridge import TiingoStreamBridge

        app.state.tiingo_bridge = TiingoStreamBridge()
    return TestClient(app)


@pytest.fixture
async def async_client():
    """Async HTTP client for REST endpoint testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── WebSocket Auth Tests ────────────────────────────────────


def test_ws_rejects_missing_token(test_client: TestClient):
    """WebSocket without token query param → close 1008."""
    with pytest.raises(WebSocketDisconnect):
        with test_client.websocket_connect("/api/v1/market-data/live/ws"):
            pass  # Should not reach here


def test_ws_accepts_dev_token(test_client: TestClient):
    """WebSocket with valid dev token → connection accepted."""
    with test_client.websocket_connect(
        _WS_URL
    ) as ws:
        # Should receive initial subscribed message (orjson bytes)
        raw = ws.receive_bytes()
        msg = orjson.loads(raw)
        assert msg["type"] == "subscribed"
        assert msg["data"]["message"] == "Connected"


def test_ws_subscribe_protocol(test_client: TestClient):
    """Client can subscribe to tickers and receive confirmation."""
    with test_client.websocket_connect(
        _WS_URL
    ) as ws:
        # Consume initial message
        ws.receive_bytes()

        # Subscribe to tickers
        ws.send_json({"action": "subscribe", "tickers": ["SPY", "QQQ"]})
        raw = ws.receive_bytes()
        msg = orjson.loads(raw)
        assert msg["type"] == "subscribed"
        assert set(msg["data"]["tickers"]) == {"SPY", "QQQ"}


def test_ws_unsubscribe_protocol(test_client: TestClient):
    """Client can unsubscribe from tickers."""
    with test_client.websocket_connect(
        _WS_URL
    ) as ws:
        ws.receive_bytes()  # initial

        # Subscribe
        ws.send_json({"action": "subscribe", "tickers": ["SPY", "QQQ", "IWM"]})
        ws.receive_bytes()

        # Unsubscribe from one
        ws.send_json({"action": "unsubscribe", "tickers": ["QQQ"]})
        raw = ws.receive_bytes()
        msg = orjson.loads(raw)
        assert msg["type"] == "subscribed"
        assert "QQQ" not in msg["data"]["tickers"]
        assert "SPY" in msg["data"]["tickers"]
        assert "IWM" in msg["data"]["tickers"]


def test_ws_ping_pong(test_client: TestClient):
    """Client ping → server pong."""
    with test_client.websocket_connect(
        _WS_URL
    ) as ws:
        ws.receive_bytes()  # initial

        ws.send_json({"action": "ping"})
        raw = ws.receive_bytes()
        msg = orjson.loads(raw)
        assert msg["type"] == "pong"


def test_ws_invalid_json(test_client: TestClient):
    """Sending invalid JSON → error message (not disconnect)."""
    with test_client.websocket_connect(
        _WS_URL
    ) as ws:
        ws.receive_bytes()  # initial

        ws.send_text("not-json{{{")
        raw = ws.receive_bytes()
        msg = orjson.loads(raw)
        assert msg["type"] == "error"
        assert "Invalid JSON" in msg["data"]["message"]


def test_ws_unknown_action(test_client: TestClient):
    """Sending unknown action → error message."""
    with test_client.websocket_connect(
        _WS_URL
    ) as ws:
        ws.receive_bytes()  # initial

        ws.send_json({"action": "foobar"})
        raw = ws.receive_bytes()
        msg = orjson.loads(raw)
        assert msg["type"] == "error"
        assert "Unknown action" in msg["data"]["message"]


def test_ws_subscribe_normalizes_tickers(test_client: TestClient):
    """Tickers are normalized to uppercase."""
    with test_client.websocket_connect(
        _WS_URL
    ) as ws:
        ws.receive_bytes()  # initial

        ws.send_json({"action": "subscribe", "tickers": ["spy", "qqq"]})
        raw = ws.receive_bytes()
        msg = orjson.loads(raw)
        assert set(msg["data"]["tickers"]) == {"SPY", "QQQ"}


# ── ConnectionManager Unit Tests ────────────────────────────


def _make_mock_ws() -> AsyncMock:
    """Build an AsyncMock that satisfies starlette's WebSocket surface
    well enough for ``ConnectionManager.accept()`` to attach it to the
    rate-limited broadcaster.

    The bounded outbound channel reads from ``send_bytes``; ``accept``
    is awaited by the manager before attach.
    """
    ws = AsyncMock()
    ws.accept = AsyncMock()
    ws.send_bytes = AsyncMock()
    return ws


async def _flush_drain_loops() -> None:
    """Yield to the event loop a few times so per-connection drain
    tasks can pick up queued payloads from the broadcaster.

    Fan-out via ``BoundedOutboundChannel.offer()`` is non-blocking and
    only sets a wakeup ``Event`` — the actual ``ws.send_bytes`` call
    runs on the drain task. Tests that observe ``send_bytes`` need to
    let the loop run after the offer.
    """
    import asyncio as _asyncio
    for _ in range(5):
        await _asyncio.sleep(0)


@pytest.mark.asyncio
async def test_connection_manager_broadcast():
    """ConnectionManager broadcasts price ticks to subscribed clients only."""
    manager = ConnectionManager()
    await manager.start()

    from app.core.security.clerk_auth import Actor

    actor = Actor(actor_id="test", name="Test", email="t@t.com")

    ws1 = _make_mock_ws()
    ws2 = _make_mock_ws()

    conn1 = await manager.accept(ws1, actor)
    conn2 = await manager.accept(ws2, actor)

    manager.update_subscriptions(conn1.conn_id, {"SPY", "QQQ"})
    manager.update_subscriptions(conn2.conn_id, {"IWM"})

    try:
        # Broadcast SPY tick — only ws1 should receive
        tick = {"ticker": "SPY", "price": 450.0, "timestamp": "2026-04-05T12:00:00Z"}
        await manager.broadcast_to_subscribers(tick)
        await _flush_drain_loops()

        ws1.send_bytes.assert_called_once()
        # Verify the payload is valid orjson
        sent = orjson.loads(ws1.send_bytes.call_args[0][0])
        assert sent["ticker"] == "SPY"
        assert sent["price"] == 450.0
        ws2.send_bytes.assert_not_called()
    finally:
        await manager.shutdown()


@pytest.mark.asyncio
async def test_connection_manager_disconnect_removes_subscriptions():
    """``disconnect(conn_id)`` removes the connection and tears down
    its ticker subscriptions, stopping any orphaned channel listeners.
    """
    manager = ConnectionManager()
    await manager.start()

    from app.core.security.clerk_auth import Actor

    actor = Actor(actor_id="test", name="Test", email="t@t.com")
    ws1 = _make_mock_ws()
    conn = await manager.accept(ws1, actor)
    manager.update_subscriptions(conn.conn_id, {"SPY"})

    assert manager.active_count == 1
    assert "SPY" in manager._ticker_subs

    await manager.disconnect(conn.conn_id)

    assert manager.active_count == 0
    assert "SPY" not in manager._ticker_subs

    await manager.shutdown()


@pytest.mark.asyncio
async def test_connection_manager_per_ticker_subscriptions():
    """update_subscriptions tracks per-ticker subscriber sets."""
    manager = ConnectionManager()
    await manager.start()

    from app.core.security.clerk_auth import Actor

    actor = Actor(actor_id="test", name="Test", email="t@t.com")
    ws1 = _make_mock_ws()
    conn = await manager.accept(ws1, actor)

    # Subscribe to SPY and QQQ
    manager.update_subscriptions(conn.conn_id, {"SPY", "QQQ"})

    assert "SPY" in manager._ticker_subs
    assert "QQQ" in manager._ticker_subs
    assert conn.conn_id in manager._ticker_subs["SPY"]
    assert conn.conn_id in manager._ticker_subs["QQQ"]
    # Channel tasks should be started
    assert "SPY" in manager._channel_tasks
    assert "QQQ" in manager._channel_tasks

    # Unsubscribe from QQQ
    manager.update_subscriptions(conn.conn_id, {"SPY"})
    assert "QQQ" not in manager._ticker_subs
    assert "SPY" in manager._ticker_subs

    # Cleanup
    await manager.shutdown()


@pytest.mark.asyncio
async def test_connection_manager_shutdown():
    """shutdown() cancels all channel listeners and detaches connections."""
    manager = ConnectionManager()
    await manager.start()

    from app.core.security.clerk_auth import Actor

    actor = Actor(actor_id="test", name="Test", email="t@t.com")
    ws1 = _make_mock_ws()
    conn = await manager.accept(ws1, actor)
    manager.update_subscriptions(conn.conn_id, {"SPY", "QQQ", "IWM"})

    assert manager.active_channels == 3

    await manager.shutdown()

    assert manager.active_channels == 0
    assert manager.active_count == 0


@pytest.mark.asyncio
async def test_connection_manager_uses_unique_connection_ids():
    """Each accepted connection gets a fresh ConnectionId — id(ws)
    collisions across accept/disconnect cycles cannot cause cross-talk.
    """
    manager = ConnectionManager()
    await manager.start()

    from app.core.security.clerk_auth import Actor

    actor = Actor(actor_id="test", name="Test", email="t@t.com")

    seen_ids: set = set()
    for _ in range(5):
        ws = _make_mock_ws()
        conn = await manager.accept(ws, actor)
        assert conn.conn_id not in seen_ids
        seen_ids.add(conn.conn_id)
        await manager.disconnect(conn.conn_id)

    await manager.shutdown()


# ── REST Dashboard Snapshot Tests ───────────────────────────


@pytest.mark.asyncio
async def test_dashboard_snapshot_requires_auth(async_client: AsyncClient):
    """Dashboard snapshot endpoint requires authentication."""
    resp = await async_client.get("/api/v1/market-data/dashboard-snapshot")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_dashboard_snapshot_with_auth(async_client: AsyncClient):
    """Dashboard snapshot returns data with valid auth."""
    resp = await async_client.get(
        "/api/v1/market-data/dashboard-snapshot",
        headers=DEV_ACTOR_HEADER,
    )
    # May be 200 with empty holdings or 200 with data, depending on DB state
    assert resp.status_code == 200
    data = resp.json()
    assert "holdings" in data
    assert "total_aum" in data
    assert "as_of" in data
    assert isinstance(data["holdings"], list)

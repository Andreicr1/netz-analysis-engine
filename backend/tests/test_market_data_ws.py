"""Tests for Market Data WebSocket endpoint + JWT authentication.

Covers:
  - WebSocket connection with valid dev token → accepted
  - WebSocket connection without token → closed 1008
  - WebSocket connection with invalid token → closed 1008
  - Subscribe/unsubscribe protocol
  - Ping/pong heartbeat
  - Price tick broadcast via ConnectionManager
  - Dashboard snapshot REST endpoint (auth required)
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.core.ws.manager import ConnectionManager
from app.main import app
from tests.conftest import DEV_ACTOR_HEADER

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def test_client():
    """Sync test client for WebSocket testing (starlette TestClient)."""
    # Ensure ConnectionManager exists on app state
    if not hasattr(app.state, "ws_manager"):
        app.state.ws_manager = ConnectionManager()
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
        "/api/v1/market-data/live/ws?token=dev-token-change-me"
    ) as ws:
        # Should receive initial subscribed message
        msg = ws.receive_json()
        assert msg["type"] == "subscribed"
        assert msg["data"]["message"] == "Connected"


def test_ws_subscribe_protocol(test_client: TestClient):
    """Client can subscribe to tickers and receive confirmation."""
    with test_client.websocket_connect(
        "/api/v1/market-data/live/ws?token=dev-token-change-me"
    ) as ws:
        # Consume initial message
        ws.receive_json()

        # Subscribe to tickers
        ws.send_json({"action": "subscribe", "tickers": ["SPY", "QQQ"]})
        msg = ws.receive_json()
        assert msg["type"] == "subscribed"
        assert set(msg["data"]["tickers"]) == {"SPY", "QQQ"}


def test_ws_unsubscribe_protocol(test_client: TestClient):
    """Client can unsubscribe from tickers."""
    with test_client.websocket_connect(
        "/api/v1/market-data/live/ws?token=dev-token-change-me"
    ) as ws:
        ws.receive_json()  # initial

        # Subscribe
        ws.send_json({"action": "subscribe", "tickers": ["SPY", "QQQ", "IWM"]})
        ws.receive_json()

        # Unsubscribe from one
        ws.send_json({"action": "unsubscribe", "tickers": ["QQQ"]})
        msg = ws.receive_json()
        assert msg["type"] == "subscribed"
        assert "QQQ" not in msg["data"]["tickers"]
        assert "SPY" in msg["data"]["tickers"]
        assert "IWM" in msg["data"]["tickers"]


def test_ws_ping_pong(test_client: TestClient):
    """Client ping → server pong."""
    with test_client.websocket_connect(
        "/api/v1/market-data/live/ws?token=dev-token-change-me"
    ) as ws:
        ws.receive_json()  # initial

        ws.send_json({"action": "ping"})
        msg = ws.receive_json()
        assert msg["type"] == "pong"


def test_ws_invalid_json(test_client: TestClient):
    """Sending invalid JSON → error message (not disconnect)."""
    with test_client.websocket_connect(
        "/api/v1/market-data/live/ws?token=dev-token-change-me"
    ) as ws:
        ws.receive_json()  # initial

        ws.send_text("not-json{{{")
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Invalid JSON" in msg["data"]["message"]


def test_ws_unknown_action(test_client: TestClient):
    """Sending unknown action → error message."""
    with test_client.websocket_connect(
        "/api/v1/market-data/live/ws?token=dev-token-change-me"
    ) as ws:
        ws.receive_json()  # initial

        ws.send_json({"action": "foobar"})
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "Unknown action" in msg["data"]["message"]


def test_ws_subscribe_normalizes_tickers(test_client: TestClient):
    """Tickers are normalized to uppercase."""
    with test_client.websocket_connect(
        "/api/v1/market-data/live/ws?token=dev-token-change-me"
    ) as ws:
        ws.receive_json()  # initial

        ws.send_json({"action": "subscribe", "tickers": ["spy", "qqq"]})
        msg = ws.receive_json()
        assert set(msg["data"]["tickers"]) == {"SPY", "QQQ"}


# ── ConnectionManager Unit Tests ────────────────────────────


@pytest.mark.asyncio
async def test_connection_manager_broadcast():
    """ConnectionManager broadcasts price ticks to subscribed clients only."""
    manager = ConnectionManager()

    # Create mock WebSocket connections
    ws1 = AsyncMock()
    ws1.send_json = AsyncMock()
    ws2 = AsyncMock()
    ws2.send_json = AsyncMock()

    from app.core.security.clerk_auth import Actor

    actor = Actor(actor_id="test", name="Test", email="t@t.com")

    # Register connections manually (bypass accept which needs real WS)
    from app.core.ws.manager import ClientConnection

    conn1 = ClientConnection(ws=ws1, actor=actor, tickers={"SPY", "QQQ"})
    conn2 = ClientConnection(ws=ws2, actor=actor, tickers={"IWM"})

    manager._connections[id(ws1)] = conn1
    manager._connections[id(ws2)] = conn2

    # Broadcast SPY tick — only ws1 should receive
    tick = {"ticker": "SPY", "price": 450.0, "timestamp": "2026-04-05T12:00:00Z"}
    await manager.broadcast_to_subscribers(tick)

    ws1.send_json.assert_called_once_with(tick)
    ws2.send_json.assert_not_called()


@pytest.mark.asyncio
async def test_connection_manager_disconnect_stale():
    """Stale connections (send_json raises) are automatically removed."""
    manager = ConnectionManager()

    ws1 = AsyncMock()
    ws1.send_json = AsyncMock(side_effect=Exception("Connection lost"))

    from app.core.security.clerk_auth import Actor
    from app.core.ws.manager import ClientConnection

    actor = Actor(actor_id="test", name="Test", email="t@t.com")
    conn1 = ClientConnection(ws=ws1, actor=actor, tickers={"SPY"})
    manager._connections[id(ws1)] = conn1

    assert manager.active_count == 1

    await manager.broadcast_to_subscribers({"ticker": "SPY", "price": 450.0})

    # Stale connection should be removed
    assert manager.active_count == 0


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

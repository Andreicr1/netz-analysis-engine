"""Test configuration — Netz Analysis Engine.

Uses httpx AsyncClient + ASGITransport for in-process async testing.
Tests run against real PostgreSQL (not SQLite — asyncpg requires PG).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


DEV_ACTOR_HEADER = {
    "X-DEV-ACTOR": '{"actor_id": "test-user", "roles": ["ADMIN"], "fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}'
}

"""Test configuration — Netz Analysis Engine.

Uses httpx AsyncClient + ASGITransport for in-process async testing.
Tests run against real PostgreSQL (not SQLite — asyncpg requires PG).
"""

from __future__ import annotations

import os

# Disable Redis-backed rate-limit middleware during tests. Every test reuses
# the same dev org_id (_TEAM_HEADER / _ADMIN_HEADER / DEV_ACTOR_HEADER), so the
# compute-tier 10 RPM ceiling (settings.rate_limit_compute_rpm) is hit within
# seconds when the full suite runs in CI — causing tests like
# test_preview_upstream_failure_returns_422 to receive 429 before their
# upstream-failure mock can run. Production gates remain intact via real env.
# Must run BEFORE any `from app.main import app` import path executes.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client():
    """Async HTTP client for testing FastAPI endpoints."""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def _rebind_engine_for_integration(request):
    """Dispose the asyncpg pool before every @pytest.mark.integration test.

    Some integration tests in this suite (and a few non-integration tests
    they depend on indirectly) drive their async setup with `asyncio.run`
    or `loop.run_until_complete`, each of which opens a private event loop,
    causes the SQLAlchemy module-level engine to bind its asyncpg pool to
    that loop, and then closes the loop. Subsequent integration tests that
    use the canonical pytest-asyncio session loop then inherit an orphaned
    pool and fail with "Future attached to a different loop".

    Calling `engine.dispose()` immediately before the test runs (in the
    session loop) tears down the orphan and lets the test's first DB call
    lazily build a fresh pool on the loop that is actually about to use it.

    Scope=function and gated on the integration marker keeps the cost
    bounded — dispose() is millisecond-cheap and the bonus only fires for
    the ~37 integration tests, not the 4900+ unit tests.
    """
    if request.node.get_closest_marker("integration"):
        from app.core.db.engine import engine

        await engine.dispose()
    yield


@pytest.fixture(autouse=True, scope="session")
async def _dispose_engine_around_session():
    """Re-bind the asyncpg pool to the pytest session loop and dispose at end.

    The SQLAlchemy engine is created at import time (module-level singleton),
    so its asyncpg connection pool is initially bound to whichever loop ran
    the import. Several integration tests in this suite use
    asyncio.run / new_event_loop / run_until_complete, which can leave the
    pool attached to a now-closed auxiliary loop. The dispose() at session
    start runs inside the pytest-asyncio session loop, tearing down any
    orphaned pool so the first real query lazily creates a fresh pool on
    the session loop. Without this, the first test that hits the DB after
    a different-loop usage gets "Future attached to a different loop" or
    "Event loop is closed".
    """
    from app.core.db.engine import engine

    await engine.dispose()
    yield
    await engine.dispose()


DEV_ACTOR_HEADER = {
    "X-DEV-ACTOR": '{"actor_id": "test-user", "roles": ["ADMIN"], "fund_ids": [], "org_id": "00000000-0000-0000-0000-000000000001"}',
}

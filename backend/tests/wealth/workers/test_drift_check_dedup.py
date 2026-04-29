"""Tests for PR-Q128: RebalanceEvent dedupe in drift_check worker.

Validates:
  C-04: drift_check does not create duplicate pending drift_rebalance
        events when a pending event already exists for the same profile.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.workers import drift_check as mod

# ── Helpers ────────────────────────────────────────────────────────────


class _FakeResult:
    """Minimal result proxy for mocked session.execute()."""

    def __init__(self, scalar_value=None):
        self._scalar = scalar_value

    def scalar(self):
        return self._scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    """Fake async session that tracks execute/commit calls.

    Extends the base pattern from test_drift_check_rls_and_lock with
    support for simulating existing pending RebalanceEvent rows.
    """

    def __init__(
        self,
        *,
        lock_acquired: bool = True,
        pending_profiles: set[str] | None = None,
    ):
        self._lock_acquired = lock_acquired
        self._pending_profiles = pending_profiles or set()
        self.executed_sql: list[str] = []
        self.commits = 0

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed_sql.append(sql)

        if "set_config" in sql and "app.current_organization_id" in sql:
            return _FakeResult()

        if "pg_try_advisory_lock" in sql:
            return _FakeResult(scalar_value=self._lock_acquired)

        if "pg_advisory_unlock" in sql:
            return _FakeResult(scalar_value=True)

        if "vertical_config_defaults" in sql.lower():
            return _FakeResult(scalar_value=None)

        # Dedupe query: SELECT rebalance_events.event_id WHERE ...
        # ORM uses bind params, so extract them from the compiled statement.
        if "rebalance_events" in sql.lower() and "event_id" in sql.lower():
            try:
                compiled = stmt.compile()
                profile_val = compiled.params.get("profile_1")
            except Exception:
                profile_val = None
            if profile_val and profile_val in self._pending_profiles:
                return _FakeResult(scalar_value=uuid.uuid4())
            return _FakeResult(scalar_value=None)

        return _FakeResult()

    async def commit(self):
        self.commits += 1


def _make_session_factory(session: _FakeSession):
    """Build an async context manager factory that yields the given session."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


def _make_fake_report(*, rebalance: bool = False):
    """Build a minimal drift report mock."""
    report = MagicMock()
    report.overall_status = "ok"
    report.max_drift_pct = 0.05
    report.rebalance_recommended = rebalance
    report.estimated_turnover = 0.02
    report.maintenance_trigger = 0.05
    report.blocks = []
    return report


# ── Test: first run creates event (no existing pending) ──────────────


@pytest.mark.asyncio
async def test_drift_check_creates_event_when_none_pending():
    """C-04: When no pending drift_rebalance exists, event is created."""
    org_id = uuid.uuid4()
    session = _FakeSession(pending_profiles=set())

    report = _make_fake_report(rebalance=True)
    fake_event = MagicMock()
    fake_event.event_id = uuid.uuid4()

    mock_create = AsyncMock(return_value=fake_event)
    mock_audit = AsyncMock()

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(mod, "compute_drift", new_callable=AsyncMock, return_value=report),
        patch.object(mod, "create_system_rebalance_event", mock_create),
        patch.object(mod, "write_audit_event", mock_audit),
    ):
        result = await mod.run_drift_check(org_id)

    assert isinstance(result, dict)
    # All 3 profiles trigger because report.rebalance_recommended = True
    assert mock_create.call_count == len(mod.PROFILES)
    assert mock_audit.call_count == len(mod.PROFILES)


# ── Test: skip when pending event exists ─────────────────────────────


@pytest.mark.asyncio
async def test_drift_check_skips_when_pending_event_exists():
    """C-04: When a pending drift_rebalance exists, no new event is created."""
    org_id = uuid.uuid4()
    # All profiles have pending events
    session = _FakeSession(
        pending_profiles={"conservative", "moderate", "growth"},
    )

    report = _make_fake_report(rebalance=True)
    mock_create = AsyncMock()
    mock_audit = AsyncMock()

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(mod, "compute_drift", new_callable=AsyncMock, return_value=report),
        patch.object(mod, "create_system_rebalance_event", mock_create),
        patch.object(mod, "write_audit_event", mock_audit),
    ):
        result = await mod.run_drift_check(org_id)

    assert isinstance(result, dict)
    # No events should be created — all profiles already have pending events
    assert mock_create.call_count == 0
    assert mock_audit.call_count == 0
    # Commits still happen (one per profile for the skip path + config load)
    assert session.commits == len(mod.PROFILES)


# ── Test: mixed — some profiles pending, some not ────────────────────


@pytest.mark.asyncio
async def test_drift_check_mixed_pending_and_new():
    """C-04: Only profiles without pending events get new events."""
    org_id = uuid.uuid4()
    # Only 'conservative' has a pending event
    session = _FakeSession(pending_profiles={"conservative"})

    report = _make_fake_report(rebalance=True)
    fake_event = MagicMock()
    fake_event.event_id = uuid.uuid4()

    mock_create = AsyncMock(return_value=fake_event)
    mock_audit = AsyncMock()

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(mod, "compute_drift", new_callable=AsyncMock, return_value=report),
        patch.object(mod, "create_system_rebalance_event", mock_create),
        patch.object(mod, "write_audit_event", mock_audit),
    ):
        result = await mod.run_drift_check(org_id)

    assert isinstance(result, dict)
    # 'conservative' skipped, 'moderate' + 'growth' created
    assert mock_create.call_count == 2
    assert mock_audit.call_count == 2


# ── Test: no rebalance recommended → no dedupe query at all ──────────


@pytest.mark.asyncio
async def test_drift_check_no_dedupe_when_not_recommended():
    """No dedupe query issued when rebalance is not recommended."""
    org_id = uuid.uuid4()
    session = _FakeSession()

    report = _make_fake_report(rebalance=False)
    mock_create = AsyncMock()

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(mod, "compute_drift", new_callable=AsyncMock, return_value=report),
        patch.object(mod, "create_system_rebalance_event", mock_create),
    ):
        result = await mod.run_drift_check(org_id)

    assert isinstance(result, dict)
    assert mock_create.call_count == 0
    # No rebalance_events queries should appear
    rebalance_queries = [
        sql for sql in session.executed_sql
        if "rebalance_events" in sql.lower() and "event_id" in sql.lower()
    ]
    assert len(rebalance_queries) == 0


# ── Test: commit + RLS reset on skip path ────────────────────────────


@pytest.mark.asyncio
async def test_drift_check_commits_and_resets_rls_on_skip():
    """C-04: Skip path still commits and re-sets RLS context."""
    org_id = uuid.uuid4()
    session = _FakeSession(pending_profiles={"conservative", "moderate", "growth"})

    report = _make_fake_report(rebalance=True)

    rls_calls: list[uuid.UUID] = []
    original_set_rls = mod.set_rls_context

    async def tracking_set_rls(db, oid):
        rls_calls.append(oid)
        # Call through to the real function which does db.execute(...)
        return await original_set_rls(db, oid)

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(mod, "compute_drift", new_callable=AsyncMock, return_value=report),
        patch.object(mod, "create_system_rebalance_event", new_callable=AsyncMock),
        patch.object(mod, "write_audit_event", new_callable=AsyncMock),
        patch.object(mod, "set_rls_context", side_effect=tracking_set_rls),
    ):
        await mod.run_drift_check(org_id)

    # Initial RLS set + 3 profile iterations (skip path each does commit + RLS)
    # = 1 initial + 3 skip-path = 4 total RLS calls
    assert len(rls_calls) >= 4
    assert all(oid == org_id for oid in rls_calls)
    # 3 commits (one per profile skip path)
    assert session.commits == 3

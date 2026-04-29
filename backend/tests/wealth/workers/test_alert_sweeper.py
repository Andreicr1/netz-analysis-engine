"""Tests for alert_sweeper worker (PR-Q127, S11 C-03).

Validates:
  1. Expired alerts are dismissed (dismissed_at set, dismissed_by="system:alert_sweeper")
  2. Future auto_dismiss_at alerts are not touched
  3. Already-dismissed alerts are not re-dismissed
  4. Lock held → returns {"status": "skipped", "dismissed": 0}
  5. One audit event per expired alert
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.workers import alert_sweeper as mod

# ── Helpers ────────────────────────────────────────────────────────────


class _FakeResult:
    """Minimal result proxy for mocked session.execute()."""

    def __init__(self, scalar_value=None, scalars_value=None):
        self._scalar = scalar_value
        self._scalars_value = scalars_value

    def scalar(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._scalars_value or []


class _FakeSession:
    """Fake async session that tracks execute/commit calls."""

    def __init__(
        self,
        *,
        lock_acquired: bool = True,
        candidates: list | None = None,
    ):
        self._lock_acquired = lock_acquired
        self._candidates = candidates or []
        self.executed_sql: list[str] = []
        self.commits = 0
        self.rls_org_ids: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed_sql.append(sql)

        if "set_config" in sql and "app.current_organization_id" in sql:
            if params:
                self.rls_org_ids.append(params.get("oid", ""))
            return _FakeResult()

        if "pg_try_advisory_lock" in sql:
            return _FakeResult(scalar_value=self._lock_acquired)

        if "pg_advisory_unlock" in sql:
            return _FakeResult(scalar_value=True)

        # SELECT on portfolio_alerts — return candidates
        if "portfolio_alerts" in sql.lower() or "PortfolioAlert" in sql:
            return _FakeResult(scalars_value=self._candidates)

        return _FakeResult(scalars_value=self._candidates)

    async def commit(self):
        self.commits += 1

    async def flush(self):
        pass

    def add(self, obj):
        pass


def _make_session_factory(session: _FakeSession):
    """Build an async context manager factory that yields the given session."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


def _make_alert(
    *,
    auto_dismiss_at: datetime | None = None,
    dismissed_at: datetime | None = None,
    alert_id: uuid.UUID | None = None,
) -> MagicMock:
    """Build a minimal PortfolioAlert mock."""
    alert = MagicMock()
    alert.id = alert_id or uuid.uuid4()
    alert.auto_dismiss_at = auto_dismiss_at
    alert.dismissed_at = dismissed_at
    alert.dismissed_by = None
    alert.portfolio_id = uuid.uuid4()
    alert.alert_type = "drift"
    alert.severity = "warning"
    alert.title = "Test alert"
    return alert


# ── Test 1: dismisses expired alerts ───────────────────────────────


@pytest.mark.asyncio
async def test_alert_sweeper_dismisses_expired():
    """Alert with auto_dismiss_at in the past → dismissed_at set."""
    org_id = uuid.uuid4()
    past = datetime.now(UTC) - timedelta(hours=2)
    alert = _make_alert(auto_dismiss_at=past)
    session = _FakeSession(candidates=[alert])

    mock_write_audit = AsyncMock()

    with (
        patch.object(mod, "async_session_factory", _make_session_factory(session)),
        patch.object(mod, "write_audit_event", mock_write_audit),
    ):
        result = await mod.run_alert_sweeper(org_id)

    assert result["status"] == "completed"
    assert result["dismissed"] == 1
    assert alert.dismissed_at is not None
    assert alert.dismissed_by == "system:alert_sweeper"
    mock_write_audit.assert_called_once()


# ── Test 2: skips future auto_dismiss_at ───────────────────────────


@pytest.mark.asyncio
async def test_alert_sweeper_skips_future():
    """Alert with auto_dismiss_at in the future → not dismissed.

    The SELECT WHERE clause filters these out, so the session returns
    an empty candidate list.
    """
    org_id = uuid.uuid4()
    # No candidates returned (DB would filter future alerts)
    session = _FakeSession(candidates=[])

    mock_write_audit = AsyncMock()

    with (
        patch.object(mod, "async_session_factory", _make_session_factory(session)),
        patch.object(mod, "write_audit_event", mock_write_audit),
    ):
        result = await mod.run_alert_sweeper(org_id)

    assert result["status"] == "completed"
    assert result["dismissed"] == 0
    mock_write_audit.assert_not_called()


# ── Test 3: skips already-dismissed alerts ─────────────────────────


@pytest.mark.asyncio
async def test_alert_sweeper_skips_already_dismissed():
    """Alert with dismissed_at already set → not returned by SELECT.

    The WHERE clause uses dismissed_at IS NULL, so already-dismissed
    alerts are never in the candidate list.
    """
    org_id = uuid.uuid4()
    # No candidates returned (DB would filter already-dismissed alerts)
    session = _FakeSession(candidates=[])

    mock_write_audit = AsyncMock()

    with (
        patch.object(mod, "async_session_factory", _make_session_factory(session)),
        patch.object(mod, "write_audit_event", mock_write_audit),
    ):
        result = await mod.run_alert_sweeper(org_id)

    assert result["status"] == "completed"
    assert result["dismissed"] == 0
    mock_write_audit.assert_not_called()


# ── Test 4: lock held → skipped ────────────────────────────────────


@pytest.mark.asyncio
async def test_alert_sweeper_lock_held_returns_skipped():
    """Lock already held → returns skipped status, no unlock call."""
    org_id = uuid.uuid4()
    session = _FakeSession(lock_acquired=False)

    with patch.object(mod, "async_session_factory", _make_session_factory(session)):
        result = await mod.run_alert_sweeper(org_id)

    assert result["status"] == "skipped"
    assert result["dismissed"] == 0

    unlock_sqls = [
        sql for sql in session.executed_sql if "pg_advisory_unlock" in sql
    ]
    assert len(unlock_sqls) == 0, "Lock was never acquired — unlock must not be called"


# ── Test 5: one audit event per expired alert ──────────────────────


@pytest.mark.asyncio
async def test_alert_sweeper_writes_audit_per_alert():
    """3 expired alerts → 3 write_audit_event calls."""
    org_id = uuid.uuid4()
    past = datetime.now(UTC) - timedelta(hours=1)
    alerts = [_make_alert(auto_dismiss_at=past) for _ in range(3)]
    session = _FakeSession(candidates=alerts)

    mock_write_audit = AsyncMock()

    with (
        patch.object(mod, "async_session_factory", _make_session_factory(session)),
        patch.object(mod, "write_audit_event", mock_write_audit),
    ):
        result = await mod.run_alert_sweeper(org_id)

    assert result["status"] == "completed"
    assert result["dismissed"] == 3
    assert mock_write_audit.call_count == 3

    # Verify each call has the correct shape
    for call in mock_write_audit.call_args_list:
        _, kwargs = call
        assert kwargs["action"] == "portfolio_alert.auto_dismissed"
        assert kwargs["entity_type"] == "portfolio_alert"
        assert kwargs["actor_id"] == "system:alert_sweeper"
        assert kwargs["allow_global"] is False
        assert kwargs["before"] == {"dismissed_at": None}
        assert "dismissed_at" in kwargs["after"]
        assert kwargs["after"]["dismissed_by"] == "system:alert_sweeper"

    # All 3 alerts must have been mutated
    for alert in alerts:
        assert alert.dismissed_at is not None
        assert alert.dismissed_by == "system:alert_sweeper"

    # Commit must have been called exactly once (atomic)
    assert session.commits == 1

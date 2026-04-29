"""Tests for alert_sweeper worker (PR-Q127, S11 C-03).

Validates:
  1. Expired alerts are dismissed (dismissed_at set, dismissed_by="system:alert_sweeper")
  2. Future auto_dismiss_at alerts are not touched
  3. Already-dismissed alerts are not re-dismissed
  4. Lock held -> returns {"status": "skipped", "dismissed": 0}
  5. One audit event per expired alert
  6. xact lock released on DB exception (auto via rollback)
  7. Concurrent run blocked (second caller returns 0)
  8. No session-scoped lock orphan (no pg_advisory_unlock used)
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domains.wealth.workers import alert_sweeper as mod

# -- Helpers ----------------------------------------------------------------


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
        self.rollbacks = 0
        self.rls_org_ids: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed_sql.append(sql)
        self.last_params = params

        if "set_config" in sql and "app.current_organization_id" in sql:
            if params:
                self.rls_org_ids.append(params.get("oid", ""))
            return _FakeResult()

        if "pg_try_advisory_xact_lock" in sql:
            return _FakeResult(scalar_value=self._lock_acquired)

        # SELECT on portfolio_alerts -- return candidates
        if "portfolio_alerts" in sql.lower() or "PortfolioAlert" in sql:
            return _FakeResult(scalars_value=self._candidates)

        return _FakeResult(scalars_value=self._candidates)

    async def commit(self):
        self.commits += 1

    async def flush(self):
        pass

    async def rollback(self):
        self.rollbacks += 1

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


# -- Test 1: dismisses expired alerts --------------------------------------


@pytest.mark.asyncio
async def test_alert_sweeper_dismisses_expired():
    """Alert with auto_dismiss_at in the past -> dismissed_at set."""
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


# -- Test 2: skips future auto_dismiss_at ----------------------------------


@pytest.mark.asyncio
async def test_alert_sweeper_skips_future():
    """Alert with auto_dismiss_at in the future -> not dismissed.

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


# -- Test 3: skips already-dismissed alerts --------------------------------


@pytest.mark.asyncio
async def test_alert_sweeper_skips_already_dismissed():
    """Alert with dismissed_at already set -> not returned by SELECT.

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


# -- Test 4: lock held -> skipped -----------------------------------------


@pytest.mark.asyncio
async def test_alert_sweeper_lock_held_returns_skipped():
    """Lock already held -> returns skipped status."""
    org_id = uuid.uuid4()
    session = _FakeSession(lock_acquired=False)

    with patch.object(mod, "async_session_factory", _make_session_factory(session)):
        result = await mod.run_alert_sweeper(org_id)

    assert result["status"] == "skipped"
    assert result["dismissed"] == 0

    # No unlock calls (xact lock, not session lock)
    unlock_sqls = [
        sql for sql in session.executed_sql if "pg_advisory_unlock" in sql
    ]
    assert len(unlock_sqls) == 0, "xact lock auto-releases -- no manual unlock"


# -- Test 5: one audit event per expired alert -----------------------------


@pytest.mark.asyncio
async def test_alert_sweeper_writes_audit_per_alert():
    """3 expired alerts -> 3 write_audit_event calls."""
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


# -- Test 6: xact lock released on DB exception ---------------------------


@pytest.mark.asyncio
async def test_alert_sweeper_lock_released_on_db_exception():
    """P1 fix: If write_audit_event raises, the exception propagates and
    the async context manager exits -- xact lock is auto-released on
    session close/rollback. No manual unlock needed."""
    org_id = uuid.uuid4()
    past = datetime.now(UTC) - timedelta(hours=2)
    alert = _make_alert(auto_dismiss_at=past)
    session = _FakeSession(candidates=[alert])

    # Make write_audit_event raise
    mock_audit_bomb = AsyncMock(side_effect=RuntimeError("audit write failed"))

    with (
        patch.object(mod, "async_session_factory", _make_session_factory(session)),
        patch.object(mod, "write_audit_event", mock_audit_bomb),
    ):
        with pytest.raises(RuntimeError, match="audit write failed"):
            await mod.run_alert_sweeper(org_id)

    # No manual unlock call -- xact lock auto-releases
    unlock_sqls = [
        sql for sql in session.executed_sql if "pg_advisory_unlock" in sql
    ]
    assert len(unlock_sqls) == 0, (
        "pg_try_advisory_xact_lock auto-releases on commit/rollback -- "
        "no manual pg_advisory_unlock should be called"
    )

    # Commit must NOT have been called (exception before commit)
    assert session.commits == 0


# -- Test 7: concurrent runs blocked (second returns 0) -------------------


@pytest.mark.asyncio
async def test_alert_sweeper_concurrent_runs_blocked():
    """Second concurrent run gets lock_acquired=False, returns 0 dismissed."""
    org_id = uuid.uuid4()

    # First run acquires lock successfully
    session1 = _FakeSession(lock_acquired=True, candidates=[])
    with patch.object(mod, "async_session_factory", _make_session_factory(session1)):
        result1 = await mod.run_alert_sweeper(org_id)
    assert result1["status"] == "completed"

    # Second run finds lock held
    session2 = _FakeSession(lock_acquired=False)
    with patch.object(mod, "async_session_factory", _make_session_factory(session2)):
        result2 = await mod.run_alert_sweeper(org_id)
    assert result2["status"] == "skipped"
    assert result2["dismissed"] == 0


# -- Test 8: no session lock orphan (no pg_advisory_unlock used) -----------


@pytest.mark.asyncio
async def test_alert_sweeper_no_session_lock_orphan():
    """Post-run: verify no advisory lock operations use session-scoped
    pg_advisory_lock/pg_advisory_unlock -- only xact variant used."""
    org_id = uuid.uuid4()
    past = datetime.now(UTC) - timedelta(hours=1)
    alert = _make_alert(auto_dismiss_at=past)
    session = _FakeSession(candidates=[alert])

    mock_write_audit = AsyncMock()

    with (
        patch.object(mod, "async_session_factory", _make_session_factory(session)),
        patch.object(mod, "write_audit_event", mock_write_audit),
    ):
        await mod.run_alert_sweeper(org_id)

    # Collect all lock-related SQL
    lock_sqls = [
        sql
        for sql in session.executed_sql
        if "advisory" in sql.lower()
    ]

    # Must only contain xact variant
    for sql in lock_sqls:
        assert "xact_lock" in sql, (
            f"Expected pg_try_advisory_xact_lock, got: {sql}"
        )

    # No session-scoped lock/unlock
    session_lock_sqls = [
        sql
        for sql in session.executed_sql
        if "pg_advisory_lock(" in sql or "pg_advisory_unlock" in sql
    ]
    assert len(session_lock_sqls) == 0, (
        f"Session-scoped advisory lock/unlock detected -- must use xact variant: "
        f"{session_lock_sqls}"
    )


# -- Test 9: alert_sweeper registered in dispatcher -------------------------


def test_alert_sweeper_registered_in_dispatcher():
    """alert_sweeper must be present in get_worker_registry with correct metadata."""
    from app.domains.admin.routes.worker_registry import get_worker_registry

    registry = get_worker_registry()
    assert "alert_sweeper" in registry, (
        "alert_sweeper not found in worker registry — it will never be invoked by scheduler"
    )

    coro_fn, scope_type, timeout = registry["alert_sweeper"]
    assert coro_fn is mod.run_alert_sweeper
    assert scope_type == "org", "alert_sweeper must be org-scoped"
    assert timeout > 0


# -- Test 10: lock scoped per org -------------------------------------------


@pytest.mark.asyncio
async def test_alert_sweeper_lock_scoped_per_org():
    """Two different orgs can acquire lock independently; same org blocks."""
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()

    # Both orgs acquire lock successfully (independent sessions)
    session_a = _FakeSession(lock_acquired=True, candidates=[])
    with patch.object(mod, "async_session_factory", _make_session_factory(session_a)):
        result_a = await mod.run_alert_sweeper(org_a)
    assert result_a["status"] == "completed"

    session_b = _FakeSession(lock_acquired=True, candidates=[])
    with patch.object(mod, "async_session_factory", _make_session_factory(session_b)):
        result_b = await mod.run_alert_sweeper(org_b)
    assert result_b["status"] == "completed"

    # Verify lock SQL uses two-arg form (class, key) not single-arg
    for session in (session_a, session_b):
        lock_sqls = [
            sql for sql in session.executed_sql
            if "pg_try_advisory_xact_lock" in sql
        ]
        assert len(lock_sqls) == 1
        assert "lock_class" in lock_sqls[0] or ":lock_class" in lock_sqls[0], (
            "Lock must use two-arg form pg_try_advisory_xact_lock(:lock_class, :lock_obj)"
        )

    # Same org: second run blocked
    session_blocked = _FakeSession(lock_acquired=False)
    with patch.object(mod, "async_session_factory", _make_session_factory(session_blocked)):
        result_blocked = await mod.run_alert_sweeper(org_a)
    assert result_blocked["status"] == "skipped"
    assert result_blocked["dismissed"] == 0


# -- Test 11: different orgs produce different lock keys --------------------


def test_org_lock_key_deterministic_and_distinct():
    """_org_lock_key produces distinct, deterministic keys for distinct orgs."""
    org_a = uuid.UUID("00000000-0000-0000-0000-000000000001")
    org_b = uuid.UUID("00000000-0000-0000-0000-000000000002")

    key_a = mod._org_lock_key(org_a)
    key_b = mod._org_lock_key(org_b)

    assert key_a == mod._org_lock_key(org_a), "must be deterministic"
    assert key_a != key_b, "different orgs must produce different lock keys"
    assert 0 <= key_a <= 0x7FFFFFFF, "must fit in int4 range"
    assert 0 <= key_b <= 0x7FFFFFFF, "must fit in int4 range"

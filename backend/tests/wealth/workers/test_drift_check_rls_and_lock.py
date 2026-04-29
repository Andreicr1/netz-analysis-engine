"""Tests for drift_check RLS context and advisory lock safety (PR-Q97).

Validates:
  C-05: run_drift_check requires org_id and sets RLS context
  C-06: Advisory lock released on cancellation (outer try/finally)
"""

from __future__ import annotations

import asyncio
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
    """Fake async session that tracks execute/commit calls."""

    def __init__(self, *, lock_acquired: bool = True, config_error: bool = False):
        self._lock_acquired = lock_acquired
        self._config_error = config_error
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

        if "vertical_config_defaults" in sql.lower():
            if self._config_error:
                raise RuntimeError("Simulated config load failure")
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
    report.max_drift_pct = 0.01
    report.rebalance_recommended = rebalance
    report.estimated_turnover = 0.005
    report.maintenance_trigger = 0.05
    report.blocks = []
    return report


# ── Test: signature requires org_id ────────────────────────────────────


@pytest.mark.asyncio
async def test_drift_check_requires_org_id():
    """C-05: run_drift_check() without org_id raises TypeError."""
    with pytest.raises(TypeError):
        await mod.run_drift_check()  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_drift_check_accepts_org_id():
    """C-05: run_drift_check(org_id=...) executes without error."""
    org_id = uuid.uuid4()
    session = _FakeSession()

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(mod, "compute_drift", new_callable=AsyncMock, return_value=_make_fake_report()),
    ):
        result = await mod.run_drift_check(org_id)

    assert isinstance(result, dict)


# ── Test: RLS context set before queries ───────────────────────────────


@pytest.mark.asyncio
async def test_drift_check_sets_rls_context():
    """C-05: set_rls_context is called with org_id before any data query."""
    org_id = uuid.uuid4()
    session = _FakeSession()

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(mod, "compute_drift", new_callable=AsyncMock, return_value=_make_fake_report()),
    ):
        await mod.run_drift_check(org_id)

    # RLS context must have been set at least once (before lock + after each commit)
    assert len(session.rls_org_ids) >= 1
    assert all(oid == str(org_id) for oid in session.rls_org_ids)

    # RLS set_config must come BEFORE pg_try_advisory_lock
    set_config_indices = [
        i for i, sql in enumerate(session.executed_sql) if "set_config" in sql
    ]
    lock_indices = [
        i for i, sql in enumerate(session.executed_sql) if "pg_try_advisory_lock" in sql
    ]
    assert set_config_indices, "set_config must be called"
    assert lock_indices, "pg_try_advisory_lock must be called"
    assert set_config_indices[0] < lock_indices[0], (
        "set_rls_context must be called before pg_try_advisory_lock"
    )


# ── Test: lock released on cancellation / config error ─────────────────


@pytest.mark.asyncio
async def test_drift_check_lock_released_on_config_error():
    """C-06: Advisory lock is released even when config load raises."""
    org_id = uuid.uuid4()
    session = _FakeSession(config_error=True)

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
    ):
        # config_error causes RuntimeError inside the inner try/except,
        # which sets config=None and continues. But we need to also mock
        # compute_drift since there is no real DB.
        with patch.object(
            mod, "compute_drift", new_callable=AsyncMock, return_value=_make_fake_report(),
        ):
            result = await mod.run_drift_check(org_id)

    # Lock must have been acquired AND released
    lock_sqls = [sql for sql in session.executed_sql if "pg_try_advisory_lock" in sql]
    unlock_sqls = [sql for sql in session.executed_sql if "pg_advisory_unlock" in sql]
    assert len(lock_sqls) == 1, "Lock must be acquired once"
    assert len(unlock_sqls) == 1, "Lock must be released once"
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_drift_check_lock_released_on_compute_drift_exception():
    """C-06: Advisory lock is released when compute_drift raises."""
    org_id = uuid.uuid4()
    session = _FakeSession()

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(
            mod, "compute_drift",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Simulated compute_drift failure"),
        ),
    ):
        with pytest.raises(RuntimeError, match="Simulated compute_drift failure"):
            await mod.run_drift_check(org_id)

    # Even after exception, lock must have been released
    unlock_sqls = [sql for sql in session.executed_sql if "pg_advisory_unlock" in sql]
    assert len(unlock_sqls) == 1, "Lock must be released even on exception"


@pytest.mark.asyncio
async def test_drift_check_lock_released_on_cancellation():
    """C-06: Advisory lock is released on asyncio.CancelledError."""
    org_id = uuid.uuid4()
    session = _FakeSession()

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(
            mod, "compute_drift",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError(),
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await mod.run_drift_check(org_id)

    # CancelledError is a BaseException — try/finally must still release lock
    unlock_sqls = [sql for sql in session.executed_sql if "pg_advisory_unlock" in sql]
    assert len(unlock_sqls) == 1, "Lock must be released even on CancelledError"


# ── Test: lock not acquired → skip ────────────────────────────────────


@pytest.mark.asyncio
async def test_drift_check_skips_when_lock_busy():
    """Lock not acquired → worker returns empty dict, no unlock called."""
    org_id = uuid.uuid4()
    session = _FakeSession(lock_acquired=False)

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
    ):
        result = await mod.run_drift_check(org_id)

    assert result == {}
    unlock_sqls = [sql for sql in session.executed_sql if "pg_advisory_unlock" in sql]
    assert len(unlock_sqls) == 0, "Lock was never acquired — unlock must not be called"

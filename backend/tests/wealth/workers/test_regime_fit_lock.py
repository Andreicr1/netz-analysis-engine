"""Tests for regime_fit advisory lock acquire/release (PR-Q99).

Validates:
  C-04: LOCK_ID 900_026 is acquired before run_regime_fit body executes
  C-04: Lock is released in finally (even on exception or cancellation)
  C-04: Concurrent invocation returns {"status": "skipped", "reason": "lock_held"}
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

from app.domains.wealth.workers import regime_fit as mod

# ── Helpers ────────────────────────────────────────────────────────────


class _FakeResult:
    """Minimal result proxy for mocked session.execute()."""

    def __init__(self, scalar_value=None):
        self._scalar = scalar_value

    def scalar(self):
        return self._scalar


class _FakeSession:
    """Fake async session that tracks execute calls for lock assertions."""

    def __init__(self, *, lock_acquired: bool = True):
        self._lock_acquired = lock_acquired
        self.executed_sql: list[str] = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self.executed_sql.append(sql)

        if "pg_try_advisory_lock" in sql:
            return _FakeResult(scalar_value=self._lock_acquired)

        if "pg_advisory_unlock" in sql:
            return _FakeResult(scalar_value=True)

        return _FakeResult()

    async def commit(self):
        pass


def _make_session_factory(session: _FakeSession):
    """Build an async context manager factory that yields the given session."""

    @asynccontextmanager
    async def factory():
        yield session

    return factory


# Sample VIX data — 300 points (> MIN_VIX_OBS=252) for tests that need fitting
_SAMPLE_VIX_DATES = [
    (date(2024, 1, 1), 15.0 + i * 0.01) for i in range(300)
]


# ── Test: skips when lock is already held ──────────────────────────────


@pytest.mark.asyncio
async def test_regime_fit_skips_when_lock_held():
    """Lock not acquired -> returns {"status": "skipped", "reason": "lock_held"}."""
    session = _FakeSession(lock_acquired=False)

    with patch.object(mod, "async_session", _make_session_factory(session)):
        result = await mod.run_regime_fit()

    assert result == {"status": "skipped", "reason": "lock_held"}

    # Lock was attempted but not acquired — no unlock should be called
    lock_sqls = [sql for sql in session.executed_sql if "pg_try_advisory_lock" in sql]
    unlock_sqls = [sql for sql in session.executed_sql if "pg_advisory_unlock" in sql]
    assert len(lock_sqls) == 1, "Lock must be attempted once"
    assert len(unlock_sqls) == 0, "Lock was never acquired — unlock must not be called"


# ── Test: lock released on exception in _do_regime_fit ─────────────────


@pytest.mark.asyncio
async def test_regime_fit_releases_lock_on_exception():
    """Advisory lock is released even when _fetch_vix_series_with_dates raises."""
    session = _FakeSession(lock_acquired=True)

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(
            mod,
            "_fetch_vix_series_with_dates",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Simulated VIX fetch failure"),
        ),
    ):
        with pytest.raises(RuntimeError, match="Simulated VIX fetch failure"):
            await mod.run_regime_fit()

    # Even after exception, lock must have been released
    lock_sqls = [sql for sql in session.executed_sql if "pg_try_advisory_lock" in sql]
    unlock_sqls = [sql for sql in session.executed_sql if "pg_advisory_unlock" in sql]
    assert len(lock_sqls) == 1, "Lock must be acquired once"
    assert len(unlock_sqls) == 1, "Lock must be released even on exception"


# ── Test: lock released on asyncio.CancelledError ──────────────────────


@pytest.mark.asyncio
async def test_regime_fit_releases_lock_on_cancellation():
    """Advisory lock is released on asyncio.CancelledError (BaseException)."""
    session = _FakeSession(lock_acquired=True)

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(
            mod,
            "_fetch_vix_series_with_dates",
            new_callable=AsyncMock,
            side_effect=asyncio.CancelledError(),
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await mod.run_regime_fit()

    # CancelledError is a BaseException — try/finally must still release lock
    unlock_sqls = [sql for sql in session.executed_sql if "pg_advisory_unlock" in sql]
    assert len(unlock_sqls) == 1, "Lock must be released even on CancelledError"


# ── Test: lock acquired and released on success path ───────────────────


@pytest.mark.asyncio
async def test_regime_fit_acquires_and_releases_lock_on_success():
    """Normal run: lock acquired, body runs, lock released."""
    session = _FakeSession(lock_acquired=True)

    with (
        patch.object(mod, "async_session", _make_session_factory(session)),
        patch.object(
            mod,
            "_fetch_vix_series_with_dates",
            new_callable=AsyncMock,
            return_value=_SAMPLE_VIX_DATES,
        ),
        patch.object(
            mod,
            "_fit_markov_regime",
            return_value=[0.3] * 300,
        ),
        patch.object(
            mod,
            "_persist_regime_history",
            new_callable=AsyncMock,
            return_value=300,
        ),
        patch.object(
            mod,
            "_update_snapshots_with_regime_probs",
            new_callable=AsyncMock,
            return_value=5,
        ),
    ):
        result = await mod.run_regime_fit()

    assert result["status"] == "completed"

    lock_sqls = [sql for sql in session.executed_sql if "pg_try_advisory_lock" in sql]
    unlock_sqls = [sql for sql in session.executed_sql if "pg_advisory_unlock" in sql]
    assert len(lock_sqls) == 1, "Lock must be acquired once"
    assert len(unlock_sqls) == 1, "Lock must be released once"

    # Unlock must come after lock
    lock_idx = next(i for i, sql in enumerate(session.executed_sql) if "pg_try_advisory_lock" in sql)
    unlock_idx = next(i for i, sql in enumerate(session.executed_sql) if "pg_advisory_unlock" in sql)
    assert unlock_idx > lock_idx, "Unlock must come after lock acquisition"


# ── Test: correct lock ID used ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_regime_fit_uses_correct_lock_id():
    """Lock SQL must contain LOCK_ID = 900026."""
    session = _FakeSession(lock_acquired=False)

    with patch.object(mod, "async_session", _make_session_factory(session)):
        await mod.run_regime_fit()

    lock_sqls = [sql for sql in session.executed_sql if "pg_try_advisory_lock" in sql]
    assert len(lock_sqls) == 1
    assert "900026" in lock_sqls[0], f"Lock SQL must use LOCK_ID 900026, got: {lock_sqls[0]}"


# ── Test: Q104 invariant — single session for all I/O ──────────────────


@pytest.mark.asyncio
async def test_regime_fit_uses_lock_owning_session_for_all_io():
    """Q104 invariant: all phases of regime fit must use the lock-owning
    session, not child sessions. This prevents idle-in-transaction timeout
    from killing the lock-holder mid-job and silently releasing the lock.

    Verified by wrapping async_session() and asserting it's called exactly once.
    """
    session = _FakeSession(lock_acquired=True)
    base_factory = _make_session_factory(session)

    call_count = 0

    def counting_factory(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return base_factory(*args, **kwargs)

    with (
        patch.object(mod, "async_session", side_effect=counting_factory),
        patch.object(
            mod,
            "_fetch_vix_series_with_dates",
            new_callable=AsyncMock,
            return_value=[],  # empty → short-circuits at MIN_VIX_OBS check
        ),
    ):
        result = await mod.run_regime_fit()

    assert result["status"] == "skipped"
    assert result["reason"] == "insufficient_vix_history"
    assert call_count == 1, (
        f"Expected exactly 1 async_session() open (lock-owning session). "
        f"Got {call_count}. _do_regime_fit must use the passed db, not open new sessions."
    )

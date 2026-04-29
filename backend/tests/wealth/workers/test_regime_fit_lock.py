"""Tests for regime_fit advisory lock acquire/release (PR-Q99, Q109).

Validates:
  C-04: LOCK_ID 900_026 is acquired before run_regime_fit body executes
  C-04: Lock is released in finally (even on exception or cancellation)
  C-04: Concurrent invocation returns {"status": "skipped", "reason": "lock_held"}
  Q109: Advisory lock acquired and released on the SAME pinned connection
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
    """Minimal result proxy for mocked connection.execute()."""

    def __init__(self, scalar_value=None):
        self._scalar = scalar_value

    def scalar(self):
        return self._scalar


class _FakeConnection:
    """Fake async connection that tracks execute calls for lock assertions."""

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


class _FakeEngine:
    """Fake engine whose connect() returns a fake connection context manager."""

    def __init__(self, conn: _FakeConnection):
        self._conn = conn
        self.connect_call_count = 0

    @asynccontextmanager
    async def connect(self):
        self.connect_call_count += 1
        yield self._conn


# Sample VIX data — 300 points (> MIN_VIX_OBS=252) for tests that need fitting
_SAMPLE_VIX_DATES = [
    (date(2024, 1, 1), 15.0 + i * 0.01) for i in range(300)
]


# ── Test: skips when lock is already held ──────────────────────────────


@pytest.mark.asyncio
async def test_regime_fit_skips_when_lock_held():
    """Lock not acquired -> returns {"status": "skipped", "reason": "lock_held"}."""
    conn = _FakeConnection(lock_acquired=False)
    fake_engine = _FakeEngine(conn)

    with patch.object(mod, "engine", fake_engine):
        result = await mod.run_regime_fit()

    assert result == {"status": "skipped", "reason": "lock_held"}

    # Lock was attempted but not acquired — no unlock should be called
    lock_sqls = [sql for sql in conn.executed_sql if "pg_try_advisory_lock" in sql]
    unlock_sqls = [sql for sql in conn.executed_sql if "pg_advisory_unlock" in sql]
    assert len(lock_sqls) == 1, "Lock must be attempted once"
    assert len(unlock_sqls) == 0, "Lock was never acquired — unlock must not be called"


# ── Test: lock released on exception in _do_regime_fit ─────────────────


@pytest.mark.asyncio
async def test_regime_fit_releases_lock_on_exception():
    """Advisory lock is released even when _fetch_vix_series_with_dates raises."""
    conn = _FakeConnection(lock_acquired=True)
    fake_engine = _FakeEngine(conn)

    with (
        patch.object(mod, "engine", fake_engine),
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
    lock_sqls = [sql for sql in conn.executed_sql if "pg_try_advisory_lock" in sql]
    unlock_sqls = [sql for sql in conn.executed_sql if "pg_advisory_unlock" in sql]
    assert len(lock_sqls) == 1, "Lock must be acquired once"
    assert len(unlock_sqls) == 1, "Lock must be released even on exception"


# ── Test: lock released on asyncio.CancelledError ──────────────────────


@pytest.mark.asyncio
async def test_regime_fit_releases_lock_on_cancellation():
    """Advisory lock is released on asyncio.CancelledError (BaseException)."""
    conn = _FakeConnection(lock_acquired=True)
    fake_engine = _FakeEngine(conn)

    with (
        patch.object(mod, "engine", fake_engine),
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
    unlock_sqls = [sql for sql in conn.executed_sql if "pg_advisory_unlock" in sql]
    assert len(unlock_sqls) == 1, "Lock must be released even on CancelledError"


# ── Test: lock acquired and released on success path ───────────────────


@pytest.mark.asyncio
async def test_regime_fit_acquires_and_releases_lock_on_success():
    """Normal run: lock acquired, body runs, lock released."""
    conn = _FakeConnection(lock_acquired=True)
    fake_engine = _FakeEngine(conn)

    with (
        patch.object(mod, "engine", fake_engine),
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

    lock_sqls = [sql for sql in conn.executed_sql if "pg_try_advisory_lock" in sql]
    unlock_sqls = [sql for sql in conn.executed_sql if "pg_advisory_unlock" in sql]
    assert len(lock_sqls) == 1, "Lock must be acquired once"
    assert len(unlock_sqls) == 1, "Lock must be released once"

    # Unlock must come after lock
    lock_idx = next(i for i, sql in enumerate(conn.executed_sql) if "pg_try_advisory_lock" in sql)
    unlock_idx = next(i for i, sql in enumerate(conn.executed_sql) if "pg_advisory_unlock" in sql)
    assert unlock_idx > lock_idx, "Unlock must come after lock acquisition"


# ── Test: correct lock ID used ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_regime_fit_uses_correct_lock_id():
    """Lock SQL must contain LOCK_ID = 900026."""
    conn = _FakeConnection(lock_acquired=False)
    fake_engine = _FakeEngine(conn)

    with patch.object(mod, "engine", fake_engine):
        await mod.run_regime_fit()

    lock_sqls = [sql for sql in conn.executed_sql if "pg_try_advisory_lock" in sql]
    assert len(lock_sqls) == 1
    assert "900026" in lock_sqls[0], f"Lock SQL must use LOCK_ID 900026, got: {lock_sqls[0]}"


# ── Test: Q109 — pinned connection invariant ───────────────────────────


@pytest.mark.asyncio
async def test_regime_fit_lock_held_on_pinned_connection():
    """Q109: advisory lock acquired and released on the SAME pinned
    connection via engine.connect(). Verifies that exactly one connection
    is opened and both lock/unlock happen on it.
    """
    conn = _FakeConnection(lock_acquired=True)
    fake_engine = _FakeEngine(conn)

    with (
        patch.object(mod, "engine", fake_engine),
        patch.object(
            mod,
            "_fetch_vix_series_with_dates",
            new_callable=AsyncMock,
            return_value=_SAMPLE_VIX_DATES,
        ),
        patch.object(mod, "_fit_markov_regime", return_value=[0.3] * 300),
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
    assert fake_engine.connect_call_count == 1, (
        "Must use exactly one pinned connection for the entire lock lifetime"
    )

    # Both lock and unlock happened on the same connection object
    lock_sqls = [sql for sql in conn.executed_sql if "pg_try_advisory_lock" in sql]
    unlock_sqls = [sql for sql in conn.executed_sql if "pg_advisory_unlock" in sql]
    assert len(lock_sqls) == 1, "Lock must be acquired once on pinned connection"
    assert len(unlock_sqls) == 1, "Lock must be released once on pinned connection"


# ── Test: Q109 — all phases use the pinned connection ──────────────────


@pytest.mark.asyncio
async def test_regime_fit_uses_pinned_connection_for_all_phases():
    """Q109: all phases of regime fit must use the pinned connection,
    not child sessions. The connection passed to _do_regime_fit is the
    same one that holds the advisory lock.
    """
    conn = _FakeConnection(lock_acquired=True)
    fake_engine = _FakeEngine(conn)

    with (
        patch.object(mod, "engine", fake_engine),
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
    assert fake_engine.connect_call_count == 1, (
        f"Expected exactly 1 engine.connect() call (pinned connection). "
        f"Got {fake_engine.connect_call_count}. "
        f"_do_regime_fit must use the passed conn, not open new ones."
    )

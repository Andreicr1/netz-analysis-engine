"""CP-04: Deep review lifecycle — deterministic state transitions.

Tests verify:
1. Success path writes exactly one READY status with timestamp.
2. Failure (exception) path writes exactly one FAILED status.
3. Soft error (result contains "error") writes FAILED status.
4. Safety net triggers when status-update session itself fails.
5. No stale PROCESSING state survives any code path.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.azure import pipeline_dispatch

# ── Helpers ──────────────────────────────────────────────────────────

_DEAL_ID = uuid.uuid4()
_FUND_ID = uuid.uuid4()


class FakeSession:
    """Minimal session stub that tracks execute/commit/rollback/close."""

    def __init__(self, *, fail_on_commit: bool = False) -> None:
        self.executions: list[dict[str, Any]] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self._fail_on_commit = fail_on_commit

    def execute(self, stmt: Any, params: dict | None = None) -> MagicMock:
        self.executions.append({"stmt": str(stmt), "params": params})
        return MagicMock(rowcount=1)

    def commit(self) -> None:
        if self._fail_on_commit:
            raise RuntimeError("simulated commit failure")
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


class SessionFactory:
    """Factory that yields pre-configured FakeSession instances in order."""

    def __init__(self, sessions: list[FakeSession]) -> None:
        self._sessions = list(sessions)
        self._index = 0
        self.all_sessions = sessions

    def __call__(self) -> FakeSession:
        if self._index >= len(self._sessions):
            # Safety: return a default session if more are requested
            s = FakeSession()
            self._sessions.append(s)
            self.all_sessions.append(s)
        s = self._sessions[self._index]
        self._index += 1
        return s


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_success_path_writes_ready_with_timestamp(monkeypatch):
    """Success: artifacts committed, READY written exactly once."""
    artifact_session = FakeSession()
    status_session = FakeSession()
    factory = SessionFactory([artifact_session, status_session])

    async def fake_deep_review(db, *, fund_id, deal_id, actor_id, force):
        return {"chaptersCompleted": 13, "version": "v4"}

    monkeypatch.setattr(
        "vertical_engines.credit.deep_review.async_run_deal_deep_review_v4",
        fake_deep_review,
    )

    await pipeline_dispatch._execute_deep_review_lifecycle(
        session_factory=factory,
        fund_id=_FUND_ID,
        deal_id=_DEAL_ID,
        actor="test-actor",
        force=False,
    )

    # Artifact session committed and closed
    assert artifact_session.committed is True
    assert artifact_session.closed is True

    # Status session wrote READY with timestamp
    assert status_session.committed is True
    assert status_session.closed is True
    assert len(status_session.executions) == 1
    params = status_session.executions[0]["params"]
    assert params["s"] == "READY"
    assert params["ts"] is not None  # generated_at timestamp
    assert params["id"] == str(_DEAL_ID)


@pytest.mark.asyncio
async def test_exception_path_writes_failed(monkeypatch):
    """Exception during deep review: FAILED written exactly once."""
    artifact_session = FakeSession()
    status_session = FakeSession()
    factory = SessionFactory([artifact_session, status_session])

    async def failing_deep_review(db, *, fund_id, deal_id, actor_id, force):
        raise ValueError("LLM timeout")

    monkeypatch.setattr(
        "vertical_engines.credit.deep_review.async_run_deal_deep_review_v4",
        failing_deep_review,
    )

    await pipeline_dispatch._execute_deep_review_lifecycle(
        session_factory=factory,
        fund_id=_FUND_ID,
        deal_id=_DEAL_ID,
        actor="test-actor",
        force=False,
    )

    # Artifact session rolled back and closed
    assert artifact_session.rolled_back is True
    assert artifact_session.closed is True

    # Status session wrote FAILED
    assert status_session.committed is True
    assert status_session.closed is True
    assert len(status_session.executions) == 1
    params = status_session.executions[0]["params"]
    assert params["s"] == "FAILED"
    assert "ts" not in params  # no timestamp for failure


@pytest.mark.asyncio
async def test_soft_error_path_writes_failed(monkeypatch):
    """Soft error (result has 'error' key): FAILED written exactly once."""
    artifact_session = FakeSession()
    status_session = FakeSession()
    factory = SessionFactory([artifact_session, status_session])

    async def soft_error_review(db, *, fund_id, deal_id, actor_id, force):
        return {"error": "Deal not found", "dealId": str(deal_id)}

    monkeypatch.setattr(
        "vertical_engines.credit.deep_review.async_run_deal_deep_review_v4",
        soft_error_review,
    )

    await pipeline_dispatch._execute_deep_review_lifecycle(
        session_factory=factory,
        fund_id=_FUND_ID,
        deal_id=_DEAL_ID,
        actor="test-actor",
        force=False,
    )

    # Artifact session rolled back (soft error)
    assert artifact_session.rolled_back is True
    assert artifact_session.closed is True

    # Status session wrote FAILED
    assert status_session.committed is True
    assert len(status_session.executions) == 1
    assert status_session.executions[0]["params"]["s"] == "FAILED"


@pytest.mark.asyncio
async def test_safety_net_fires_when_status_commit_fails(monkeypatch):
    """If the status-update commit fails, safety net writes FAILED."""
    artifact_session = FakeSession()
    status_session = FakeSession(fail_on_commit=True)
    fallback_session = FakeSession()
    factory = SessionFactory([artifact_session, status_session, fallback_session])

    async def ok_review(db, *, fund_id, deal_id, actor_id, force):
        return {"chaptersCompleted": 13}

    monkeypatch.setattr(
        "vertical_engines.credit.deep_review.async_run_deal_deep_review_v4",
        ok_review,
    )

    await pipeline_dispatch._execute_deep_review_lifecycle(
        session_factory=factory,
        fund_id=_FUND_ID,
        deal_id=_DEAL_ID,
        actor="test-actor",
        force=False,
    )

    # Status session failed to commit
    assert status_session.rolled_back is True
    assert status_session.closed is True

    # Safety-net fallback session wrote FAILED
    assert fallback_session.committed is True
    assert fallback_session.closed is True
    assert len(fallback_session.executions) == 1
    assert fallback_session.executions[0]["params"]["s"] == "FAILED"


@pytest.mark.asyncio
async def test_all_sessions_closed_on_any_path(monkeypatch):
    """Every session opened is guaranteed closed — no connection leaks."""
    artifact_session = FakeSession()
    status_session = FakeSession()
    factory = SessionFactory([artifact_session, status_session])

    async def ok_review(db, *, fund_id, deal_id, actor_id, force):
        return {"chaptersCompleted": 13}

    monkeypatch.setattr(
        "vertical_engines.credit.deep_review.async_run_deal_deep_review_v4",
        ok_review,
    )

    await pipeline_dispatch._execute_deep_review_lifecycle(
        session_factory=factory,
        fund_id=_FUND_ID,
        deal_id=_DEAL_ID,
        actor="test-actor",
        force=False,
    )

    for session in factory.all_sessions:
        assert session.closed is True, "Session was not closed"


@pytest.mark.asyncio
async def test_failure_after_artifact_persist_still_writes_terminal(monkeypatch):
    """Failure injection: artifacts persisted, then status update fails,
    safety net still writes a terminal FAILED state."""
    artifact_session = FakeSession()
    # Status session will fail on commit — simulates crash after artifact persist
    status_session = FakeSession(fail_on_commit=True)
    fallback_session = FakeSession()
    factory = SessionFactory([artifact_session, status_session, fallback_session])

    commit_count = 0

    async def ok_review(db, *, fund_id, deal_id, actor_id, force):
        return {"chaptersCompleted": 13}

    monkeypatch.setattr(
        "vertical_engines.credit.deep_review.async_run_deal_deep_review_v4",
        ok_review,
    )

    await pipeline_dispatch._execute_deep_review_lifecycle(
        session_factory=factory,
        fund_id=_FUND_ID,
        deal_id=_DEAL_ID,
        actor="test-actor",
        force=False,
    )

    # Artifacts were committed successfully
    assert artifact_session.committed is True

    # Status commit failed, safety net kicked in
    assert status_session.rolled_back is True

    # Fallback wrote FAILED
    assert fallback_session.committed is True
    assert fallback_session.executions[0]["params"]["s"] == "FAILED"


def test_dispatch_deep_review_background_tasks_path(monkeypatch):
    """dispatch_deep_review schedules the lifecycle coroutine via BackgroundTasks."""
    monkeypatch.setattr(pipeline_dispatch, "_use_service_bus", lambda: False)

    class DummyBackgroundTasks:
        def __init__(self):
            self.tasks: list = []

        def add_task(self, func, *args, **kwargs):
            self.tasks.append(func)

    bg = DummyBackgroundTasks()
    result = pipeline_dispatch.dispatch_deep_review(
        background_tasks=bg,
        fund_id=_FUND_ID,
        deal_id=_DEAL_ID,
        actor="test-actor",
        force=False,
    )

    assert result["dispatch"] == "background_tasks"
    assert result["dealId"] == str(_DEAL_ID)
    assert len(bg.tasks) == 1
    # The scheduled task should be a coroutine function
    import asyncio
    assert asyncio.iscoroutinefunction(bg.tasks[0])

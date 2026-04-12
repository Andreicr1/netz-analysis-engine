"""Tests for the Redis-backed cooperative cancellation primitives.

Phase 2 Session C commit 3 — exercises the low-level tracker helpers
(``request_cancellation``, ``is_cancellation_requested``,
``clear_cancellation_flag``). The DELETE /jobs/{id} route is covered
by integration tests once the full test harness stands up; here we
lock in the primitives a worker depends on.
"""
from __future__ import annotations

import uuid

import pytest

from app.core.jobs.tracker import (
    clear_cancellation_flag,
    is_cancellation_requested,
    request_cancellation,
)


@pytest.mark.asyncio
async def test_cancellation_flag_round_trip() -> None:
    job_id = f"test-cancel-{uuid.uuid4()}"
    try:
        assert await is_cancellation_requested(job_id) is False
        await request_cancellation(job_id, ttl_seconds=60)
        assert await is_cancellation_requested(job_id) is True
    finally:
        await clear_cancellation_flag(job_id)


@pytest.mark.asyncio
async def test_cancellation_is_idempotent() -> None:
    """Calling request_cancellation twice refreshes TTL — no error."""
    job_id = f"test-cancel-idem-{uuid.uuid4()}"
    try:
        await request_cancellation(job_id, ttl_seconds=60)
        await request_cancellation(job_id, ttl_seconds=60)
        assert await is_cancellation_requested(job_id) is True
    finally:
        await clear_cancellation_flag(job_id)


@pytest.mark.asyncio
async def test_clear_cancellation_flag() -> None:
    job_id = f"test-cancel-clear-{uuid.uuid4()}"
    await request_cancellation(job_id, ttl_seconds=60)
    assert await is_cancellation_requested(job_id) is True
    await clear_cancellation_flag(job_id)
    assert await is_cancellation_requested(job_id) is False


@pytest.mark.asyncio
async def test_unknown_job_reports_not_cancelled() -> None:
    job_id = f"test-cancel-missing-{uuid.uuid4()}"
    assert await is_cancellation_requested(job_id) is False

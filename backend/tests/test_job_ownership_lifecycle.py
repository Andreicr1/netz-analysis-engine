"""ASYNC-01: Job ownership lifecycle — TTL refresh, terminal cleanup, reconnect auth.

Time-travel tests prove that long-running jobs remain stream-authorizable
beyond the default 1-hour TTL, while terminal jobs clean up within the
bounded grace window.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.core.jobs.tracker import (
    DEFAULT_OWNERSHIP_TTL,
    TERMINAL_CLEANUP_TTL,
    TERMINAL_EVENT_TYPES,
    clear_job_owner,
    publish_terminal_event,
    refresh_job_owner_ttl,
    register_job_owner,
    verify_job_owner,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_ID = "org-test-001"
OTHER_ORG = "org-test-002"
JOB_ID = "dd:org-test-001:report-abc"


class FakeRedis:
    """Minimal in-memory Redis mock for ownership key lifecycle tests.

    Supports SET (with EX), GET, EXPIRE, TTL, DELETE.
    Uses a dict to store keys and their TTLs.
    """

    def __init__(self):
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value
        if ex is not None:
            self._ttls[key] = ex

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def expire(self, key: str, seconds: int) -> bool:
        if key not in self._store:
            return False
        self._ttls[key] = seconds
        return True

    async def ttl(self, key: str) -> int:
        if key not in self._store:
            return -2  # key does not exist
        return self._ttls.get(key, -1)

    async def delete(self, key: str) -> int:
        if key in self._store:
            del self._store[key]
            self._ttls.pop(key, None)
            return 1
        return 0

    async def publish(self, channel: str, message: str) -> int:
        return 0  # no subscribers in tests

    async def aclose(self) -> None:
        pass

    def simulate_expiry(self, key: str) -> None:
        """Simulate key expiry (time travel past TTL)."""
        self._store.pop(key, None)
        self._ttls.pop(key, None)


@pytest.fixture()
def fake_redis():
    """Provide a FakeRedis and patch tracker to use it."""
    r = FakeRedis()

    # aioredis.Redis() is a sync constructor — return FakeRedis directly
    with patch("app.core.jobs.tracker.aioredis.Redis", return_value=r):
        yield r


# ---------------------------------------------------------------------------
# Tests: register + verify basics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_and_verify(fake_redis: FakeRedis):
    """Registered job is verifiable by the owning org."""
    await register_job_owner(JOB_ID, ORG_ID)
    assert await verify_job_owner(JOB_ID, ORG_ID) is True
    assert await verify_job_owner(JOB_ID, OTHER_ORG) is False


@pytest.mark.asyncio
async def test_verify_missing_key_returns_false(fake_redis: FakeRedis):
    """Unregistered job denies access."""
    assert await verify_job_owner("nonexistent", ORG_ID) is False


# ---------------------------------------------------------------------------
# Tests: TTL refresh for long-running jobs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_extends_ttl(fake_redis: FakeRedis):
    """refresh_job_owner_ttl extends the TTL on an existing key."""
    await register_job_owner(JOB_ID, ORG_ID, ttl_seconds=3600)
    original_ttl = fake_redis._ttls.get(f"job:{JOB_ID}:org")
    assert original_ttl == 3600

    result = await refresh_job_owner_ttl(JOB_ID, ttl_seconds=3600)
    assert result is True
    # TTL was refreshed (set again to 3600)
    assert fake_redis._ttls[f"job:{JOB_ID}:org"] == 3600


@pytest.mark.asyncio
async def test_refresh_on_expired_key_returns_false(fake_redis: FakeRedis):
    """Refreshing an expired key returns False."""
    await register_job_owner(JOB_ID, ORG_ID)
    # Simulate time travel past TTL
    fake_redis.simulate_expiry(f"job:{JOB_ID}:org")

    result = await refresh_job_owner_ttl(JOB_ID)
    assert result is False


@pytest.mark.asyncio
async def test_time_travel_active_job_remains_authorizable(fake_redis: FakeRedis):
    """A job running >1h that refreshes TTL remains stream-authorizable.

    This is the core ASYNC-01 acceptance test:
    1. Register job with 1h TTL
    2. Simulate time passing (original TTL would expire)
    3. But TTL was refreshed before expiry
    4. Verify reconnect still succeeds
    """
    await register_job_owner(JOB_ID, ORG_ID, ttl_seconds=3600)

    # Simulate: 50 minutes pass, TTL refresh happens
    result = await refresh_job_owner_ttl(JOB_ID, ttl_seconds=3600)
    assert result is True

    # Job is still authorizable (key exists with refreshed TTL)
    assert await verify_job_owner(JOB_ID, ORG_ID) is True

    # Simulate: another 50 minutes pass, refresh again
    result = await refresh_job_owner_ttl(JOB_ID, ttl_seconds=3600)
    assert result is True
    assert await verify_job_owner(JOB_ID, ORG_ID) is True


@pytest.mark.asyncio
async def test_time_travel_without_refresh_loses_auth(fake_redis: FakeRedis):
    """Without TTL refresh, key expires and reconnect fails."""
    await register_job_owner(JOB_ID, ORG_ID, ttl_seconds=3600)

    # Simulate: 1h+ passes without refresh → key expired
    fake_redis.simulate_expiry(f"job:{JOB_ID}:org")

    assert await verify_job_owner(JOB_ID, ORG_ID) is False


# ---------------------------------------------------------------------------
# Tests: Terminal cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clear_job_owner_sets_grace_ttl(fake_redis: FakeRedis):
    """clear_job_owner sets the key to a short grace TTL."""
    await register_job_owner(JOB_ID, ORG_ID, ttl_seconds=3600)
    assert fake_redis._ttls[f"job:{JOB_ID}:org"] == 3600

    await clear_job_owner(JOB_ID)
    assert fake_redis._ttls[f"job:{JOB_ID}:org"] == TERMINAL_CLEANUP_TTL
    # Key still exists during grace window
    assert await verify_job_owner(JOB_ID, ORG_ID) is True


@pytest.mark.asyncio
async def test_clear_job_owner_after_grace_expires(fake_redis: FakeRedis):
    """After grace TTL expires, verify_job_owner returns False."""
    await register_job_owner(JOB_ID, ORG_ID)
    await clear_job_owner(JOB_ID)

    # Grace window: still accessible
    assert await verify_job_owner(JOB_ID, ORG_ID) is True

    # Simulate grace TTL expiry
    fake_redis.simulate_expiry(f"job:{JOB_ID}:org")
    assert await verify_job_owner(JOB_ID, ORG_ID) is False


@pytest.mark.asyncio
async def test_publish_terminal_event_cleans_up(fake_redis: FakeRedis):
    """publish_terminal_event publishes event AND schedules cleanup."""
    await register_job_owner(JOB_ID, ORG_ID, ttl_seconds=3600)

    await publish_terminal_event(JOB_ID, "report_completed", {"status": "done"})

    # Key should now have grace TTL, not the original 3600
    assert fake_redis._ttls[f"job:{JOB_ID}:org"] == TERMINAL_CLEANUP_TTL


@pytest.mark.asyncio
async def test_reconnect_after_terminal_within_grace_succeeds(fake_redis: FakeRedis):
    """Reconnect within grace window after terminal event succeeds."""
    await register_job_owner(JOB_ID, ORG_ID)
    await publish_terminal_event(JOB_ID, "report_completed")

    # Within grace window — reconnect works (for final event delivery)
    assert await verify_job_owner(JOB_ID, ORG_ID) is True


@pytest.mark.asyncio
async def test_reconnect_after_terminal_grace_expired_fails(fake_redis: FakeRedis):
    """Reconnect after grace window expires is denied."""
    await register_job_owner(JOB_ID, ORG_ID)
    await publish_terminal_event(JOB_ID, "report_completed")

    # Simulate grace TTL expiry
    fake_redis.simulate_expiry(f"job:{JOB_ID}:org")
    assert await verify_job_owner(JOB_ID, ORG_ID) is False


# ---------------------------------------------------------------------------
# Tests: Terminal event types constant
# ---------------------------------------------------------------------------


def test_terminal_event_types_include_all_known_terminals():
    """All known terminal event types are in the constant."""
    expected = {"done", "error", "ingestion_complete", "memo_complete",
                "report_completed", "report_failed"}
    assert expected == TERMINAL_EVENT_TYPES


# ---------------------------------------------------------------------------
# Tests: Constants have expected values
# ---------------------------------------------------------------------------


def test_default_ownership_ttl():
    assert DEFAULT_OWNERSHIP_TTL == 3600


def test_terminal_cleanup_ttl():
    assert TERMINAL_CLEANUP_TTL == 120


# ---------------------------------------------------------------------------
# Tests: Full lifecycle scenario (integration-style)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_lifecycle_long_running_job(fake_redis: FakeRedis):
    """End-to-end: register → refresh cycles → terminal → grace → expiry.

    Simulates a 3-hour DD report generation:
    - Registered at t=0 with 1h TTL
    - Refreshed at t=50m, t=110m, t=170m
    - Completed at t=180m (terminal event)
    - Reconnect at t=181m (within grace): allowed
    - Reconnect at t=185m (grace expired): denied
    """
    # t=0: Register
    await register_job_owner(JOB_ID, ORG_ID, ttl_seconds=3600)
    assert await verify_job_owner(JOB_ID, ORG_ID) is True

    # t=50m: First refresh (before 60m expiry)
    assert await refresh_job_owner_ttl(JOB_ID, ttl_seconds=3600) is True
    assert await verify_job_owner(JOB_ID, ORG_ID) is True

    # t=110m: Second refresh
    assert await refresh_job_owner_ttl(JOB_ID, ttl_seconds=3600) is True
    assert await verify_job_owner(JOB_ID, ORG_ID) is True

    # t=170m: Third refresh
    assert await refresh_job_owner_ttl(JOB_ID, ttl_seconds=3600) is True
    assert await verify_job_owner(JOB_ID, ORG_ID) is True

    # t=180m: Job completes — terminal event
    await publish_terminal_event(JOB_ID, "report_completed", {
        "report_id": "report-abc",
        "status": "completed",
    })
    assert fake_redis._ttls[f"job:{JOB_ID}:org"] == TERMINAL_CLEANUP_TTL

    # t=181m: Reconnect within grace → allowed
    assert await verify_job_owner(JOB_ID, ORG_ID) is True

    # t=185m: Grace expired → denied
    fake_redis.simulate_expiry(f"job:{JOB_ID}:org")
    assert await verify_job_owner(JOB_ID, ORG_ID) is False


@pytest.mark.asyncio
async def test_full_lifecycle_job_fails(fake_redis: FakeRedis):
    """Failed job also cleans up via publish_terminal_event."""
    await register_job_owner(JOB_ID, ORG_ID)

    await publish_terminal_event(JOB_ID, "report_failed", {
        "error": "Out of memory",
    })

    # Grace window
    assert await verify_job_owner(JOB_ID, ORG_ID) is True
    assert fake_redis._ttls[f"job:{JOB_ID}:org"] == TERMINAL_CLEANUP_TTL

    # After grace
    fake_redis.simulate_expiry(f"job:{JOB_ID}:org")
    assert await verify_job_owner(JOB_ID, ORG_ID) is False


@pytest.mark.asyncio
async def test_ingestion_terminal_cleanup(fake_redis: FakeRedis):
    """ingestion_complete terminal event also triggers cleanup."""
    job_id = "ingest:version-123"
    await register_job_owner(job_id, ORG_ID)

    await publish_terminal_event(job_id, "ingestion_complete", {
        "document_id": "doc-1",
        "chunks_indexed": 42,
    })

    assert fake_redis._ttls[f"job:{job_id}:org"] == TERMINAL_CLEANUP_TTL

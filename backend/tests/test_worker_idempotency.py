"""Tests for worker idempotency guard (M-6 audit remediation)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.core.jobs.worker_idempotency import (
    COMPLETED_TTL,
    FAILED_TTL,
    RUNNING_TTL,
    _status_key,
    check_worker_status,
    idempotent_worker_wrapper,
    mark_worker_completed,
    mark_worker_failed,
    mark_worker_running,
)


@pytest.fixture()
def mock_redis():
    """Mock Redis connection via get_redis_pool."""
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock()
    redis_mock.aclose = AsyncMock()

    pool_mock = AsyncMock()

    with patch(
        "app.core.jobs.worker_idempotency.get_redis_pool",
        return_value=pool_mock,
    ), patch(
        "app.core.jobs.worker_idempotency.aioredis.Redis",
        return_value=redis_mock,
    ):
        yield redis_mock


class TestStatusKey:
    def test_tenant_scoped(self):
        key = _status_key("run-risk-calc", "org-123")
        assert key == "worker:run-risk-calc:org-123:status"

    def test_global_scoped(self):
        key = _status_key("run-macro-ingestion", "global")
        assert key == "worker:run-macro-ingestion:global:status"


class TestCheckWorkerStatus:
    @pytest.mark.asyncio()
    async def test_returns_none_when_no_key(self, mock_redis):
        mock_redis.get.return_value = None
        result = await check_worker_status("run-risk-calc", "org-123")
        assert result is None

    @pytest.mark.asyncio()
    async def test_returns_state_when_running(self, mock_redis):
        state = {"status": "running", "worker": "run-risk-calc"}
        mock_redis.get.return_value = json.dumps(state)
        result = await check_worker_status("run-risk-calc", "org-123")
        assert result is not None
        assert result["status"] == "running"

    @pytest.mark.asyncio()
    async def test_returns_state_when_completed(self, mock_redis):
        state = {"status": "completed", "worker": "run-risk-calc"}
        mock_redis.get.return_value = json.dumps(state)
        result = await check_worker_status("run-risk-calc", "org-123")
        assert result is not None
        assert result["status"] == "completed"

    @pytest.mark.asyncio()
    async def test_returns_none_when_failed(self, mock_redis):
        """Failed status does NOT block re-triggers."""
        state = {"status": "failed", "worker": "run-risk-calc", "error": "boom"}
        mock_redis.get.return_value = json.dumps(state)
        result = await check_worker_status("run-risk-calc", "org-123")
        assert result is None


class TestMarkWorkerRunning:
    @pytest.mark.asyncio()
    async def test_sets_running_with_ttl(self, mock_redis):
        await mark_worker_running("run-risk-calc", "org-123")
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        key = call_args[0][0]
        value = json.loads(call_args[0][1])
        ttl = call_args[1]["ex"]

        assert key == "worker:run-risk-calc:org-123:status"
        assert value["status"] == "running"
        assert ttl == RUNNING_TTL


class TestMarkWorkerCompleted:
    @pytest.mark.asyncio()
    async def test_sets_completed_with_ttl(self, mock_redis):
        await mark_worker_completed("run-risk-calc", "org-123", {"funds": 5})
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        value = json.loads(call_args[0][1])
        ttl = call_args[1]["ex"]

        assert value["status"] == "completed"
        assert ttl == COMPLETED_TTL


class TestMarkWorkerFailed:
    @pytest.mark.asyncio()
    async def test_sets_failed_with_error(self, mock_redis):
        await mark_worker_failed("run-risk-calc", "org-123", "DB connection lost")
        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        value = json.loads(call_args[0][1])
        ttl = call_args[1]["ex"]

        assert value["status"] == "failed"
        assert "DB connection lost" in value["error"]
        assert ttl == FAILED_TTL


class TestIdempotentWorkerWrapper:
    @pytest.mark.asyncio()
    async def test_marks_completed_on_success(self, mock_redis):
        async def fake_worker():
            return {"ok": True}

        await idempotent_worker_wrapper("test-worker", "org-1", fake_worker)

        # Should have called set twice: once for completed
        # (mark_worker_running is called separately before dispatch)
        assert mock_redis.set.call_count == 1
        value = json.loads(mock_redis.set.call_args[0][1])
        assert value["status"] == "completed"

    @pytest.mark.asyncio()
    async def test_marks_failed_on_exception(self, mock_redis):
        async def failing_worker():
            raise ValueError("something broke")

        with pytest.raises(ValueError, match="something broke"):
            await idempotent_worker_wrapper("test-worker", "org-1", failing_worker)

        assert mock_redis.set.call_count == 1
        value = json.loads(mock_redis.set.call_args[0][1])
        assert value["status"] == "failed"
        assert "something broke" in value["error"]

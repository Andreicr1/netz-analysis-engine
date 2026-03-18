"""Tests for SRCH-03: partial indexing failure -> degraded terminal state.

Failure-injection tests that prove clients can distinguish full persistence
from partial persistence without inspecting logs.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from ai_engine.extraction.search_upsert_service import UpsertResult, upsert_chunks

# ── UpsertResult unit tests ──────────────────────────────────────────


class TestUpsertResultProperties:
    def test_full_success(self):
        r = UpsertResult(
            attempted_chunk_count=10,
            successful_chunk_count=10,
            failed_chunk_count=0,
            retryable=False,
        )
        assert r.is_full_success is True
        assert r.is_degraded is False
        assert r.is_total_failure is False

    def test_degraded(self):
        r = UpsertResult(
            attempted_chunk_count=10,
            successful_chunk_count=7,
            failed_chunk_count=3,
            retryable=True,
        )
        assert r.is_full_success is False
        assert r.is_degraded is True
        assert r.is_total_failure is False

    def test_total_failure(self):
        r = UpsertResult(
            attempted_chunk_count=10,
            successful_chunk_count=0,
            failed_chunk_count=10,
            retryable=True,
        )
        assert r.is_full_success is False
        assert r.is_degraded is False
        assert r.is_total_failure is True

    def test_empty_batch(self):
        r = UpsertResult(
            attempted_chunk_count=0,
            successful_chunk_count=0,
            failed_chunk_count=0,
            retryable=False,
        )
        assert r.is_full_success is False
        assert r.is_degraded is False
        assert r.is_total_failure is False


# ── upsert_chunks returns UpsertResult ───────────────────────────────


class TestUpsertChunksReturnsStructuredResult:
    """Verify upsert_chunks returns UpsertResult for all failure modes."""

    def test_empty_list_returns_zero_result(self):
        result = upsert_chunks([])
        assert isinstance(result, UpsertResult)
        assert result.attempted_chunk_count == 0
        assert result.successful_chunk_count == 0
        assert result.failed_chunk_count == 0

    def test_full_success_returns_counts(self, monkeypatch):
        mock_client = MagicMock()
        mock_client.upload_documents.return_value = [
            SimpleNamespace(succeeded=True),
            SimpleNamespace(succeeded=True),
            SimpleNamespace(succeeded=True),
        ]

        with patch(
            "app.services.azure.search_client.get_search_client",
            return_value=mock_client,
        ):
            result = upsert_chunks([
                {"id": "chunk-1"},
                {"id": "chunk-2"},
                {"id": "chunk-3"},
            ])

        assert isinstance(result, UpsertResult)
        assert result.attempted_chunk_count == 3
        assert result.successful_chunk_count == 3
        assert result.failed_chunk_count == 0
        assert result.is_full_success is True
        assert result.retryable is False
        assert result.batch_errors == []

    def test_partial_failure_returns_degraded(self, monkeypatch):
        """Inject partial failure: 2 succeed, 1 fails within a batch."""
        mock_client = MagicMock()
        mock_client.upload_documents.return_value = [
            SimpleNamespace(succeeded=True),
            SimpleNamespace(succeeded=True),
            SimpleNamespace(succeeded=False),
        ]

        with patch(
            "app.services.azure.search_client.get_search_client",
            return_value=mock_client,
        ):
            result = upsert_chunks([
                {"id": "chunk-1"},
                {"id": "chunk-2"},
                {"id": "chunk-3"},
            ])

        assert result.attempted_chunk_count == 3
        assert result.successful_chunk_count == 2
        assert result.failed_chunk_count == 1
        assert result.is_degraded is True
        assert result.retryable is True
        assert len(result.batch_errors) == 1

    def test_entire_batch_exception_returns_total_failure(self, monkeypatch):
        """Inject total failure: batch upload throws exception."""
        mock_client = MagicMock()
        mock_client.upload_documents.side_effect = RuntimeError("Azure throttled")

        with patch(
            "app.services.azure.search_client.get_search_client",
            return_value=mock_client,
        ):
            result = upsert_chunks([
                {"id": "chunk-1"},
                {"id": "chunk-2"},
            ])

        assert result.attempted_chunk_count == 2
        assert result.successful_chunk_count == 0
        assert result.failed_chunk_count == 2
        assert result.is_total_failure is True
        assert result.retryable is True
        assert "RuntimeError" in result.batch_errors[0]

    def test_multi_batch_partial_failure(self, monkeypatch):
        """Inject failure: first batch succeeds, second batch fails entirely."""
        mock_client = MagicMock()

        # First call: batch of 100 succeeds
        first_batch_results = [SimpleNamespace(succeeded=True)] * 100
        # Second call: batch of 50 fails entirely
        mock_client.upload_documents.side_effect = [
            first_batch_results,
            ConnectionError("Network timeout"),
        ]

        with patch(
            "app.services.azure.search_client.get_search_client",
            return_value=mock_client,
        ):
            # 150 docs -> 2 batches of 100 + 50
            docs = [{"id": f"chunk-{i}"} for i in range(150)]
            result = upsert_chunks(docs)

        assert result.attempted_chunk_count == 150
        assert result.successful_chunk_count == 100
        assert result.failed_chunk_count == 50
        assert result.is_degraded is True
        assert result.retryable is True


# ── Fake Redis for job state tests ───────────────────────────────────


class _FakeRedis:
    """Minimal in-memory Redis mock for persist/get job state tests."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def aclose(self) -> None:
        pass


@pytest.fixture()
def fake_redis():
    """Provide a _FakeRedis and patch tracker to use it."""
    r = _FakeRedis()

    with patch("app.core.jobs.tracker.aioredis.Redis", return_value=r):
        yield r


# ── Job state persistence tests ──────────────────────────────────────


class TestJobStatePersistence:
    """Verify persist_job_state and get_job_state round-trip."""

    @pytest.mark.asyncio
    async def test_persist_and_retrieve_degraded_state(self, fake_redis):
        """Client can retrieve persisted degraded state with chunk counts."""
        from app.core.jobs.tracker import get_job_state, persist_job_state

        job_id = "test-degraded-job-001"

        await persist_job_state(
            job_id,
            terminal_state="degraded",
            attempted_chunk_count=100,
            successful_chunk_count=85,
            failed_chunk_count=15,
            retryable=True,
            errors=["batch 1: 15/100 chunks failed"],
        )

        state = await get_job_state(job_id)
        assert state is not None
        assert state["terminal_state"] == "degraded"
        assert state["attempted_chunk_count"] == 100
        assert state["successful_chunk_count"] == 85
        assert state["failed_chunk_count"] == 15
        assert state["retryable"] is True
        assert len(state["errors"]) == 1

    @pytest.mark.asyncio
    async def test_persist_and_retrieve_success_state(self, fake_redis):
        from app.core.jobs.tracker import get_job_state, persist_job_state

        job_id = "test-success-job-002"

        await persist_job_state(
            job_id,
            terminal_state="success",
            attempted_chunk_count=50,
            successful_chunk_count=50,
            failed_chunk_count=0,
            retryable=False,
        )

        state = await get_job_state(job_id)
        assert state is not None
        assert state["terminal_state"] == "success"
        assert state["failed_chunk_count"] == 0
        assert state["retryable"] is False

    @pytest.mark.asyncio
    async def test_persist_and_retrieve_failed_state(self, fake_redis):
        from app.core.jobs.tracker import get_job_state, persist_job_state

        job_id = "test-failed-job-003"

        await persist_job_state(
            job_id,
            terminal_state="failed",
            attempted_chunk_count=30,
            successful_chunk_count=0,
            failed_chunk_count=30,
            retryable=True,
            errors=["batch 0: entire batch of 30 failed -- ConnectionError"],
        )

        state = await get_job_state(job_id)
        assert state is not None
        assert state["terminal_state"] == "failed"
        assert state["successful_chunk_count"] == 0
        assert state["failed_chunk_count"] == 30

    @pytest.mark.asyncio
    async def test_nonexistent_job_returns_none(self, fake_redis):
        from app.core.jobs.tracker import get_job_state

        state = await get_job_state("nonexistent-job-999")
        assert state is None

    @pytest.mark.asyncio
    async def test_client_distinguishes_success_from_degraded(self, fake_redis):
        """Core acceptance criterion: clients can distinguish full from partial
        persistence using only the persisted state -- no log inspection needed."""
        from app.core.jobs.tracker import get_job_state, persist_job_state

        # Persist two jobs: one success, one degraded
        await persist_job_state(
            "job-full",
            terminal_state="success",
            attempted_chunk_count=50,
            successful_chunk_count=50,
            failed_chunk_count=0,
            retryable=False,
        )
        await persist_job_state(
            "job-partial",
            terminal_state="degraded",
            attempted_chunk_count=50,
            successful_chunk_count=35,
            failed_chunk_count=15,
            retryable=True,
            errors=["batch 0: 15/50 chunks failed"],
        )

        full = await get_job_state("job-full")
        partial = await get_job_state("job-partial")

        # Client can programmatically distinguish
        assert full is not None
        assert partial is not None
        assert full["terminal_state"] != partial["terminal_state"]
        assert full["terminal_state"] == "success"
        assert partial["terminal_state"] == "degraded"
        assert full["failed_chunk_count"] == 0
        assert partial["failed_chunk_count"] > 0
        assert partial["retryable"] is True

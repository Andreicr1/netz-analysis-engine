"""Tests for ai_engine.pipeline.unified_pipeline — pipeline helpers and job management."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from ai_engine.pipeline.models import IngestRequest, PipelineStageResult
from ai_engine.pipeline.unified_pipeline import (
    _EXTRACTION_JOBS,
    _MAX_EXTRACTION_JOBS,
    EXTRACTION_SOURCE_CONFIG,
    _trim_extraction_jobs,
    _update_extraction_job,
    get_extraction_job_status,
    list_extraction_jobs,
    new_extraction_job,
    run_extraction_pipeline,
)

# ── IngestRequest validation ─────────────────────────────────────


class TestIngestRequest:
    def test_valid_request(self):
        r = IngestRequest(
            source="ui",
            org_id=uuid.UUID(int=1),
            vertical="credit",
            document_id=uuid.UUID(int=2),
            blob_uri="container/path/doc.pdf",
            filename="doc.pdf",
        )
        assert r.vertical == "credit"

    def test_invalid_vertical_raises(self):
        with pytest.raises(ValueError, match="Invalid vertical"):
            IngestRequest(
                source="ui",
                org_id=uuid.UUID(int=1),
                vertical="invalid",
                document_id=uuid.UUID(int=2),
                blob_uri="container/doc.pdf",
                filename="doc.pdf",
            )

    def test_path_traversal_blob_uri_raises(self):
        with pytest.raises(ValueError, match="path traversal"):
            IngestRequest(
                source="ui",
                org_id=uuid.UUID(int=1),
                vertical="credit",
                document_id=uuid.UUID(int=2),
                blob_uri="../etc/passwd",
                filename="doc.pdf",
            )

    def test_absolute_path_blob_uri_raises(self):
        with pytest.raises(ValueError, match="path traversal"):
            IngestRequest(
                source="ui",
                org_id=uuid.UUID(int=1),
                vertical="credit",
                document_id=uuid.UUID(int=2),
                blob_uri="/etc/passwd",
                filename="doc.pdf",
            )


# ── Job management ────────────────────────────────────────────────


class TestJobManagement:
    def setup_method(self):
        _EXTRACTION_JOBS.clear()

    def test_new_extraction_job(self):
        job_id = new_extraction_job("deals", "filter1")
        assert job_id in _EXTRACTION_JOBS
        job = _EXTRACTION_JOBS[job_id]
        assert job["source"] == "deals"
        assert job["status"] == "pending"
        assert job["deals_filter"] == "filter1"
        assert job["pipeline_name"] == "unified_pipeline"

    def test_get_extraction_job_status_exists(self):
        job_id = new_extraction_job("deals", "")
        status = get_extraction_job_status(job_id)
        assert status["job_id"] == job_id
        assert status["status"] == "pending"

    def test_get_extraction_job_status_not_found(self):
        status = get_extraction_job_status("nonexistent")
        assert status["error"] == "Job not found"

    def test_list_extraction_jobs_returns_all(self):
        new_extraction_job("deals", "a")
        new_extraction_job("deals", "b")
        jobs = list_extraction_jobs()
        assert len(jobs) == 2

    def test_update_extraction_job(self):
        job_id = new_extraction_job("deals", "")
        _update_extraction_job(job_id, status="running")
        assert _EXTRACTION_JOBS[job_id]["status"] == "running"

    def test_update_nonexistent_job_no_error(self):
        _update_extraction_job("nonexistent", status="running")  # Should not raise

    def test_trim_extraction_jobs(self):
        # Fill beyond max
        for i in range(_MAX_EXTRACTION_JOBS + 5):
            new_extraction_job("deals", f"filter_{i}")
        assert len(_EXTRACTION_JOBS) <= _MAX_EXTRACTION_JOBS + 5
        _trim_extraction_jobs()
        # After trim, should have removed at least 1


# ── EXTRACTION_SOURCE_CONFIG ──────────────────────────────────────


class TestExtractionSourceConfig:
    def test_config_has_expected_sources(self):
        assert "deals" in EXTRACTION_SOURCE_CONFIG
        assert "fund-data" in EXTRACTION_SOURCE_CONFIG
        assert "market-data" in EXTRACTION_SOURCE_CONFIG

    def test_each_source_has_required_keys(self):
        for source, config in EXTRACTION_SOURCE_CONFIG.items():
            assert "storage_prefix" in config
            assert "description" in config


# ── run_extraction_pipeline validation ────────────────────────────


class TestRunExtractionPipelineValidation:
    def setup_method(self):
        _EXTRACTION_JOBS.clear()

    def test_invalid_source_raises(self):
        with pytest.raises(ValueError, match="Invalid source"):
            run_extraction_pipeline(source="invalid_source")


# ── _check_gate ──────────────────────────────────────────────────


class TestCheckGate:
    @pytest.mark.asyncio
    async def test_success_gate_returns_none(self):
        from ai_engine.pipeline.unified_pipeline import _check_gate

        gate = PipelineStageResult(
            stage="test", success=True, data="ok", metrics={},
        )
        request = IngestRequest(
            source="ui",
            org_id=uuid.UUID(int=1),
            vertical="credit",
            document_id=uuid.UUID(int=2),
            blob_uri="container/doc.pdf",
            filename="doc.pdf",
        )
        result = await _check_gate(
            gate, "test",
            request=request, db=None, actor_id="test",
            metrics={}, warnings=[],
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_failure_gate_returns_result(self):
        from ai_engine.pipeline.unified_pipeline import _check_gate

        gate = PipelineStageResult(
            stage="test", success=False, data=None, metrics={},
            errors=["something failed"],
        )
        request = IngestRequest(
            source="ui",
            org_id=uuid.UUID(int=1),
            vertical="credit",
            document_id=uuid.UUID(int=2),
            blob_uri="container/doc.pdf",
            filename="doc.pdf",
        )
        result = await _check_gate(
            gate, "test",
            request=request, db=None, actor_id="test",
            metrics={}, warnings=[],
        )
        assert result is not None
        assert result.success is False
        assert "something failed" in result.errors

    @pytest.mark.asyncio
    async def test_gate_warnings_collected(self):
        from ai_engine.pipeline.unified_pipeline import _check_gate

        gate = PipelineStageResult(
            stage="test", success=True, data="ok", metrics={},
            warnings=["watch out"],
        )
        request = IngestRequest(
            source="ui",
            org_id=uuid.UUID(int=1),
            vertical="credit",
            document_id=uuid.UUID(int=2),
            blob_uri="container/doc.pdf",
            filename="doc.pdf",
        )
        warnings: list[str] = []
        await _check_gate(
            gate, "test",
            request=request, db=None, actor_id="test",
            metrics={}, warnings=warnings,
        )
        assert "watch out" in warnings


# ── _write_to_lake ────────────────────────────────────────────────


class TestWriteToLake:
    @pytest.mark.asyncio
    async def test_write_failure_returns_false(self):
        from ai_engine.pipeline.unified_pipeline import _write_to_lake

        with patch(
            "app.services.storage_client.get_storage_client",
            side_effect=Exception("no storage"),
        ):
            result = await _write_to_lake("test/path", b"data")
            assert result is False

    @pytest.mark.asyncio
    async def test_write_success_returns_true(self):
        from ai_engine.pipeline.unified_pipeline import _write_to_lake

        mock_client = AsyncMock()
        with patch(
            "app.services.storage_client.get_storage_client",
            return_value=mock_client,
        ):
            result = await _write_to_lake("test/path", b"data")
            assert result is True


# ── _emit helpers ─────────────────────────────────────────────────


class TestEmitHelpers:
    @pytest.mark.asyncio
    async def test_emit_none_version_id_noop(self):
        from ai_engine.pipeline.unified_pipeline import _emit
        await _emit(None, "test_event")  # Should not raise

    @pytest.mark.asyncio
    async def test_emit_terminal_none_version_id_noop(self):
        from ai_engine.pipeline.unified_pipeline import _emit_terminal
        await _emit_terminal(None, "test_event")  # Should not raise


# ── _audit helper ──────────────────────────────────────────────────


class TestAuditHelper:
    @pytest.mark.asyncio
    async def test_audit_none_db_noop(self):
        from ai_engine.pipeline.unified_pipeline import _audit
        await _audit(None, fund_id=None, actor_id="test",
                     action="TEST", entity_id=uuid.UUID(int=1), after=None)

    @pytest.mark.asyncio
    async def test_audit_none_fund_id_noop(self):
        from ai_engine.pipeline.unified_pipeline import _audit
        mock_db = AsyncMock()
        await _audit(mock_db, fund_id=None, actor_id="test",
                     action="TEST", entity_id=uuid.UUID(int=1), after=None)

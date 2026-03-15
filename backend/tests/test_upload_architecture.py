"""Tests for upload architecture — URL generation, completion, SSE wiring."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

DEV_HEADERS = {"X-DEV-ACTOR": "dev|org-test-001|ADMIN"}


@pytest.fixture
def anyio_backend():
    return "asyncio"


class TestUploadUrlEndpoint:
    @pytest.mark.asyncio
    async def test_upload_url_requires_auth(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/documents/upload-url", json={
                "fund_id": "00000000-0000-0000-0000-000000000001",
                "filename": "test.pdf",
            })
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_upload_complete_requires_auth(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/documents/upload-complete", json={
                "upload_id": "00000000-0000-0000-0000-000000000001",
                "fund_id": "00000000-0000-0000-0000-000000000001",
            })
            assert resp.status_code == 401


class TestUploadUrlRouteExists:
    @pytest.mark.asyncio
    async def test_upload_url_route_registered(self):
        """Verify the route exists (will get 401 without auth, not 404)."""
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/documents/upload-url", json={
                "fund_id": "00000000-0000-0000-0000-000000000001",
                "filename": "test.pdf",
            })
            assert resp.status_code != 404, "Route /documents/upload-url not found"

    @pytest.mark.asyncio
    async def test_upload_complete_route_registered(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/documents/upload-complete", json={
                "upload_id": "00000000-0000-0000-0000-000000000001",
                "fund_id": "00000000-0000-0000-0000-000000000001",
            })
            assert resp.status_code != 404, "Route /documents/upload-complete not found"


class TestSSEEventEmission:
    """Test the _emit helper used by ingestion worker."""

    @pytest.mark.asyncio
    async def test_emit_publishes_to_redis(self):
        from app.domains.credit.documents.services.ingestion_worker import _emit

        with patch("app.domains.credit.documents.services.ingestion_worker.publish_event", new_callable=AsyncMock) as mock_pub:
            import uuid

            vid = uuid.uuid4()
            await _emit(vid, "ocr_complete", {"pages": 42})
            mock_pub.assert_called_once_with(str(vid), "ocr_complete", {"pages": 42})

    @pytest.mark.asyncio
    async def test_emit_swallows_redis_errors(self):
        """SSE emission failure should not break ingestion."""
        from app.domains.credit.documents.services.ingestion_worker import _emit

        with patch(
            "app.domains.credit.documents.services.ingestion_worker.publish_event",
            new_callable=AsyncMock,
            side_effect=ConnectionError("Redis down"),
        ):
            import uuid

            # Should not raise
            await _emit(uuid.uuid4(), "test_event", {})


class TestJobStreamEndpoint:
    @pytest.mark.asyncio
    async def test_job_stream_requires_auth(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/jobs/test-job-123/stream")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_job_stream_route_registered(self):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/v1/jobs/test-job-123/stream")
            # 401 means route exists but auth failed (not 404)
            assert resp.status_code != 404, "Route /jobs/{job_id}/stream not found"

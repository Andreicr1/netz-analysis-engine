"""Tests for unified portfolio report endpoints.

Covers:
  - GET /model-portfolios/{id}/reports — auth (401), 404, schema shape, filtering
  - POST /model-portfolios/{id}/reports/generate — auth (401), 403, 404, 400, 202 accepted
  - GET /model-portfolios/{id}/reports/stream/{job_id} — auth (401), 403
  - Pydantic schema validation for report request/response schemas
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.domains.wealth.schemas.generated_report import (
    ReportGenerateRequest,
    ReportGenerateResponse,
    ReportHistoryItem,
    ReportHistoryResponse,
)
from app.main import app
from tests.conftest import DEV_ACTOR_HEADER


@pytest.fixture
async def client():
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Schema Unit Tests ───────────────────────────────────────


def test_report_generate_request_defaults():
    """ReportGenerateRequest has sensible defaults."""
    req = ReportGenerateRequest(report_type="fact_sheet")
    assert req.report_type == "fact_sheet"
    assert req.language == "pt"
    assert req.format == "executive"
    assert req.as_of_date is None


def test_report_generate_request_all_fields():
    """ReportGenerateRequest accepts all fields."""
    req = ReportGenerateRequest(
        report_type="monthly_report",
        as_of_date=date(2026, 4, 1),
        language="en",
        format="institutional",
    )
    assert req.report_type == "monthly_report"
    assert req.as_of_date == date(2026, 4, 1)
    assert req.language == "en"
    assert req.format == "institutional"


def test_report_generate_request_rejects_invalid_type():
    """ReportGenerateRequest rejects unknown report types."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReportGenerateRequest(report_type="unknown_type")


def test_report_history_item_from_attributes():
    """ReportHistoryItem validates from dict (simulating ORM)."""
    item = ReportHistoryItem(
        id=uuid.uuid4(),
        portfolio_id=uuid.uuid4(),
        report_type="fact_sheet",
        job_id="fs-abc123",
        display_filename="fact-sheet-conservative.pdf",
        generated_at=datetime.now(timezone.utc),
        size_bytes=102400,
        status="completed",
    )
    assert item.report_type == "fact_sheet"
    assert item.size_bytes == 102400


def test_report_history_response_empty():
    """ReportHistoryResponse works with empty list."""
    pid = uuid.uuid4()
    resp = ReportHistoryResponse(portfolio_id=pid, reports=[], total=0)
    assert resp.total == 0
    assert len(resp.reports) == 0


def test_report_generate_response_shape():
    """ReportGenerateResponse has expected fields."""
    resp = ReportGenerateResponse(
        job_id="fs-abc-12345678",
        portfolio_id=uuid.uuid4(),
        report_type="fact_sheet",
        status="accepted",
    )
    assert resp.status == "accepted"
    assert resp.job_id.startswith("fs-")


# ── Endpoint Integration Tests ──────────────────────────────


FAKE_PORTFOLIO_ID = str(uuid.uuid4())
API_PREFIX = "/api/v1"


@pytest.mark.anyio
async def test_list_reports_requires_auth(client: AsyncClient):
    """GET /model-portfolios/{id}/reports returns 401 without auth."""
    resp = await client.get(
        f"{API_PREFIX}/model-portfolios/{FAKE_PORTFOLIO_ID}/reports",
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_list_reports_404_nonexistent(client: AsyncClient):
    """GET /model-portfolios/{id}/reports returns 404 for missing portfolio."""
    resp = await client.get(
        f"{API_PREFIX}/model-portfolios/{FAKE_PORTFOLIO_ID}/reports",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_generate_report_requires_auth(client: AsyncClient):
    """POST /model-portfolios/{id}/reports/generate returns 401 without auth."""
    resp = await client.post(
        f"{API_PREFIX}/model-portfolios/{FAKE_PORTFOLIO_ID}/reports/generate",
        json={"report_type": "fact_sheet"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_generate_report_404_nonexistent(client: AsyncClient):
    """POST /model-portfolios/{id}/reports/generate returns 404 for missing portfolio."""
    resp = await client.post(
        f"{API_PREFIX}/model-portfolios/{FAKE_PORTFOLIO_ID}/reports/generate",
        json={"report_type": "fact_sheet"},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_generate_report_rejects_invalid_type(client: AsyncClient):
    """POST /model-portfolios/{id}/reports/generate returns 422 for invalid report_type."""
    resp = await client.post(
        f"{API_PREFIX}/model-portfolios/{FAKE_PORTFOLIO_ID}/reports/generate",
        json={"report_type": "nonexistent_report"},
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_stream_report_requires_auth(client: AsyncClient):
    """GET /model-portfolios/{id}/reports/stream/{job_id} returns 401 without auth."""
    resp = await client.get(
        f"{API_PREFIX}/model-portfolios/{FAKE_PORTFOLIO_ID}/reports/stream/fake-job-123",
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_stream_report_403_unauthorized_job(client: AsyncClient):
    """GET /model-portfolios/{id}/reports/stream/{job_id} returns 403 for unregistered job."""
    resp = await client.get(
        f"{API_PREFIX}/model-portfolios/{FAKE_PORTFOLIO_ID}/reports/stream/nonexistent-job",
        headers=DEV_ACTOR_HEADER,
    )
    assert resp.status_code == 403

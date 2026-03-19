"""Tests for DD Report approval workflow — approve, reject, self-approval, status filter.

Uses dependency overrides for get_db_with_rls and get_actor to avoid
real DB connections and auth.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls, get_org_id
from app.main import app
from app.shared.enums import Role

ORG_ID = "00000000-0000-0000-0000-000000000001"


def _actor(actor_id: str = "ic-reviewer", roles: list[Role] | None = None) -> Actor:
    return Actor(
        actor_id=actor_id,
        name="Test User",
        email="test@netz.capital",
        roles=roles or [Role.INVESTMENT_TEAM],
        organization_id=uuid.UUID(ORG_ID),
    )


def _make_dd_report(
    *,
    report_id: uuid.UUID | None = None,
    status: str = "pending_approval",
    created_by: str = "report-creator",
):
    """Create a mock DDReport."""
    report = MagicMock()
    report.id = report_id or uuid.uuid4()
    report.instrument_id = uuid.uuid4()
    report.report_type = "dd_report"
    report.version = 1
    report.status = status
    report.confidence_score = Decimal("75.50")
    report.decision_anchor = "invest"
    report.is_current = True
    report.created_at = datetime(2026, 3, 19, 12, 0, 0, tzinfo=timezone.utc)
    report.created_by = created_by
    report.approved_by = None
    report.approved_at = None
    report.rejection_reason = None
    report.config_snapshot = None
    report.schema_version = 1
    report.chapters = []
    report.organization_id = ORG_ID
    return report


def _mock_db_with_report(report):
    """Create a mock AsyncSession that returns the given report from execute()."""
    mock_db = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = report
    mock_db.execute.return_value = mock_result
    mock_db.commit = AsyncMock()
    return mock_db


def _setup_overrides(mock_db, actor: Actor):
    """Set FastAPI dependency overrides."""
    app.dependency_overrides[get_db_with_rls] = lambda: mock_db
    app.dependency_overrides[get_actor] = lambda: actor
    app.dependency_overrides[get_org_id] = lambda: ORG_ID


def _clear_overrides():
    app.dependency_overrides.pop(get_db_with_rls, None)
    app.dependency_overrides.pop(get_actor, None)
    app.dependency_overrides.pop(get_org_id, None)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    _clear_overrides()


# ── Approve ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestApproveEndpoint:
    async def test_approve_happy_path(self, client: AsyncClient):
        report = _make_dd_report(status="pending_approval", created_by="report-creator")
        mock_db = _mock_db_with_report(report)
        _setup_overrides(mock_db, _actor("ic-reviewer"))

        resp = await client.post(f"/api/v1/dd-reports/{report.id}/approve")

        assert resp.status_code == 200
        assert report.status == "approved"
        assert report.approved_by == "ic-reviewer"
        assert report.approved_at is not None

    async def test_self_approval_blocked(self, client: AsyncClient):
        """Creator cannot approve their own report (403)."""
        report = _make_dd_report(status="pending_approval", created_by="report-creator")
        mock_db = _mock_db_with_report(report)
        _setup_overrides(mock_db, _actor("report-creator"))

        resp = await client.post(f"/api/v1/dd-reports/{report.id}/approve")

        assert resp.status_code == 403
        assert "Self-approval" in resp.json()["detail"]

    async def test_approve_wrong_status_returns_409(self, client: AsyncClient):
        report = _make_dd_report(status="draft")
        mock_db = _mock_db_with_report(report)
        _setup_overrides(mock_db, _actor("ic-reviewer"))

        resp = await client.post(f"/api/v1/dd-reports/{report.id}/approve")

        assert resp.status_code == 409

    async def test_approve_investor_role_forbidden(self, client: AsyncClient):
        """Investor role cannot approve (403)."""
        report = _make_dd_report(status="pending_approval")
        mock_db = _mock_db_with_report(report)
        _setup_overrides(mock_db, _actor("investor-user", roles=[Role.INVESTOR]))

        resp = await client.post(f"/api/v1/dd-reports/{report.id}/approve")

        assert resp.status_code == 403

    async def test_approve_not_found(self, client: AsyncClient):
        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result
        _setup_overrides(mock_db, _actor("ic-reviewer"))

        resp = await client.post(f"/api/v1/dd-reports/{uuid.uuid4()}/approve")

        assert resp.status_code == 404


# ── Reject ───────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRejectEndpoint:
    async def test_reject_happy_path(self, client: AsyncClient):
        report = _make_dd_report(status="pending_approval")
        mock_db = _mock_db_with_report(report)
        _setup_overrides(mock_db, _actor("ic-reviewer"))

        resp = await client.post(
            f"/api/v1/dd-reports/{report.id}/reject",
            json={"reason": "Confidence score too low, needs more evidence on liquidity risk."},
        )

        assert resp.status_code == 200
        assert report.status == "draft"
        assert "liquidity risk" in report.rejection_reason

    async def test_reject_too_short_reason(self, client: AsyncClient):
        """Reason must be at least 10 characters (Pydantic validation)."""
        report = _make_dd_report(status="pending_approval")
        mock_db = _mock_db_with_report(report)
        _setup_overrides(mock_db, _actor("ic-reviewer"))

        resp = await client.post(
            f"/api/v1/dd-reports/{report.id}/reject",
            json={"reason": "short"},
        )

        assert resp.status_code == 422

    async def test_reject_wrong_status_returns_409(self, client: AsyncClient):
        report = _make_dd_report(status="approved")
        mock_db = _mock_db_with_report(report)
        _setup_overrides(mock_db, _actor("ic-reviewer"))

        resp = await client.post(
            f"/api/v1/dd-reports/{report.id}/reject",
            json={"reason": "This should fail because report is already approved."},
        )

        assert resp.status_code == 409


# ── Status Filter on List ────────────────────────────────────────


@pytest.mark.asyncio
class TestStatusFilter:
    async def test_list_with_status_filter(self, client: AsyncClient):
        approved_report = _make_dd_report(status="approved")
        fund_id = approved_report.instrument_id

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [approved_report]
        mock_db.execute.return_value = mock_result
        _setup_overrides(mock_db, _actor("ic-reviewer"))

        resp = await client.get(f"/api/v1/dd-reports/funds/{fund_id}?status=approved")

        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_list_without_filter(self, client: AsyncClient):
        report = _make_dd_report(status="pending_approval")
        fund_id = report.instrument_id

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [report]
        mock_db.execute.return_value = mock_result
        _setup_overrides(mock_db, _actor("ic-reviewer"))

        resp = await client.get(f"/api/v1/dd-reports/funds/{fund_id}")

        assert resp.status_code == 200


# ── Engine sets pending_approval ─────────────────────────────────


class TestEngineSetsPendingApproval:
    """Verify DDReportEngine._persist_results sets pending_approval for completed reports."""

    def test_persist_sets_pending_approval_when_all_complete(self):
        from vertical_engines.wealth.dd_report.dd_report_engine import DDReportEngine
        from vertical_engines.wealth.dd_report.models import ChapterResult

        engine = DDReportEngine()

        mock_db = MagicMock()
        mock_report = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_report

        chapters = [
            ChapterResult(
                tag=f"ch{i}", order=i, title=f"Chapter {i}",
                content_md="Test content", status="completed",
            )
            for i in range(1, 9)
        ]

        engine._persist_results(
            mock_db,
            report_id=uuid.uuid4(),
            organization_id=ORG_ID,
            chapters=chapters,
            confidence_score=80.0,
            decision_anchor="invest",
        )

        assert mock_report.status == "pending_approval"

    def test_persist_sets_draft_when_partial(self):
        from vertical_engines.wealth.dd_report.dd_report_engine import DDReportEngine
        from vertical_engines.wealth.dd_report.models import ChapterResult

        engine = DDReportEngine()

        mock_db = MagicMock()
        mock_report = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_report

        chapters = [
            ChapterResult(tag="ch1", order=1, title="Ch 1", content_md="Test", status="completed"),
            ChapterResult(tag="ch2", order=2, title="Ch 2", content_md=None, status="failed"),
        ]

        engine._persist_results(
            mock_db,
            report_id=uuid.uuid4(),
            organization_id=ORG_ID,
            chapters=chapters,
            confidence_score=40.0,
            decision_anchor=None,
        )

        assert mock_report.status == "draft"

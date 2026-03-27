"""Tests for credit AI provenance, memo timeline, and decision audit endpoints."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

ORG_ID = "00000000-0000-0000-0000-000000000001"
FUND_ID = uuid.UUID("00000000-0000-0000-0000-000000000099")
DEAL_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
DOC_ID = uuid.UUID("00000000-0000-0000-0000-000000000020")

DEV_ACTOR_HEADER = {
    "X-DEV-ACTOR": json.dumps(
        {
            "actor_id": "test-user",
            "roles": ["ADMIN"],
            "fund_ids": [str(FUND_ID)],
            "org_id": ORG_ID,
        },
    ),
}

BASE = f"/api/v1/funds/{FUND_ID}/deals/{DEAL_ID}"


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ── Mock helpers ──────────────────────────────────────────────────


def _fake_deal():
    deal = MagicMock()
    deal.id = DEAL_ID
    deal.fund_id = FUND_ID
    deal.stage = "QUALIFIED"
    return deal


def _fake_review():
    review = MagicMock()
    review.id = uuid.uuid4()
    review.document_id = DOC_ID
    review.document_type = "TERM_SHEET"
    review.classification_confidence = 0.92
    review.classification_layer = 2
    review.classification_model = None
    review.routing_basis = "Embedding similarity to term sheet corpus"
    review.submitted_at = datetime(2026, 3, 15, 10, 0, 0, tzinfo=UTC)
    review.status = "APPROVED"
    review.metadata_json = {"embedding_model": "text-embedding-3-large", "embedding_dim": 3072}
    review.fund_id = FUND_ID
    review.deal_id = DEAL_ID
    return review


def _fake_memo(version: int = 1):
    memo = MagicMock()
    memo.id = uuid.uuid4()
    memo.deal_id = DEAL_ID
    memo.version = version
    memo.recommendation = "APPROVED"
    memo.created_by = "analyst@netz.capital"
    memo.created_at = datetime(2026, 3, 14, 9, 0, 0, tzinfo=UTC)
    memo.updated_at = datetime(2026, 3, 14, 10, 0, 0, tzinfo=UTC)
    memo.committee_votes = [
        {
            "email": "ic-member@netz.capital",
            "vote": "APPROVED",
            "signed_at": "2026-03-14T11:00:00+00:00",
            "actor_capacity": "ic_member",
            "rationale": "Solid deal structure",
        },
    ]
    return memo


def _fake_audit_event(action: str, before: dict | None, after: dict | None):
    ae = MagicMock()
    ae.id = uuid.uuid4()
    ae.action = action
    ae.actor_id = "test-user"
    ae.entity_type = "Deal"
    ae.entity_id = str(DEAL_ID)
    ae.fund_id = FUND_ID
    ae.before_state = before
    ae.after_state = after
    ae.created_at = datetime(2026, 3, 15, 12, 0, 0, tzinfo=UTC)
    return ae


def _mock_db_returning(*call_results):
    """Build a mock AsyncSession returning different results for sequential execute() calls."""
    mock_db = AsyncMock()
    side_effects = []
    for cr in call_results:
        mock_result = MagicMock()
        if isinstance(cr, list):
            # scalars().all() pattern
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = cr
            mock_result.scalars.return_value = mock_scalars
        elif cr is None:
            # scalar_one_or_none() returning None
            mock_result.scalar_one_or_none.return_value = None
            mock_result.scalar.return_value = None
        else:
            # single object from scalar_one_or_none()
            mock_result.scalar_one_or_none.return_value = cr
            mock_result.scalar.return_value = cr
        side_effects.append(mock_result)
    mock_db.execute = AsyncMock(side_effect=side_effects)
    return mock_db


# ── Tests: AI Provenance ──────────────────────────────────────────


@pytest.mark.asyncio
class TestAIProvenance:
    async def test_returns_classification_metadata(self, client: AsyncClient):
        deal = _fake_deal()
        review = _fake_review()
        mock_db = _mock_db_returning(deal, review, 5)

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{BASE}/documents/{DOC_ID}/ai-provenance",
                headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["classification_result"] == "TERM_SHEET"
        assert data["classification_confidence"] == 0.92
        assert data["classification_layer"] == 2
        assert data["classification_layer_label"] == "Embedding similarity"
        assert data["embedding_model"] == "text-embedding-3-large"
        assert data["review_count"] == 5
        assert data["current_review_status"] == "APPROVED"

    async def test_404_for_nonexistent_document(self, client: AsyncClient):
        deal = _fake_deal()
        mock_db = _mock_db_returning(deal, None)

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{BASE}/documents/{DOC_ID}/ai-provenance",
                headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 404

    async def test_404_for_wrong_deal(self, client: AsyncClient):
        mock_db = _mock_db_returning(None)  # deal not found

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{BASE}/documents/{DOC_ID}/ai-provenance",
                headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 404
        assert "Deal not found" in resp.json()["detail"]


# ── Tests: Memo Timeline ─────────────────────────────────────────


@pytest.mark.asyncio
class TestMemoTimeline:
    async def test_returns_events_sorted(self, client: AsyncClient):
        deal = _fake_deal()
        memo = _fake_memo(version=1)
        mock_db = _mock_db_returning(deal, [memo])

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{BASE}/ic-memo/timeline", headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["memo_count"] == 1
        assert len(data["events"]) >= 1
        # First event should be memo_created
        assert data["events"][0]["event_type"] == "memo_created"
        # Check chronological order
        timestamps = [e["timestamp"] for e in data["events"]]
        assert timestamps == sorted(timestamps)

    async def test_empty_when_no_memos(self, client: AsyncClient):
        deal = _fake_deal()
        mock_db = _mock_db_returning(deal, [])

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{BASE}/ic-memo/timeline", headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["memo_count"] == 0
        assert data["events"] == []


# ── Tests: Decision Audit ─────────────────────────────────────────


@pytest.mark.asyncio
class TestDecisionAudit:
    async def test_returns_stage_transitions(self, client: AsyncClient):
        deal = _fake_deal()
        ae = _fake_audit_event(
            "deal.stage.changed",
            {"stage": "INTAKE"},
            {"stage": "QUALIFIED", "actor_email": "pm@netz.capital", "actor_capacity": "portfolio_manager"},
        )
        mock_db = _mock_db_returning(deal, [ae])

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{BASE}/decision-audit", headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 1
        event = data["events"][0]
        assert event["event_type"] == "stage_change"
        assert event["from_stage"] == "INTAKE"
        assert event["to_stage"] == "QUALIFIED"
        assert event["actor_id"] == "test-user"
        assert event["actor_email"] == "pm@netz.capital"

    async def test_empty_for_no_decisions(self, client: AsyncClient):
        deal = _fake_deal()
        mock_db = _mock_db_returning(deal, [])

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{BASE}/decision-audit", headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 0
        assert data["events"] == []

    async def test_404_for_wrong_tenant(self, client: AsyncClient):
        """RLS: deal not visible to wrong tenant returns 404."""
        mock_db = _mock_db_returning(None)

        from app.core.tenancy.middleware import get_db_with_rls
        app.dependency_overrides[get_db_with_rls] = lambda: mock_db
        try:
            resp = await client.get(
                f"{BASE}/decision-audit", headers=DEV_ACTOR_HEADER,
            )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 404

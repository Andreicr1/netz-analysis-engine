"""Tests for the Asset Universe service — approval flow, self-approval prevention, deactivation."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from vertical_engines.wealth.asset_universe.fund_approval import (
    VALID_DECISIONS,
    InvalidDecisionError,
    SelfApprovalError,
    decide_approval,
)
from vertical_engines.wealth.asset_universe.models import (
    ApprovalDecision,
    ApprovalRequest,
    DeactivationResult,
    UniverseAsset,
)


class TestApprovalModels:
    """Verify frozen dataclasses are immutable and have correct fields."""

    def test_approval_request_is_frozen(self):
        req = ApprovalRequest(
            instrument_id=uuid.uuid4(),
            analysis_report_id=uuid.uuid4(),
            created_by="user_1",
            organization_id="org_1",
        )
        with pytest.raises(AttributeError):
            req.instrument_id = uuid.uuid4()  # type: ignore[misc]

    def test_approval_decision_is_frozen(self):
        dec = ApprovalDecision(
            approval_id=uuid.uuid4(),
            decision="approved",
            rationale="Good fund",
            decided_by="user_2",
        )
        with pytest.raises(AttributeError):
            dec.decision = "rejected"  # type: ignore[misc]

    def test_universe_asset_is_frozen(self):
        asset = UniverseAsset(
            instrument_id=uuid.uuid4(),
            fund_name="Test Fund",
            block_id="equity_global",
            geography="US",
            asset_class="equity",
            approval_status="approved",
            approval_decision="approved",
            approved_at=None,
        )
        with pytest.raises(AttributeError):
            asset.fund_name = "Changed"  # type: ignore[misc]

    def test_deactivation_result_is_frozen(self):
        result = DeactivationResult(
            instrument_id=uuid.uuid4(),
            was_active=True,
            rebalance_needed=True,
        )
        with pytest.raises(AttributeError):
            result.rebalance_needed = False  # type: ignore[misc]


class TestValidDecisions:
    """Verify the VALID_DECISIONS constant."""

    def test_valid_decisions_contains_expected(self):
        assert "approved" in VALID_DECISIONS
        assert "rejected" in VALID_DECISIONS
        assert "watchlist" in VALID_DECISIONS

    def test_pending_not_in_valid_decisions(self):
        assert "pending" not in VALID_DECISIONS


class TestSelfApprovalPrevention:
    """Verify that self-approval is prevented."""

    def test_self_approval_raises(self):
        """decided_by == created_by should raise SelfApprovalError."""
        db = MagicMock()
        user_id = "user_same"
        approval_id = uuid.uuid4()

        # Mock the approval query
        mock_approval = MagicMock()
        mock_approval.id = approval_id
        mock_approval.decision = "pending"
        mock_approval.created_by = user_id
        mock_approval.fund_id = uuid.uuid4()

        db.execute.return_value.scalar_one_or_none.return_value = mock_approval

        decision = ApprovalDecision(
            approval_id=approval_id,
            decision="approved",
            rationale="I approve my own fund",
            decided_by=user_id,
        )

        with pytest.raises(SelfApprovalError):
            decide_approval(db, decision)

    def test_different_users_allowed(self):
        """decided_by != created_by should succeed."""
        db = MagicMock()
        approval_id = uuid.uuid4()
        fund_id = uuid.uuid4()

        mock_approval = MagicMock()
        mock_approval.id = approval_id
        mock_approval.decision = "pending"
        mock_approval.created_by = "user_submitter"
        mock_approval.fund_id = fund_id

        mock_fund = MagicMock()
        mock_fund.fund_id = fund_id
        mock_fund.approval_status = "dd_complete"

        # First call returns approval, second returns fund
        db.execute.return_value.scalar_one_or_none.side_effect = [
            mock_approval,
            mock_fund,
        ]

        decision = ApprovalDecision(
            approval_id=approval_id,
            decision="approved",
            rationale="Good fund",
            decided_by="user_reviewer",
        )

        result = decide_approval(db, decision)
        assert result.decision == "approved"
        assert result.decided_by == "user_reviewer"


class TestInvalidDecision:
    """Verify that invalid decisions are rejected."""

    def test_invalid_decision_raises(self):
        db = MagicMock()
        decision = ApprovalDecision(
            approval_id=uuid.uuid4(),
            decision="maybe",
            rationale=None,
            decided_by="user_1",
        )
        with pytest.raises(InvalidDecisionError):
            decide_approval(db, decision)


class TestUniverseServiceImports:
    """Verify the service can be imported and has expected methods."""

    def test_universe_service_importable(self):
        from vertical_engines.wealth.asset_universe import UniverseService

        svc = UniverseService()
        assert hasattr(svc, "add_fund")
        assert hasattr(svc, "approve_fund")
        assert hasattr(svc, "list_universe")
        assert hasattr(svc, "list_pending")
        assert hasattr(svc, "deactivate_asset")

    def test_fund_approval_helpers_importable(self):
        from vertical_engines.wealth.asset_universe.fund_approval import (
            InvalidDecisionError,
            MissingDDReportError,
            SelfApprovalError,
        )

        assert SelfApprovalError is not None
        assert InvalidDecisionError is not None
        assert MissingDDReportError is not None


class TestUniverseSchemas:
    """Verify Pydantic schemas for universe API."""

    def test_universe_asset_read_schema(self):
        from app.domains.wealth.schemas.universe import UniverseAssetRead

        asset = UniverseAssetRead(
            instrument_id=uuid.uuid4(),
            fund_name="Test Fund",
            block_id="equity_global",
            geography="US",
            asset_class="equity",
            approval_status="approved",
            approval_decision="approved",
            approved_at=None,
        )
        assert asset.fund_name == "Test Fund"
        assert asset.approval_decision == "approved"

    def test_universe_approval_read_from_attributes(self):
        from app.domains.wealth.schemas.universe import UniverseApprovalRead

        mock = MagicMock()
        mock.id = uuid.uuid4()
        mock.instrument_id = uuid.uuid4()
        mock.analysis_report_id = uuid.uuid4()
        mock.decision = "pending"
        mock.rationale = None
        mock.created_by = "user_1"
        mock.decided_by = None
        mock.decided_at = None
        mock.is_current = True
        mock.created_at = "2026-03-16T00:00:00"

        schema = UniverseApprovalRead.model_validate(mock)
        assert schema.decision == "pending"
        assert schema.is_current is True

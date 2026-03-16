"""Fund approval logic — self-approval prevention and state transitions.

Helpers used by UniverseService. Must NOT import from universe_service.py
(enforced by import-linter pattern: helpers must not import service).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domains.wealth.models.dd_report import DDReport
from app.domains.wealth.models.fund import Fund
from app.domains.wealth.models.universe_approval import UniverseApproval
from vertical_engines.wealth.asset_universe.models import ApprovalDecision, ApprovalRequest

# Valid approval decisions
VALID_DECISIONS = frozenset({"approved", "rejected", "watchlist"})

# Mapping from approval decision to fund approval_status
_DECISION_TO_FUND_STATUS: dict[str, str] = {
    "approved": "approved",
    "rejected": "rejected",
    "watchlist": "watchlist",
}


class SelfApprovalError(Exception):
    """Raised when decided_by == created_by (self-approval prevention)."""


class InvalidDecisionError(Exception):
    """Raised for an unrecognized decision value."""


class MissingDDReportError(Exception):
    """Raised when the DD report does not exist or is not completed."""


def validate_dd_report(db: Session, dd_report_id: uuid.UUID, fund_id: uuid.UUID) -> DDReport:
    """Verify DD report exists, belongs to the fund, and is completed."""
    report = db.execute(
        select(DDReport).where(
            DDReport.id == dd_report_id,
            DDReport.fund_id == fund_id,
        )
    ).scalar_one_or_none()

    if report is None:
        raise MissingDDReportError(
            f"DD Report {dd_report_id} not found for fund {fund_id}"
        )
    if report.status not in ("completed", "escalated"):
        raise MissingDDReportError(
            f"DD Report {dd_report_id} has status '{report.status}', expected 'completed' or 'escalated'"
        )
    return report


def create_pending_approval(db: Session, request: ApprovalRequest) -> UniverseApproval:
    """Create a pending UniverseApproval and update fund status to pending_dd.

    Marks any existing current approval as not current (is_current pattern).
    """
    # Mark previous current approval as not current
    existing = db.execute(
        select(UniverseApproval).where(
            UniverseApproval.fund_id == request.fund_id,
            UniverseApproval.organization_id == request.organization_id,
            UniverseApproval.is_current.is_(True),
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.is_current = False

    approval = UniverseApproval(
        fund_id=request.fund_id,
        dd_report_id=request.dd_report_id,
        organization_id=request.organization_id,
        decision="pending",
        created_by=request.created_by,
        is_current=True,
    )
    db.add(approval)
    db.flush()
    return approval


def decide_approval(db: Session, decision: ApprovalDecision) -> UniverseApproval:
    """Apply a decision to an existing approval.

    Enforces self-approval prevention: decided_by != created_by.
    Uses SELECT FOR UPDATE on the fund row to prevent concurrent state corruption.
    """
    if decision.decision not in VALID_DECISIONS:
        raise InvalidDecisionError(
            f"Invalid decision '{decision.decision}'. Valid: {', '.join(sorted(VALID_DECISIONS))}"
        )

    # Load approval with FOR UPDATE to prevent concurrent decisions
    approval = db.execute(
        select(UniverseApproval)
        .where(UniverseApproval.id == decision.approval_id)
        .with_for_update()
    ).scalar_one_or_none()

    if approval is None:
        raise ValueError(f"Approval {decision.approval_id} not found")

    if approval.decision != "pending":
        raise ValueError(
            f"Approval {decision.approval_id} already decided: {approval.decision}"
        )

    # Self-approval prevention
    if approval.created_by and approval.created_by == decision.decided_by:
        raise SelfApprovalError(
            "Self-approval is not allowed: the person who submitted the fund "
            "for approval cannot be the same person who decides on it"
        )

    # Lock the fund row to prevent concurrent state corruption
    fund = db.execute(
        select(Fund)
        .where(Fund.fund_id == approval.fund_id)
        .with_for_update()
    ).scalar_one_or_none()

    if fund is None:
        raise ValueError(f"Fund {approval.fund_id} not found")

    # Apply decision
    approval.decision = decision.decision
    approval.rationale = decision.rationale
    approval.decided_by = decision.decided_by
    approval.decided_at = datetime.now(timezone.utc)

    # Update fund approval_status
    fund.approval_status = _DECISION_TO_FUND_STATUS[decision.decision]

    db.flush()
    return approval

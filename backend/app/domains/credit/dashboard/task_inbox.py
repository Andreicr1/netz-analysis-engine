"""Task Inbox — cross-domain aggregation of pending user actions.

Endpoint:
  GET /dashboard/task-inbox → pending tasks across all modules

Aggregates:
  - Cash transactions awaiting approval/signature
  - Compliance obligations overdue or in-progress
  - Signature queue items pending action
  - Execution actions still open
  - Pipeline deals awaiting IC decision
  - IC Memos with open conditions or pending e-signatures
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor
from app.shared.enums import Role

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/task-inbox")
def task_inbox(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Return all pending tasks grouped by module, filtered by actor role."""
    roles = {r.value if hasattr(r, "value") else r for r in (actor.roles or [])}
    is_admin = Role.ADMIN.value in roles

    sections: list[dict[str, Any]] = []
    total = 0

    cash = _cash_tasks(db, fund_id, roles, is_admin)
    if cash:
        sections.append(cash)
        total += cash["count"]

    compliance = _compliance_tasks(db, fund_id, roles, is_admin)
    if compliance:
        sections.append(compliance)
        total += compliance["count"]

    signatures = _signature_tasks(db, fund_id, roles, is_admin)
    if signatures:
        sections.append(signatures)
        total += signatures["count"]

    actions = _action_tasks(db, fund_id, roles, is_admin)
    if actions:
        sections.append(actions)
        total += actions["count"]

    pipeline = _pipeline_tasks(db, fund_id, roles, is_admin)
    if pipeline:
        sections.append(pipeline)
        total += pipeline["count"]

    doc_reviews = _document_review_tasks(db, fund_id, roles, is_admin, actor)
    if doc_reviews:
        sections.append(doc_reviews)
        total += doc_reviews["count"]

    return {
        "totalPending": total,
        "sections": sections,
        "asOf": dt.datetime.now(dt.UTC).isoformat(),
    }


# ── Cash Management ──────────────────────────────────────────────────

def _cash_tasks(
    db: Session,
    fund_id: uuid.UUID,
    roles: set[str],
    is_admin: bool,
) -> dict[str, Any] | None:
    relevant_roles = {"DIRECTOR", "GP", "INVESTMENT_TEAM", "ADMIN"}
    if not is_admin and not roles.intersection(relevant_roles):
        return None

    from app.domains.credit.cash_management.enums import CashTransactionStatus
    from app.domains.credit.cash_management.models.cash import CashTransaction

    actionable = [
        CashTransactionStatus.PENDING_APPROVAL,
        CashTransactionStatus.APPROVED,
        CashTransactionStatus.SENT_TO_ADMIN,
    ]

    rows = list(
        db.execute(
            select(CashTransaction).where(
                CashTransaction.fund_id == fund_id,
                CashTransaction.status.in_(actionable),
            )
            .order_by(CashTransaction.created_at.desc())
            .limit(50),
        ).scalars().all(),
    )

    if not rows:
        return None

    items = []
    for tx in rows:
        action = _cash_action_label(tx.status)
        items.append({
            "id": str(tx.id),
            "title": f"{tx.type.value} — {tx.beneficiary_name or 'N/A'}",
            "subtitle": f"USD {float(tx.amount or 0):,.2f}",
            "status": tx.status.value,
            "action": action,
            "createdAt": tx.created_at.isoformat() if tx.created_at else None,
            "route": "cash-management",
        })

    return {
        "module": "cashManagement",
        "label": "Cash Management",
        "icon": "sap-icon://money-bills",
        "count": len(items),
        "items": items,
    }


def _cash_action_label(status: Any) -> str:
    from app.domains.credit.cash_management.enums import CashTransactionStatus

    mapping = {
        CashTransactionStatus.PENDING_APPROVAL: "approvalRequired",
        CashTransactionStatus.APPROVED: "sendToAdmin",
        CashTransactionStatus.SENT_TO_ADMIN: "confirmExecution",
    }
    return mapping.get(status, "review")


# ── Compliance Obligations ───────────────────────────────────────────

def _compliance_tasks(
    db: Session,
    fund_id: uuid.UUID,
    roles: set[str],
    is_admin: bool,
) -> dict[str, Any] | None:
    relevant_roles = {"COMPLIANCE", "ADMIN", "INVESTMENT_TEAM", "GP"}
    if not is_admin and not roles.intersection(relevant_roles):
        return None

    from app.domains.credit.modules.compliance.models import Obligation

    active_obligations = list(
        db.execute(
            select(Obligation).where(
                Obligation.fund_id == fund_id,
                Obligation.is_active.is_(True),
            ),
        ).scalars().all(),
    )

    if not active_obligations:
        return None

    obligation_ids = [o.id for o in active_obligations]

    from app.domains.credit.modules.compliance.service import (
        compute_display_status,
        get_workflow_status_map,
    )
    wf_map = get_workflow_status_map(db, fund_id=fund_id, obligation_ids=obligation_ids)

    today = dt.date.today()
    items = []
    for ob in active_obligations:
        wf_status = wf_map.get(ob.id, "OPEN")
        display = compute_display_status(wf_status, ob.next_due_date)

        if display in ("COMPLETED",):
            continue

        priority = "high" if display == "OVERDUE" else "medium"
        days_left = (ob.next_due_date - today).days if ob.next_due_date else None

        items.append({
            "id": str(ob.id),
            "title": ob.name,
            "subtitle": ob.responsible_party or ob.regulator or "",
            "status": display,
            "action": "resolveObligation",
            "priority": priority,
            "daysLeft": days_left,
            "dueDate": ob.next_due_date.isoformat() if ob.next_due_date else None,
            "route": "compliance",
        })

    items.sort(key=lambda x: (0 if x["status"] == "OVERDUE" else 1, x.get("daysLeft") or 9999))
    items = items[:50]

    if not items:
        return None

    return {
        "module": "compliance",
        "label": "Compliance",
        "icon": "sap-icon://shield",
        "count": len(items),
        "items": items,
    }


# ── Signature Queue ──────────────────────────────────────────────────

def _signature_tasks(
    db: Session,
    fund_id: uuid.UUID,
    roles: set[str],
    is_admin: bool,
) -> dict[str, Any] | None:
    relevant_roles = {"DIRECTOR", "GP", "INVESTMENT_TEAM", "ADMIN"}
    if not is_admin and not roles.intersection(relevant_roles):
        return None

    from app.domains.credit.modules.signatures.models import (
        SignatureQueueItem,
        SignatureQueueStatus,
    )

    pending_statuses = [
        SignatureQueueStatus.QUEUED,
        SignatureQueueStatus.SENT,
        SignatureQueueStatus.ERROR,
    ]

    rows = list(
        db.execute(
            select(SignatureQueueItem).where(
                SignatureQueueItem.fund_id == fund_id,
                SignatureQueueItem.status.in_(pending_statuses),
            )
            .order_by(SignatureQueueItem.created_at.desc())
            .limit(50),
        ).scalars().all(),
    )

    if not rows:
        return None

    items = []
    for sq in rows:
        action_map = {
            SignatureQueueStatus.QUEUED: "sendForSignature",
            SignatureQueueStatus.SENT: "awaitingSignature",
            SignatureQueueStatus.ERROR: "resolveError",
        }
        items.append({
            "id": str(sq.id),
            "title": sq.title,
            "subtitle": sq.source_page or "",
            "status": sq.status.value,
            "action": action_map.get(sq.status, "review"),
            "createdAt": sq.created_at.isoformat() if sq.created_at else None,
            "route": "signatures",
        })

    return {
        "module": "signatures",
        "label": "Signatures",
        "icon": "sap-icon://signature",
        "count": len(items),
        "items": items,
    }


# ── Execution Actions ────────────────────────────────────────────────

def _action_tasks(
    db: Session,
    fund_id: uuid.UUID,
    roles: set[str],
    is_admin: bool,
) -> dict[str, Any] | None:
    relevant_roles = {"INVESTMENT_TEAM", "COMPLIANCE", "ADMIN", "GP"}
    if not is_admin and not roles.intersection(relevant_roles):
        return None

    from app.domains.credit.modules.actions.models import Action

    rows = list(
        db.execute(
            select(Action).where(
                Action.fund_id == fund_id,
                Action.status.in_(["Open", "In Progress", "Pending Evidence", "Under Review"]),
            )
            .order_by(Action.due_date.asc().nullslast(), Action.created_at.desc())
            .limit(50),
        ).scalars().all(),
    )

    if not rows:
        return None

    today = dt.date.today()
    items = []
    for a in rows:
        overdue = a.due_date is not None and a.due_date < today
        items.append({
            "id": str(a.id),
            "title": a.title,
            "subtitle": a.owner_actor_id or "",
            "status": "OVERDUE" if overdue else a.status,
            "action": "completeAction",
            "priority": "high" if overdue else "medium",
            "dueDate": a.due_date.isoformat() if a.due_date else None,
            "route": "portfolio",
        })

    return {
        "module": "actions",
        "label": "Actions",
        "icon": "sap-icon://task",
        "count": len(items),
        "items": items,
    }


# ── Pipeline Deals (IC Decision) ────────────────────────────────────

def _pipeline_tasks(
    db: Session,
    fund_id: uuid.UUID,
    roles: set[str],
    is_admin: bool,
) -> dict[str, Any] | None:
    relevant_roles = {"ADMIN", "INVESTMENT_TEAM", "GP", "COMPLIANCE"}
    if not is_admin and not roles.intersection(relevant_roles):
        return None

    from app.domains.credit.modules.deals.models import PipelineDeal

    ic_stages = ("IC_REVIEW", "IC Decision", "ic_review", "ic_decision", "CONDITIONAL", "Conditional")

    rows = list(
        db.execute(
            select(PipelineDeal).where(
                PipelineDeal.fund_id == fund_id,
                PipelineDeal.is_archived.is_(False),
                PipelineDeal.intelligence_status == "READY",
                PipelineDeal.approved_deal_id.is_(None),
            )
            .order_by(PipelineDeal.created_at.desc())
            .limit(50),
        ).scalars().all(),
    )

    if not rows:
        return None

    items = []
    for deal in rows:
        stage = deal.stage or deal.lifecycle_stage or "Unknown"
        items.append({
            "id": str(deal.id),
            "title": deal.deal_name or deal.title or str(deal.id),
            "subtitle": deal.sponsor_name or deal.borrower_name or "",
            "status": stage,
            "action": "icDecision",
            "amount": f"USD {float(deal.requested_amount or 0):,.0f}" if deal.requested_amount else None,
            "route": "deals-pipeline",
            "routeParam": str(deal.id),
        })

    return {
        "module": "dealsPipeline",
        "label": "Deals Pipeline",
        "icon": "sap-icon://pipeline-analysis",
        "count": len(items),
        "items": items,
    }


# ── Document Reviews ─────────────────────────────────────────────────

def _document_review_tasks(
    db: Session,
    fund_id: uuid.UUID,
    roles: set[str],
    is_admin: bool,
    actor: Actor,
) -> dict[str, Any] | None:
    relevant_roles = {"ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE"}
    if not is_admin and not roles.intersection(relevant_roles):
        return None

    from app.domains.credit.documents.models.review import (
        DocumentReview,
        ReviewAssignment,
        ReviewStatus,
    )

    stmt = (
        select(DocumentReview)
        .where(
            DocumentReview.fund_id == fund_id,
            DocumentReview.status.in_([ReviewStatus.SUBMITTED.value, ReviewStatus.UNDER_REVIEW.value]),
        )
    )

    if not is_admin:
        stmt = (
            select(DocumentReview)
            .join(ReviewAssignment, ReviewAssignment.review_id == DocumentReview.id)
            .where(
                DocumentReview.fund_id == fund_id,
                DocumentReview.status.in_([ReviewStatus.SUBMITTED.value, ReviewStatus.UNDER_REVIEW.value]),
                ReviewAssignment.reviewer_actor_id == actor.actor_id,
                ReviewAssignment.decision.is_(None),
            )
        )

    rows = list(
        db.execute(
            stmt.order_by(DocumentReview.due_date.asc().nullslast(), DocumentReview.submitted_at.desc())
            .limit(50),
        ).scalars().all(),
    )

    if not rows:
        return None

    today = dt.date.today()
    items = []
    for r in rows:
        overdue = r.due_date is not None and r.due_date < today
        items.append({
            "id": str(r.id),
            "title": r.title,
            "subtitle": f"{r.document_type} — {r.submitted_by}",
            "status": r.status,
            "action": "reviewDocument",
            "priority": "high" if r.priority == "URGENT" or overdue else ("medium" if r.priority == "HIGH" else "low"),
            "dueDate": r.due_date.isoformat() if r.due_date else None,
            "route": "deals-pipeline",
            "routeParam": str(r.deal_id) if r.deal_id else None,
        })

    return {
        "module": "documentReviews",
        "label": "Document Reviews",
        "icon": "sap-icon://document-text",
        "count": len(items),
        "items": items,
    }

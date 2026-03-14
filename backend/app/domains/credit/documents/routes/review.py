"""Document Review routes — governed review workflow for legal documents.

Endpoints:
  POST /document-reviews                          → submit document for review
  GET  /document-reviews                          → list reviews (filterable)
  GET  /document-reviews/{id}                     → review detail + assignments + events
  POST /document-reviews/{id}/assign              → assign reviewer(s)
  POST /document-reviews/{id}/decide              → reviewer submits decision
  POST /document-reviews/{id}/finalize            → GP/Admin force-decides
  POST /document-reviews/{id}/resubmit            → resubmit after revision request
  GET  /document-reviews/pending                  → reviews awaiting current actor's decision
  GET  /document-reviews/summary                  → dashboard counts by status
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_fund_access, require_role
from app.domains.credit.documents.models.review import (
    DocumentReview,
    ReviewAssignment,
    ReviewChecklistItem,
    ReviewDecision,
    ReviewEvent,
    ReviewPriority,
    ReviewStatus,
)
from app.domains.credit.documents.services.checklist_templates import get_checklist_template
from app.domains.credit.modules.documents.models import Document, DocumentVersion

router = APIRouter(
    prefix="/funds/{fund_id}/document-reviews",
    tags=["Document Reviews"],
    dependencies=[Depends(require_fund_access())],
)


# ── Routing rules by document type ──────────────────────────────────

_REVIEW_ROUTING: dict[str, list[str]] = {
    "LEGAL": ["COMPLIANCE", "INVESTMENT_TEAM"],
    "REGULATORY": ["COMPLIANCE"],
    "DD_REPORT": ["INVESTMENT_TEAM"],
    "TERM_SHEET": ["INVESTMENT_TEAM", "COMPLIANCE"],
    "INVESTMENT_MEMO": ["INVESTMENT_TEAM", "GP"],
    "MARKETING": ["GP"],
    "OTHER": ["INVESTMENT_TEAM"],
}


# ── Schemas ──────────────────────────────────────────────────────────

class ReviewSubmit(BaseModel):
    document_id: uuid.UUID
    document_version_id: uuid.UUID | None = None
    title: str
    document_type: str
    deal_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    priority: str = ReviewPriority.MEDIUM.value
    due_date: date | None = None
    review_notes: str | None = None


class AssignReviewer(BaseModel):
    reviewer_actor_id: str
    reviewer_role: str | None = None
    is_required: bool = True


class ReviewDecisionPayload(BaseModel):
    decision: str = Field(description="APPROVED | REJECTED | REVISION_REQUESTED")
    comments: str | None = None


class FinalizePayload(BaseModel):
    decision: str = Field(description="APPROVED | REJECTED")
    comments: str | None = None


# ── Submit ───────────────────────────────────────────────────────────

@router.post("")
def submit_for_review(
    fund_id: uuid.UUID,
    payload: ReviewSubmit,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE"])),
) -> dict[str, Any]:
    """Submit a document for review. Auto-assigns reviewers based on document type."""
    now = datetime.now(UTC)

    document_exists = db.execute(
        select(Document.id).where(Document.id == payload.document_id, Document.fund_id == fund_id),
    ).scalar_one_or_none()
    if document_exists is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if payload.document_version_id is not None:
        version_exists = db.execute(
            select(DocumentVersion.id).where(
                DocumentVersion.id == payload.document_version_id,
                DocumentVersion.document_id == payload.document_id,
                DocumentVersion.fund_id == fund_id,
            ),
        ).scalar_one_or_none()
        if version_exists is None:
            raise HTTPException(status_code=404, detail="Document version not found")

    routing_roles = _REVIEW_ROUTING.get(payload.document_type, ["INVESTMENT_TEAM"])

    review = DocumentReview(
        fund_id=fund_id,
        document_id=payload.document_id,
        document_version_id=payload.document_version_id,
        deal_id=payload.deal_id,
        asset_id=payload.asset_id,
        title=payload.title,
        document_type=payload.document_type,
        status=ReviewStatus.SUBMITTED.value,
        priority=payload.priority,
        submitted_by=actor.actor_id,
        submitted_at=now,
        due_date=payload.due_date,
        review_notes=payload.review_notes,
        routing_basis=f"auto-routed by document_type={payload.document_type}",
    )
    db.add(review)
    db.flush()

    checklist_items = _create_checklist_from_template(db, review)

    _log_event(db, review, "submitted", actor.actor_id, {
        "document_type": payload.document_type,
        "priority": payload.priority,
        "routing_roles": routing_roles,
        "checklist_items": len(checklist_items),
    })

    write_audit_event(
        db=db, fund_id=fund_id, actor_id=actor.actor_id,
        action="document_review.submitted", entity_type="DocumentReview",
        entity_id=str(review.id), before=None,
        after={"document_id": str(payload.document_id), "document_type": payload.document_type},
    )

    db.commit()
    return {
        **_review_to_dict(review),
        "suggestedReviewerRoles": routing_roles,
    }


# ── List & Detail ────────────────────────────────────────────────────

@router.get("")
def list_reviews(
    fund_id: uuid.UUID,
    status: str | None = None,
    document_type: str | None = None,
    deal_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE", "AUDITOR"])),
) -> dict[str, Any]:
    stmt = select(DocumentReview).where(DocumentReview.fund_id == fund_id)
    if status:
        stmt = stmt.where(DocumentReview.status == status)
    if document_type:
        stmt = stmt.where(DocumentReview.document_type == document_type)
    if deal_id:
        stmt = stmt.where(DocumentReview.deal_id == deal_id)

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = list(
        db.execute(
            stmt.order_by(DocumentReview.submitted_at.desc()).limit(limit).offset(offset),
        ).scalars().all(),
    )

    return {"total": total, "reviews": [_review_to_dict(r) for r in rows]}


@router.get("/pending")
def get_pending_reviews(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE"])),
) -> dict[str, Any]:
    """Return reviews where the current actor has an undecided assignment."""
    stmt = (
        select(DocumentReview)
        .join(ReviewAssignment, ReviewAssignment.review_id == DocumentReview.id)
        .where(
            DocumentReview.fund_id == fund_id,
            DocumentReview.status.in_([ReviewStatus.SUBMITTED.value, ReviewStatus.UNDER_REVIEW.value]),
            ReviewAssignment.reviewer_actor_id == actor.actor_id,
            ReviewAssignment.decision.is_(None),
        )
        .order_by(DocumentReview.due_date.asc().nullslast(), DocumentReview.submitted_at.desc())
    )
    rows = list(db.execute(stmt).scalars().all())
    return {"count": len(rows), "reviews": [_review_to_dict(r) for r in rows]}


@router.get("/summary")
def review_summary(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE", "AUDITOR"])),
) -> dict[str, Any]:
    """Dashboard-level review counts by status."""
    rows = list(
        db.execute(
            select(DocumentReview.status, func.count(DocumentReview.id))
            .where(DocumentReview.fund_id == fund_id)
            .group_by(DocumentReview.status),
        ).all(),
    )
    counts = {s.value: 0 for s in ReviewStatus}
    for status_val, cnt in rows:
        counts[status_val] = cnt

    return {
        "total": sum(counts.values()),
        "submitted": counts.get("SUBMITTED", 0),
        "underReview": counts.get("UNDER_REVIEW", 0),
        "approved": counts.get("APPROVED", 0),
        "rejected": counts.get("REJECTED", 0),
        "revisionRequested": counts.get("REVISION_REQUESTED", 0),
        "cancelled": counts.get("CANCELLED", 0),
    }


@router.get("/{review_id}")
def get_review_detail(
    fund_id: uuid.UUID,
    review_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE", "AUDITOR"])),
) -> dict[str, Any]:
    review = _get_review(db, fund_id, review_id)

    assignments = list(
        db.execute(
            select(ReviewAssignment)
            .where(ReviewAssignment.review_id == review_id)
            .order_by(ReviewAssignment.round_number, ReviewAssignment.created_at),
        ).scalars().all(),
    )

    events = list(
        db.execute(
            select(ReviewEvent)
            .where(ReviewEvent.review_id == review_id)
            .order_by(ReviewEvent.created_at.asc()),
        ).scalars().all(),
    )

    checklist_items = _get_checklist_items(db, review_id)
    total_cl = len(checklist_items)
    checked_cl = sum(1 for i in checklist_items if i.is_checked)
    required_cl = sum(1 for i in checklist_items if i.is_required)
    required_checked_cl = sum(1 for i in checklist_items if i.is_required and i.is_checked)

    result = _review_to_dict(review)
    result["assignments"] = [
        {
            "id": str(a.id),
            "reviewerActorId": a.reviewer_actor_id,
            "reviewerRole": a.reviewer_role,
            "roundNumber": a.round_number,
            "isRequired": a.is_required,
            "decision": a.decision,
            "decisionAt": a.decision_at.isoformat() if a.decision_at else None,
            "comments": a.comments,
        }
        for a in assignments
    ]
    result["checklist"] = {
        "total": total_cl,
        "checked": checked_cl,
        "required": required_cl,
        "requiredChecked": required_checked_cl,
        "allRequiredComplete": required_checked_cl >= required_cl,
        "completionPct": round(checked_cl / total_cl * 100, 1) if total_cl > 0 else 100,
        "items": [_checklist_item_to_dict(i) for i in checklist_items],
    }
    result["events"] = [
        {
            "id": str(e.id),
            "eventType": e.event_type,
            "actorId": e.actor_id,
            "detail": e.detail,
            "createdAt": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]
    return result


# ── Assign ───────────────────────────────────────────────────────────

@router.post("/{review_id}/assign")
def assign_reviewer(
    fund_id: uuid.UUID,
    review_id: uuid.UUID,
    payload: list[AssignReviewer],
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM"])),
) -> dict[str, Any]:
    """Assign one or more reviewers. Transitions status to UNDER_REVIEW."""
    review = _get_review(db, fund_id, review_id)

    if review.status in (ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value, ReviewStatus.CANCELLED.value):
        raise HTTPException(status_code=409, detail=f"Cannot assign reviewers: review is {review.status}")

    created = []
    for p in payload:
        assignment = ReviewAssignment(
            fund_id=fund_id,
            review_id=review_id,
            reviewer_actor_id=p.reviewer_actor_id,
            reviewer_role=p.reviewer_role,
            round_number=review.current_round,
            is_required=p.is_required,
        )
        db.add(assignment)
        created.append(assignment)

    if review.status == ReviewStatus.SUBMITTED.value:
        review.status = ReviewStatus.UNDER_REVIEW.value

    db.flush()

    _log_event(db, review, "assigned", actor.actor_id, {
        "reviewers": [p.reviewer_actor_id for p in payload],
        "round": review.current_round,
    })

    write_audit_event(
        db=db, fund_id=fund_id, actor_id=actor.actor_id,
        action="document_review.reviewers_assigned", entity_type="DocumentReview",
        entity_id=str(review_id), before={"status": ReviewStatus.SUBMITTED.value},
        after={"status": review.status, "reviewers_added": len(created)},
    )

    db.commit()
    return {"reviewId": str(review_id), "status": review.status, "assignmentsAdded": len(created)}


# ── Decide ───────────────────────────────────────────────────────────

@router.post("/{review_id}/decide")
def submit_decision(
    fund_id: uuid.UUID,
    review_id: uuid.UUID,
    payload: ReviewDecisionPayload,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE"])),
) -> dict[str, Any]:
    """A reviewer submits their decision on the document."""
    review = _get_review(db, fund_id, review_id)

    if review.status not in (ReviewStatus.UNDER_REVIEW.value, ReviewStatus.SUBMITTED.value):
        raise HTTPException(status_code=409, detail=f"Cannot decide: review is {review.status}")

    assignment = db.execute(
        select(ReviewAssignment).where(
            ReviewAssignment.review_id == review_id,
            ReviewAssignment.reviewer_actor_id == actor.actor_id,
            ReviewAssignment.round_number == review.current_round,
            ReviewAssignment.decision.is_(None),
        ),
    ).scalar_one_or_none()

    if not assignment:
        raise HTTPException(status_code=403, detail="You are not assigned as a reviewer for this round, or you already decided")

    if payload.decision == ReviewDecision.APPROVED.value:
        unchecked = _get_unchecked_required_items(db, review_id)
        if unchecked:
            labels = [item.label for item in unchecked[:5]]
            raise HTTPException(
                status_code=400,
                detail={
                    "message": f"Cannot approve: {len(unchecked)} required checklist item(s) not verified",
                    "uncheckedItems": labels,
                    "uncheckedCount": len(unchecked),
                },
            )

    now = datetime.now(UTC)
    assignment.decision = payload.decision
    assignment.decision_at = now
    assignment.comments = payload.comments
    db.flush()

    _log_event(db, review, "decision", actor.actor_id, {
        "decision": payload.decision,
        "comments": payload.comments,
        "round": review.current_round,
    })

    _evaluate_review_outcome(db, review)

    write_audit_event(
        db=db, fund_id=fund_id, actor_id=actor.actor_id,
        action=f"document_review.decision.{payload.decision.lower()}", entity_type="DocumentReview",
        entity_id=str(review_id), before=None,
        after={"decision": payload.decision, "review_status": review.status},
    )

    db.commit()
    return {
        "reviewId": str(review_id),
        "yourDecision": payload.decision,
        "reviewStatus": review.status,
        "finalDecision": review.final_decision,
    }


# ── Finalize (force-decide) ─────────────────────────────────────────

@router.post("/{review_id}/finalize")
def finalize_review(
    fund_id: uuid.UUID,
    review_id: uuid.UUID,
    payload: FinalizePayload,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP"])),
) -> dict[str, Any]:
    """GP/Admin force-decides the review regardless of pending assignments."""
    review = _get_review(db, fund_id, review_id)

    if review.status in (ReviewStatus.APPROVED.value, ReviewStatus.REJECTED.value, ReviewStatus.CANCELLED.value):
        raise HTTPException(status_code=409, detail=f"Review is already {review.status}")

    now = datetime.now(UTC)
    review.status = payload.decision
    review.final_decision = payload.decision
    review.decided_by = actor.actor_id
    review.decided_at = now
    db.flush()

    _log_event(db, review, "finalized", actor.actor_id, {
        "decision": payload.decision,
        "comments": payload.comments,
        "force": True,
    })

    write_audit_event(
        db=db, fund_id=fund_id, actor_id=actor.actor_id,
        action=f"document_review.finalized.{payload.decision.lower()}", entity_type="DocumentReview",
        entity_id=str(review_id), before={"status": review.status},
        after={"status": payload.decision, "decided_by": actor.actor_id},
    )

    db.commit()
    return {"reviewId": str(review_id), "status": review.status, "finalDecision": review.final_decision}


# ── Resubmit ─────────────────────────────────────────────────────────

@router.post("/{review_id}/resubmit")
def resubmit_for_review(
    fund_id: uuid.UUID,
    review_id: uuid.UUID,
    document_version_id: uuid.UUID | None = None,
    notes: str | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM"])),
) -> dict[str, Any]:
    """Resubmit a document after revision was requested."""
    review = _get_review(db, fund_id, review_id)

    if review.status != ReviewStatus.REVISION_REQUESTED.value:
        raise HTTPException(status_code=409, detail=f"Cannot resubmit: review is {review.status}, expected REVISION_REQUESTED")

    review.status = ReviewStatus.SUBMITTED.value
    review.revision_count += 1
    review.current_round += 1
    review.final_decision = None
    review.decided_by = None
    review.decided_at = None
    if document_version_id:
        review.document_version_id = document_version_id
    if notes:
        review.review_notes = notes
    db.flush()

    _log_event(db, review, "resubmitted", actor.actor_id, {
        "round": review.current_round,
        "revision_count": review.revision_count,
        "new_version_id": str(document_version_id) if document_version_id else None,
    })

    write_audit_event(
        db=db, fund_id=fund_id, actor_id=actor.actor_id,
        action="document_review.resubmitted", entity_type="DocumentReview",
        entity_id=str(review_id), before={"status": "REVISION_REQUESTED"},
        after={"status": "SUBMITTED", "round": review.current_round},
    )

    db.commit()
    return {"reviewId": str(review_id), "status": review.status, "currentRound": review.current_round}


# ── AI Analysis ──────────────────────────────────────────────────────

@router.post("/{review_id}/ai-analyze")
def trigger_ai_analysis(
    fund_id: uuid.UUID,
    review_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE"])),
) -> dict[str, Any]:
    """Trigger AI pre-analysis of all checklist items for a document review.

    The AI searches for document content relevant to each checklist item
    and produces a finding (FOUND / NOT_FOUND / UNCLEAR) with confidence
    and supporting excerpt.
    """
    review = _get_review(db, fund_id, review_id)

    if review.status in (ReviewStatus.CANCELLED.value,):
        raise HTTPException(status_code=409, detail=f"Cannot analyze: review is {review.status}")

    _log_event(db, review, "ai_analysis_started", actor.actor_id, {})

    write_audit_event(
        db=db, fund_id=fund_id, actor_id=actor.actor_id,
        action="document_review.ai_analysis_started", entity_type="DocumentReview",
        entity_id=str(review_id), before=None, after={"triggered_by": actor.actor_id},
    )

    db.commit()

    from app.domains.credit.documents.services.ai_review_analyzer import analyze_review_checklist

    def _run_analysis() -> None:
        analysis_db = async_session_factory()
        try:
            r = analysis_db.execute(
                select(DocumentReview).where(DocumentReview.id == review_id),
            ).scalar_one()
            stats = analyze_review_checklist(analysis_db, review=r, fund_id=fund_id)

            _log_event(analysis_db, r, "ai_analysis_completed", "ai-engine", {
                "stats": stats,
            })
            analysis_db.commit()

            logger.info(
                "AI review analysis completed review=%s stats=%s",
                review_id, stats,
            )
        except Exception:
            logger.error("AI review analysis failed review=%s", review_id, exc_info=True)
            analysis_db.rollback()
        finally:
            analysis_db.close()

    from app.core.config import settings
    if getattr(settings, "USE_SERVICE_BUS", False):
        from app.services.azure.servicebus_client import send_to_queue
        send_to_queue("memo-generation", {
            "fund_id": str(fund_id),
            "review_id": str(review_id),
            "task": "ai_review_analysis",
            "triggered_by": actor.actor_id,
        }, stage="doc_review")
        return {
            "reviewId": str(review_id),
            "status": "queued",
            "dispatch": "service_bus",
            "message": "AI analysis queued. Results will appear on checklist items.",
        }

    background_tasks.add_task(_run_analysis)
    return {
        "reviewId": str(review_id),
        "status": "started",
        "dispatch": "background_tasks",
        "message": "AI analysis started. Results will appear on checklist items.",
    }


# ── Checklist ─────────────────────────────────────────────────────────

class CheckItemPayload(BaseModel):
    notes: str | None = None


@router.get("/{review_id}/checklist")
def get_review_checklist(
    fund_id: uuid.UUID,
    review_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE", "AUDITOR"])),
) -> dict[str, Any]:
    """Return the checklist items for a review."""
    _get_review(db, fund_id, review_id)
    items = _get_checklist_items(db, review_id)

    total = len(items)
    checked = sum(1 for i in items if i.is_checked)
    required = sum(1 for i in items if i.is_required)
    required_checked = sum(1 for i in items if i.is_required and i.is_checked)

    return {
        "reviewId": str(review_id),
        "total": total,
        "checked": checked,
        "required": required,
        "requiredChecked": required_checked,
        "allRequiredComplete": required_checked >= required,
        "completionPct": round(checked / total * 100, 1) if total > 0 else 100,
        "items": [_checklist_item_to_dict(i) for i in items],
    }


@router.post("/{review_id}/checklist/{item_id}/check")
def check_item(
    fund_id: uuid.UUID,
    review_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: CheckItemPayload | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE"])),
) -> dict[str, Any]:
    """Mark a checklist item as verified."""
    review = _get_review(db, fund_id, review_id)
    item = db.execute(
        select(ReviewChecklistItem).where(
            ReviewChecklistItem.id == item_id,
            ReviewChecklistItem.review_id == review_id,
        ),
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    item.is_checked = True
    item.checked_by = actor.actor_id
    item.checked_at = datetime.now(UTC)
    if payload and payload.notes:
        item.notes = payload.notes
    db.flush()

    _log_event(db, review, "checklist_checked", actor.actor_id, {
        "item_id": str(item_id),
        "label": item.label,
        "category": item.category,
    })

    db.commit()
    return _checklist_item_to_dict(item)


@router.post("/{review_id}/checklist/{item_id}/uncheck")
def uncheck_item(
    fund_id: uuid.UUID,
    review_id: uuid.UUID,
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard=Depends(require_role(["ADMIN", "GP", "INVESTMENT_TEAM", "COMPLIANCE"])),
) -> dict[str, Any]:
    """Unmark a checklist item."""
    review = _get_review(db, fund_id, review_id)
    item = db.execute(
        select(ReviewChecklistItem).where(
            ReviewChecklistItem.id == item_id,
            ReviewChecklistItem.review_id == review_id,
        ),
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    item.is_checked = False
    item.checked_by = None
    item.checked_at = None
    db.flush()

    _log_event(db, review, "checklist_unchecked", actor.actor_id, {
        "item_id": str(item_id),
        "label": item.label,
    })

    db.commit()
    return _checklist_item_to_dict(item)


# ── Helpers ──────────────────────────────────────────────────────────

def _get_review(db: Session, fund_id: uuid.UUID, review_id: uuid.UUID) -> DocumentReview:
    review = db.execute(
        select(DocumentReview).where(
            DocumentReview.id == review_id, DocumentReview.fund_id == fund_id,
        ),
    ).scalar_one_or_none()
    if not review:
        raise HTTPException(status_code=404, detail="Document review not found")
    return review


def _log_event(
    db: Session,
    review: DocumentReview,
    event_type: str,
    actor_id: str,
    detail: dict | None = None,
) -> None:
    db.add(ReviewEvent(
        fund_id=review.fund_id,
        review_id=review.id,
        event_type=event_type,
        actor_id=actor_id,
        detail=detail,
    ))
    db.flush()


def _evaluate_review_outcome(db: Session, review: DocumentReview) -> None:
    """Check if all required reviewers have decided and update review status accordingly."""
    assignments = list(
        db.execute(
            select(ReviewAssignment).where(
                ReviewAssignment.review_id == review.id,
                ReviewAssignment.round_number == review.current_round,
                ReviewAssignment.is_required.is_(True),
            ),
        ).scalars().all(),
    )

    if not assignments:
        return

    undecided = [a for a in assignments if a.decision is None]
    if undecided:
        return

    decisions = [a.decision for a in assignments]

    if ReviewDecision.REJECTED.value in decisions:
        review.status = ReviewStatus.REJECTED.value
        review.final_decision = ReviewDecision.REJECTED.value
    elif ReviewDecision.REVISION_REQUESTED.value in decisions:
        review.status = ReviewStatus.REVISION_REQUESTED.value
        review.final_decision = ReviewDecision.REVISION_REQUESTED.value
    else:
        review.status = ReviewStatus.APPROVED.value
        review.final_decision = ReviewDecision.APPROVED.value

    review.decided_at = datetime.now(UTC)
    review.decided_by = "consensus"
    db.flush()


def _create_checklist_from_template(
    db: Session,
    review: DocumentReview,
) -> list[ReviewChecklistItem]:
    """Auto-generate checklist items from the template for the document type."""
    template = get_checklist_template(review.document_type)
    items = []
    for idx, tmpl in enumerate(template):
        item = ReviewChecklistItem(
            fund_id=review.fund_id,
            review_id=review.id,
            sort_order=idx,
            category=tmpl.category,
            label=tmpl.label,
            description=tmpl.description,
            is_required=tmpl.is_required,
        )
        db.add(item)
        items.append(item)
    db.flush()
    return items


def _get_checklist_items(db: Session, review_id: uuid.UUID) -> list[ReviewChecklistItem]:
    return list(
        db.execute(
            select(ReviewChecklistItem)
            .where(ReviewChecklistItem.review_id == review_id)
            .order_by(ReviewChecklistItem.sort_order),
        ).scalars().all(),
    )


def _get_unchecked_required_items(db: Session, review_id: uuid.UUID) -> list[ReviewChecklistItem]:
    return list(
        db.execute(
            select(ReviewChecklistItem).where(
                ReviewChecklistItem.review_id == review_id,
                ReviewChecklistItem.is_required.is_(True),
                ReviewChecklistItem.is_checked.is_(False),
            )
            .order_by(ReviewChecklistItem.sort_order),
        ).scalars().all(),
    )


def _checklist_item_to_dict(i: ReviewChecklistItem) -> dict[str, Any]:
    return {
        "id": str(i.id),
        "sortOrder": i.sort_order,
        "category": i.category,
        "label": i.label,
        "description": i.description,
        "isRequired": i.is_required,
        "isChecked": i.is_checked,
        "checkedBy": i.checked_by,
        "checkedAt": i.checked_at.isoformat() if i.checked_at else None,
        "notes": i.notes,
        "aiFinding": i.ai_finding,
    }


def _review_to_dict(r: DocumentReview) -> dict[str, Any]:
    return {
        "id": str(r.id),
        "fundId": str(r.fund_id),
        "documentId": str(r.document_id),
        "documentVersionId": str(r.document_version_id) if r.document_version_id else None,
        "dealId": str(r.deal_id) if r.deal_id else None,
        "assetId": str(r.asset_id) if r.asset_id else None,
        "title": r.title,
        "documentType": r.document_type,
        "status": r.status,
        "priority": r.priority,
        "submittedBy": r.submitted_by,
        "submittedAt": r.submitted_at.isoformat() if r.submitted_at else None,
        "dueDate": r.due_date.isoformat() if r.due_date else None,
        "reviewNotes": r.review_notes,
        "finalDecision": r.final_decision,
        "decidedBy": r.decided_by,
        "decidedAt": r.decided_at.isoformat() if r.decided_at else None,
        "revisionCount": r.revision_count,
        "currentRound": r.current_round,
        "routingBasis": r.routing_basis,
        "createdAt": r.created_at.isoformat() if r.created_at else None,
    }

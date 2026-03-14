"""Task Inbox -- cross-domain aggregation of pending user actions.

Endpoint:
  GET /dashboard/task-inbox -> pending tasks across all modules

Aggregates:
  - Execution actions still open
  - Pipeline deals awaiting IC decision
  - Document reviews pending action
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.shared.enums import Role

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/task-inbox")
async def task_inbox(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict[str, Any]:
    """Return all pending tasks grouped by module, filtered by actor role."""
    roles = {r.value if hasattr(r, "value") else r for r in (actor.roles or [])}
    is_admin = Role.ADMIN.value in roles

    sections: list[dict[str, Any]] = []
    total = 0

    actions = await _action_tasks(db, fund_id, roles, is_admin)
    if actions:
        sections.append(actions)
        total += actions["count"]

    pipeline = await _pipeline_tasks(db, fund_id, roles, is_admin)
    if pipeline:
        sections.append(pipeline)
        total += pipeline["count"]

    doc_reviews = await _document_review_tasks(db, fund_id, roles, is_admin, actor)
    if doc_reviews:
        sections.append(doc_reviews)
        total += doc_reviews["count"]

    return {
        "totalPending": total,
        "sections": sections,
        "asOf": dt.datetime.now(dt.UTC).isoformat(),
    }


# -- Execution Actions -------------------------------------------------------

async def _action_tasks(
    db: AsyncSession,
    fund_id: uuid.UUID,
    roles: set[str],
    is_admin: bool,
) -> dict[str, Any] | None:
    relevant_roles = {"INVESTMENT_TEAM", "COMPLIANCE", "ADMIN", "GP"}
    if not is_admin and not roles.intersection(relevant_roles):
        return None

    from app.domains.credit.modules.actions.models import Action

    result = await db.execute(
        select(Action).where(
            Action.fund_id == fund_id,
            Action.status.in_(["Open", "In Progress", "Pending Evidence", "Under Review"]),
        )
        .order_by(Action.due_date.asc().nullslast(), Action.created_at.desc())
        .limit(50),
    )
    rows = list(result.scalars().all())

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


# -- Pipeline Deals (IC Decision) -------------------------------------------

async def _pipeline_tasks(
    db: AsyncSession,
    fund_id: uuid.UUID,
    roles: set[str],
    is_admin: bool,
) -> dict[str, Any] | None:
    relevant_roles = {"ADMIN", "INVESTMENT_TEAM", "GP", "COMPLIANCE"}
    if not is_admin and not roles.intersection(relevant_roles):
        return None

    from app.domains.credit.modules.deals.models import PipelineDeal

    result = await db.execute(
        select(PipelineDeal).where(
            PipelineDeal.fund_id == fund_id,
            PipelineDeal.is_archived.is_(False),
            PipelineDeal.intelligence_status == "READY",
            PipelineDeal.approved_deal_id.is_(None),
        )
        .order_by(PipelineDeal.created_at.desc())
        .limit(50),
    )
    rows = list(result.scalars().all())

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


# -- Document Reviews --------------------------------------------------------

async def _document_review_tasks(
    db: AsyncSession,
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

    result = await db.execute(
        stmt.order_by(DocumentReview.due_date.asc().nullslast(), DocumentReview.submitted_at.desc())
        .limit(50),
    )
    rows = list(result.scalars().all())

    if not rows:
        return None

    today = dt.date.today()
    items = []
    for r in rows:
        overdue = r.due_date is not None and r.due_date < today
        items.append({
            "id": str(r.id),
            "title": r.title,
            "subtitle": f"{r.document_type} -- {r.submitted_by}",
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

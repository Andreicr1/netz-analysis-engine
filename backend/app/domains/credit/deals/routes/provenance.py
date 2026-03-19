"""Credit AI provenance, memo timeline, and decision audit endpoints."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.models import AuditEvent
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.deals.models.deals import Deal
from app.domains.credit.deals.models.ic_memos import ICMemo
from app.domains.credit.deals.schemas.provenance import (
    AIProvenanceOut,
    DecisionAuditEventOut,
    DecisionAuditOut,
    MemoTimelineEventOut,
    MemoTimelineOut,
    layer_label,
)
from app.domains.credit.documents.models.review import DocumentReview, ReviewEvent

router = APIRouter(prefix="/funds/{fund_id}/deals", tags=["Deals — Provenance"])


async def _get_deal_or_404(
    db: AsyncSession, fund_id: uuid.UUID, deal_id: uuid.UUID
) -> Deal:
    result = await db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id)
    )
    deal = result.scalar_one_or_none()
    if deal is None:
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


# ── Endpoint 1: AI Provenance ─────────────────────────────────────


@router.get(
    "/{deal_id}/documents/{document_id}/ai-provenance",
    response_model=AIProvenanceOut,
    summary="Document AI classification provenance",
)
async def get_ai_provenance(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> AIProvenanceOut:
    await _get_deal_or_404(db, fund_id, deal_id)

    result = await db.execute(
        select(DocumentReview).where(
            DocumentReview.fund_id == fund_id,
            DocumentReview.deal_id == deal_id,
            DocumentReview.document_id == document_id,
        )
    )
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(status_code=404, detail="Document review not found")

    # Count review events
    count_result = await db.execute(
        select(func.count()).select_from(ReviewEvent).where(
            ReviewEvent.review_id == review.id,
        )
    )
    review_count = count_result.scalar() or 0

    # Extract embedding metadata from metadata_json if present
    meta = review.metadata_json or {}
    embedding_model = meta.get("embedding_model")
    embedding_dim = meta.get("embedding_dim")

    return AIProvenanceOut(
        document_id=review.document_id,
        classification_result=review.document_type,
        classification_confidence=review.classification_confidence,
        classification_layer=review.classification_layer,
        classification_layer_label=layer_label(review.classification_layer),
        classification_model=review.classification_model,
        routing_basis=review.routing_basis,
        embedding_model=embedding_model,
        embedding_dim=embedding_dim,
        processed_at=review.submitted_at,
        review_count=review_count,
        current_review_status=review.status,
    )


# ── Endpoint 2: IC Memo Timeline ─────────────────────────────────


@router.get(
    "/{deal_id}/ic-memo/timeline",
    response_model=MemoTimelineOut,
    summary="IC memo version and review timeline",
)
async def get_memo_timeline(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> MemoTimelineOut:
    await _get_deal_or_404(db, fund_id, deal_id)

    # Fetch all memo versions for this deal
    memo_result = await db.execute(
        select(ICMemo)
        .where(ICMemo.deal_id == deal_id)
        .order_by(ICMemo.version.asc())
    )
    memos = list(memo_result.scalars().all())

    events: list[MemoTimelineEventOut] = []

    for memo in memos:
        # Memo creation/update event
        event_type = "memo_created" if memo.version == 1 else "memo_updated"
        events.append(MemoTimelineEventOut(
            event_type=event_type,
            version=memo.version,
            actor_id=memo.created_by,
            timestamp=memo.created_at,
            metadata={"recommendation": memo.recommendation} if memo.recommendation else None,
        ))

        # Committee votes as review events
        votes = memo.committee_votes or []
        for vote in votes:
            if isinstance(vote, dict) and vote.get("vote") and vote["vote"] != "PENDING":
                vote_type_map = {
                    "APPROVED": "review_approved",
                    "REJECTED": "review_rejected",
                }
                events.append(MemoTimelineEventOut(
                    event_type=vote_type_map.get(vote["vote"], "review_submitted"),
                    version=memo.version,
                    actor_id=vote.get("email"),
                    actor_email=vote.get("email"),
                    actor_capacity=vote.get("actor_capacity"),
                    rationale=vote.get("rationale"),
                    timestamp=datetime.fromisoformat(vote["signed_at"]) if vote.get("signed_at") else memo.updated_at,
                    metadata={"vote": vote["vote"]},
                ))

    # Sort all events chronologically
    events.sort(key=lambda e: e.timestamp)

    return MemoTimelineOut(
        deal_id=deal_id,
        memo_count=len(memos),
        events=events,
        computed_at=datetime.now(timezone.utc),
    )


# ── Endpoint 3: Decision Audit Trail ─────────────────────────────


@router.get(
    "/{deal_id}/decision-audit",
    response_model=DecisionAuditOut,
    summary="Deal decision and stage change audit trail",
)
async def get_decision_audit(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> DecisionAuditOut:
    await _get_deal_or_404(db, fund_id, deal_id)

    result = await db.execute(
        select(AuditEvent)
        .where(
            AuditEvent.entity_type == "Deal",
            AuditEvent.entity_id == str(deal_id),
            AuditEvent.fund_id == fund_id,
        )
        .order_by(AuditEvent.created_at.asc())
    )
    audit_events = list(result.scalars().all())

    events: list[DecisionAuditEventOut] = []

    for ae in audit_events:
        before = ae.before_state or {}
        after = ae.after_state or {}

        from_stage = before.get("stage") if isinstance(before, dict) else None
        to_stage = after.get("stage") if isinstance(after, dict) else None

        # Determine event type from action
        action_str = ae.action or ""
        if "stage" in action_str or (from_stage and to_stage and from_stage != to_stage):
            event_type = "stage_change"
        elif "decision" in action_str:
            event_type = "decision"
        elif "condition" in action_str and "resolve" in action_str:
            event_type = "condition_resolved"
        elif "condition" in action_str:
            event_type = "condition_added"
        elif "review" in action_str or "document" in action_str:
            event_type = "document_reviewed"
        else:
            event_type = action_str

        # Extract actor context from after_state metadata
        actor_email = after.get("actor_email") if isinstance(after, dict) else None
        actor_capacity = after.get("actor_capacity") if isinstance(after, dict) else None
        rationale = after.get("rationale") if isinstance(after, dict) else None

        # Build metadata (extra context without duplicating top-level fields)
        meta = {}
        if isinstance(after, dict):
            for key in ("rejection_code", "rejection_notes", "trigger", "extra_audit"):
                if key in after:
                    meta[key] = after[key]
        if not meta:
            meta = None

        events.append(DecisionAuditEventOut(
            event_type=event_type,
            from_stage=from_stage,
            to_stage=to_stage,
            action=action_str,
            actor_id=ae.actor_id,
            actor_email=actor_email,
            actor_capacity=actor_capacity,
            rationale=rationale,
            timestamp=ae.created_at,
            metadata=meta,
        ))

    return DecisionAuditOut(
        deal_id=deal_id,
        events=events,
        total_events=len(events),
        computed_at=datetime.now(timezone.utc),
    )

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.deals.models.deals import Deal
from app.domains.credit.deals.models.ic_memos import ICMemo
from app.domains.credit.deals.schemas.deals import ConditionResolvePayload, ICMemoOut

router = APIRouter(tags=["IC Memos"])


async def _get_latest_memo(db: AsyncSession, deal_id: uuid.UUID) -> ICMemo | None:
    result = await db.execute(
        select(ICMemo).where(ICMemo.deal_id == deal_id).order_by(ICMemo.version.desc()),
    )
    return result.scalar_one_or_none()


@router.post("/funds/{fund_id}/deals/{deal_id}/ic-memo", response_model=dict)
async def create_ic_memo(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict:
    result = await db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if "executive_summary" not in payload:
        raise HTTPException(status_code=400, detail="executive_summary is required")

    # Determine next version
    latest = await _get_latest_memo(db, deal_id)
    next_version = (latest.version + 1) if latest else 1

    memo = ICMemo(
        deal_id=deal_id,
        executive_summary=payload["executive_summary"],
        risks=payload.get("risks"),
        mitigants=payload.get("mitigants"),
        recommendation=payload.get("recommendation"),
        conditions=payload.get("conditions", []),
        version=next_version,
        memo_blob_url=payload.get("memo_blob_url"),
    )
    db.add(memo)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="ic_memo.created",
        entity_type="ICMemo",
        entity_id=str(memo.id),
        before=None,
        after={
            "deal_id": str(deal_id),
            "version": next_version,
            "recommendation": memo.recommendation,
            "conditions_count": len(memo.conditions),
        },
    )

    await db.commit()
    return {"memo_id": str(memo.id), "version": next_version}


@router.get("/funds/{fund_id}/deals/{deal_id}/ic-memo", response_model=ICMemoOut)
async def get_latest_ic_memo(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ICMemoOut:
    result = await db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    memo = await _get_latest_memo(db, deal_id)
    if not memo:
        raise HTTPException(status_code=404, detail="No IC Memo found for this deal")

    return ICMemoOut.model_validate(memo)


@router.patch("/funds/{fund_id}/deals/{deal_id}/ic-memo/conditions", response_model=dict)
async def resolve_condition(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    payload: ConditionResolvePayload,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict:
    result = await db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    memo = await _get_latest_memo(db, deal_id)
    if not memo:
        raise HTTPException(status_code=404, detail="No IC Memo found for this deal")

    # Find the condition by id
    conditions = copy.deepcopy(memo.conditions or [])
    target = None
    for cond in conditions:
        if cond.get("id") == payload.condition_id:
            target = cond
            break

    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"Condition '{payload.condition_id}' not found in IC Memo v{memo.version}",
        )

    if target.get("status") != "open":
        raise HTTPException(
            status_code=409,
            detail=f"Condition '{payload.condition_id}' is already {target.get('status')}",
        )

    # Update the condition
    now = datetime.now(UTC).isoformat()
    target["status"] = payload.status
    target["resolved_at"] = now
    target["resolved_by"] = actor.id
    if payload.evidence_docs:
        target["evidence_docs"] = payload.evidence_docs
    if payload.notes:
        target["notes"] = payload.notes

    # Append to condition_history
    history = copy.deepcopy(memo.condition_history or [])
    history.append({
        "timestamp": now,
        "event": f"condition_{payload.status}",
        "condition_id": payload.condition_id,
        "condition_title": target.get("title", ""),
        "resolved_by": actor.id,
        "evidence_docs": payload.evidence_docs,
        "memo_version": memo.version,
    })

    # Write back (JSONB mutation requires reassignment for SQLAlchemy dirty tracking)
    memo.conditions = conditions
    memo.condition_history = history
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action=f"ic_memo.condition.{payload.status}",
        entity_type="ICMemo",
        entity_id=str(memo.id),
        before={"condition_id": payload.condition_id, "status": "open"},
        after={
            "condition_id": payload.condition_id,
            "status": payload.status,
            "evidence_docs": payload.evidence_docs,
            "notes": payload.notes,
        },
    )

    # Check if all conditions are now resolved/waived
    all_resolved = all(
        c.get("status") != "open"
        for c in conditions
    )

    await db.commit()
    return {
        "memo_id": str(memo.id),
        "condition_id": payload.condition_id,
        "status": payload.status,
        "all_resolved": all_resolved,
    }


@router.get("/funds/{fund_id}/deals/{deal_id}/ic-memo/voting-status", response_model=dict)
async def get_voting_status(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict:
    """Return structured IC Committee voting status with quorum tracking."""
    result = await db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    memo = await _get_latest_memo(db, deal_id)
    if not memo:
        raise HTTPException(status_code=404, detail="No IC Memo found for this deal")

    members = memo.committee_members or []
    votes = memo.committee_votes or []
    conditions = memo.conditions or []

    total_members = len(members)
    majority = (total_members // 2) + 1 if total_members > 0 else 1

    votes_cast = [v for v in votes if v.get("vote")]
    approvals = [v for v in votes_cast if v.get("vote") == "APPROVE"]
    rejections = [v for v in votes_cast if v.get("vote") == "REFUSE"]

    open_conditions = [c for c in conditions if c.get("status", "open") == "open"]
    resolved_conditions = [c for c in conditions if c.get("status") in ("resolved", "waived")]

    if memo.recommendation in ("APPROVED", "REJECTED"):
        voting_state = "decided"
    elif memo.esignature_status in ("SENT", "IN_PROCESS"):
        voting_state = "in_progress"
    elif memo.esignature_status == "NOT_SENT" or not memo.esignature_status:
        voting_state = "not_started"
    else:
        voting_state = memo.esignature_status.lower() if memo.esignature_status else "unknown"

    member_details = []
    vote_map = {v.get("email"): v for v in votes}
    for email in members:
        v = vote_map.get(email, {})
        member_details.append({
            "email": email,
            "vote": v.get("vote"),
            "signedAt": v.get("signed_at"),
            "signerStatus": v.get("signer_status"),
        })

    return {
        "memoId": str(memo.id),
        "version": memo.version,
        "recommendation": memo.recommendation,
        "esignatureStatus": memo.esignature_status,
        "votingState": voting_state,
        "quorum": {
            "totalMembers": total_members,
            "majorityRequired": majority,
            "votesCast": len(votes_cast),
            "approvals": len(approvals),
            "rejections": len(rejections),
            "pending": total_members - len(votes_cast),
            "quorumReached": len(votes_cast) >= majority,
        },
        "members": member_details,
        "conditions": {
            "total": len(conditions),
            "open": len(open_conditions),
            "resolved": len(resolved_conditions),
            "allResolved": len(open_conditions) == 0 and len(conditions) > 0,
            "items": conditions,
        },
        "conditionHistory": memo.condition_history or [],
    }

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.deals.enums import DealStage
from app.domains.credit.deals.models.deals import Deal
from app.domains.credit.deals.models.qualification import DealQualification
from app.domains.credit.deals.schemas.deals import DealCreate, DealDecision, DealOut
from app.domains.credit.deals.services.qualification import run_minimum_qualification
from app.domains.credit.deals.services.stage_transition import (
    VALID_TRANSITIONS,
    transition_deal_stage,
)
from app.domains.credit.modules.deals.models import DealStageHistory

router = APIRouter(prefix="/funds/{fund_id}/deals", tags=["Deals"])


@router.post("", response_model=DealOut, status_code=status.HTTP_201_CREATED)
async def create_deal(
    fund_id: uuid.UUID,
    payload: DealCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> DealOut:
    deal = Deal(fund_id=fund_id, **payload.model_dump())
    db.add(deal)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="deal.intake.created",
        entity_type="Deal",
        entity_id=str(deal.id),
        before=None,
        after=payload.model_dump(),
    )

    # Automatic deterministic qualification
    passed, summary, rejection_code = run_minimum_qualification(deal)
    qual = DealQualification(deal_id=deal.id, passed=passed, summary=summary)
    db.add(qual)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id="system",
        request_id="workflow",
        action="deal.qualification.persisted",
        entity_type="DealQualification",
        entity_id=str(qual.id),
        before=None,
        after={
            "deal_id": str(deal.id),
            "passed": passed,
            "summary": summary,
            "rejection_code": rejection_code.value if rejection_code else None,
        },
    )

    if passed:
        await transition_deal_stage(
            db, deal, DealStage.QUALIFIED,
            actor_id="system", fund_id=fund_id,
            extra_audit={"trigger": "auto_qualification"},
        )
    else:
        deal.rejection_code = rejection_code
        deal.rejection_notes = summary
        await transition_deal_stage(
            db, deal, DealStage.REJECTED,
            actor_id="system", fund_id=fund_id,
            extra_audit={
                "trigger": "auto_qualification",
                "rejection_code": rejection_code.value if rejection_code else None,
            },
        )

    await db.commit()
    await db.refresh(deal)
    return DealOut.model_validate(deal)


@router.get("", response_model=list[DealOut])
async def list_deals(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[DealOut]:
    result = await db.execute(
        select(Deal).where(Deal.fund_id == fund_id).limit(limit).offset(offset),
    )
    return [DealOut.model_validate(row) for row in result.scalars().all()]


@router.patch("/{deal_id}/decision", response_model=DealOut)
async def decide_deal(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    payload: DealDecision,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> DealOut:
    result = await db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if payload.stage == DealStage.REJECTED:
        deal.rejection_code = payload.rejection_code
        deal.rejection_notes = payload.rejection_notes

    try:
        await transition_deal_stage(
            db,
            deal,
            payload.stage,
            actor_id=actor.id,
            fund_id=fund_id,
            extra_audit={
                "rejection_code": payload.rejection_code.value if payload.rejection_code else None,
                "rejection_notes": payload.rejection_notes,
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    await db.refresh(deal)
    return DealOut.model_validate(deal)


@router.get("/{deal_id}/stage-timeline", response_model=dict)
async def get_deal_stage_timeline(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict:
    """Return the deal's stage history as a timeline plus allowed next transitions."""
    result = await db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    )
    deal = result.scalar_one_or_none()
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    history_result = await db.execute(
        select(DealStageHistory)
        .where(DealStageHistory.deal_id == deal_id, DealStageHistory.fund_id == fund_id)
        .order_by(DealStageHistory.changed_at.asc()),
    )
    history = list(history_result.scalars().all())

    stage_order = [s.value for s in DealStage if s not in (DealStage.REJECTED, DealStage.CLOSED)]
    current_stage = deal.stage if isinstance(deal.stage, str) else deal.stage.value
    current_idx = stage_order.index(current_stage) if current_stage in stage_order else -1

    nodes = []
    for i, stage_val in enumerate(stage_order):
        if i < current_idx:
            state = "Positive"
        elif i == current_idx:
            state = "Critical"
        else:
            state = "Neutral"

        entry = next((h for h in history if h.to_stage == stage_val), None)
        nodes.append({
            "stage": stage_val,
            "state": state,
            "reachedAt": entry.changed_at.isoformat() if entry else None,
            "rationale": entry.rationale if entry else None,
        })

    if current_stage in (DealStage.REJECTED.value, "REJECTED"):
        nodes.append({
            "stage": "REJECTED",
            "state": "Negative",
            "reachedAt": next(
                (h.changed_at.isoformat() for h in history if h.to_stage == "REJECTED"),
                None,
            ),
            "rationale": deal.rejection_notes,
        })

    try:
        current_enum = DealStage(current_stage)
        allowed_next = [s.value for s in VALID_TRANSITIONS.get(current_enum, [])]
    except ValueError:
        allowed_next = []

    timeline_events = [
        {
            "fromStage": h.from_stage,
            "toStage": h.to_stage,
            "changedAt": h.changed_at.isoformat() if h.changed_at else None,
            "rationale": h.rationale,
        }
        for h in history
    ]

    return {
        "dealId": str(deal_id),
        "currentStage": current_stage,
        "nodes": nodes,
        "allowedTransitions": allowed_next,
        "timeline": timeline_events,
    }

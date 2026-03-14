from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.actions.schemas.actions import ActionCreate, ActionOut, ActionUpdate
from app.domains.credit.documents.models.evidence import EvidenceDocument
from app.domains.credit.modules.actions.models import Action as ExecutionAction

router = APIRouter(tags=["Actions"])


@router.post("/funds/{fund_id}/actions", response_model=ActionOut, status_code=status.HTTP_201_CREATED)
async def create_action(
    fund_id: uuid.UUID,
    payload: ActionCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ActionOut:
    action = ExecutionAction(
        fund_id=fund_id,
        title=payload.title,
        status="OPEN",
        description=None,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(action)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="action.created",
        entity_type="ExecutionAction",
        entity_id=str(action.id),
        before=None,
        after={"title": payload.title},
    )

    await db.commit()
    await db.refresh(action)
    return ActionOut.model_validate(action)


@router.get("/funds/{fund_id}/actions", response_model=list[ActionOut])
async def list_actions(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ActionOut]:
    result = await db.execute(
        select(ExecutionAction)
        .where(ExecutionAction.fund_id == fund_id)
        .limit(limit)
        .offset(offset),
    )
    return [ActionOut.model_validate(row) for row in result.scalars().all()]


@router.patch("/funds/{fund_id}/actions/{action_id}", response_model=ActionOut)
async def update_action(
    fund_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: ActionUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ActionOut:
    result = await db.execute(
        select(ExecutionAction).where(
            ExecutionAction.fund_id == fund_id, ExecutionAction.id == action_id,
        ),
    )
    action = result.scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404, detail="Not found")

    # Governance rule: cannot close without evidence
    if payload.status == "CLOSED":
        evidence_result = await db.execute(
            select(func.count())
            .select_from(EvidenceDocument)
            .where(EvidenceDocument.fund_id == fund_id, EvidenceDocument.action_id == action.id),
        )
        evidence_count = evidence_result.scalar_one()
        if evidence_count == 0:
            await write_audit_event(
                db=db,
                fund_id=fund_id,
                actor_id=actor.id,
                action="action.close_blocked_missing_evidence",
                entity_type="ExecutionAction",
                entity_id=str(action.id),
                before={"status": action.status},
                after={"attempted_status": "CLOSED"},
            )
            await db.commit()
            raise HTTPException(status_code=400, detail="Cannot close Action without evidence")

    before = {"status": action.status, "description": action.description}
    action.status = payload.status
    if payload.evidence_notes is not None:
        action.description = payload.evidence_notes
    action.updated_by = actor.id
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="action.updated",
        entity_type="ExecutionAction",
        entity_id=str(action.id),
        before=before,
        after=payload.model_dump(),
    )

    await db.commit()
    await db.refresh(action)
    return ActionOut.model_validate(action)

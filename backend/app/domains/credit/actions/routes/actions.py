from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.actions.schemas.actions import ActionCreate, ActionOut, ActionUpdate
from app.domains.credit.documents.models.evidence import EvidenceDocument
from app.domains.credit.modules.actions.models import Action as ExecutionAction


def _limit(limit: int = Query(default=50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(default=0, ge=0)) -> int:
    return offset


router = APIRouter(tags=["Actions"], dependencies=[Depends(require_fund_access())])


@router.post("/funds/{fund_id}/actions", response_model=ActionOut, status_code=status.HTTP_201_CREATED)
def create_action(
    fund_id: uuid.UUID,
    payload: ActionCreate,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "ADMIN"])),
):
    action = ExecutionAction(
        fund_id=fund_id,
        title=payload.title,
        status="OPEN",
        description=None,
        created_by=actor.id,
        updated_by=actor.id,
    )
    db.add(action)
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="action.created",
        entity_type="ExecutionAction",
        entity_id=str(action.id),
        before=None,
        after={"title": payload.title},
    )

    db.commit()
    db.refresh(action)
    return action


@router.get("/funds/{fund_id}/actions", response_model=list[ActionOut])
def list_actions(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "COMPLIANCE", "AUDITOR", "INVESTMENT_TEAM"])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
):
    return list(
        db.execute(
            select(ExecutionAction)
            .where(ExecutionAction.fund_id == fund_id)
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    )


@router.patch("/funds/{fund_id}/actions/{action_id}", response_model=ActionOut)
def update_action(
    fund_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: ActionUpdate,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "COMPLIANCE", "INVESTMENT_TEAM"])),
):
    action = db.execute(select(ExecutionAction).where(ExecutionAction.fund_id == fund_id, ExecutionAction.id == action_id)).scalar_one_or_none()
    if not action:
        raise HTTPException(status_code=404, detail="Not found")

    # Governance rule: cannot close without evidence
    if payload.status == "CLOSED":
        evidence_count = db.execute(
            select(func.count())
            .select_from(EvidenceDocument)
            .where(EvidenceDocument.fund_id == fund_id, EvidenceDocument.action_id == action.id)
        ).scalar_one()
        if evidence_count == 0:
            write_audit_event(
                db=db,
                fund_id=fund_id,
                actor_id=actor.id,
                action="action.close_blocked_missing_evidence",
                entity_type="ExecutionAction",
                entity_id=str(action.id),
                before={"status": action.status},
                after={"attempted_status": "CLOSED"},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Cannot close Action without evidence")

    before = {"status": action.status, "description": action.description}
    action.status = payload.status
    if payload.evidence_notes is not None:
        action.description = payload.evidence_notes
    action.updated_by = actor.id
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="action.updated",
        entity_type="ExecutionAction",
        entity_id=str(action.id),
        before=before,
        after=payload.model_dump(),
    )

    db.commit()
    db.refresh(action)
    return action


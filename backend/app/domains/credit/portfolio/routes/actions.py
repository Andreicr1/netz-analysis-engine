from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.portfolio.models.actions import Action
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.schemas.actions import ActionOut, ActionUpdate


def _limit(limit: int = Query(default=50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(default=0, ge=0)) -> int:
    return offset


router = APIRouter(tags=["Actions"], dependencies=[Depends(require_fund_access())])


@router.get("/funds/{fund_id}/portfolio/actions", response_model=list[ActionOut])
def list_actions(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "COMPLIANCE", "AUDITOR"])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
):
    return list(
        db.execute(
            select(Action)
            .join(PortfolioAsset, PortfolioAsset.id == Action.asset_id)
            .where(PortfolioAsset.fund_id == fund_id)
            .limit(limit)
            .offset(offset),
        ).scalars().all(),
    )


@router.patch("/funds/{fund_id}/portfolio/actions/{action_id}", response_model=ActionOut)
def update_action(
    fund_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: ActionUpdate,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "COMPLIANCE"])),
):
    action = db.execute(
        select(Action)
        .join(PortfolioAsset, PortfolioAsset.id == Action.asset_id)
        .where(
            PortfolioAsset.fund_id == fund_id,
            Action.id == action_id,
        ),
    ).scalar_one_or_none()

    if not action:
        raise HTTPException(status_code=404, detail="Not found")

    before = {"status": action.status.value if hasattr(action.status, "value") else action.status}

    action.status = payload.status
    action.evidence_notes = payload.evidence_notes
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="action.updated",
        entity_type="Action",
        entity_id=str(action.id),
        before=before,
        after=payload.model_dump(),
    )

    db.commit()
    db.refresh(action)
    return action


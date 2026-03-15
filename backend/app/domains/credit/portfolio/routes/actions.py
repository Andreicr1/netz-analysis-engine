from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.portfolio.models.actions import Action
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.schemas.actions import ActionOut, ActionUpdate

router = APIRouter(tags=["Actions"])


@router.get("/funds/{fund_id}/portfolio/actions", response_model=list[ActionOut])
async def list_actions(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ActionOut]:
    result = await db.execute(
        select(Action)
        .join(PortfolioAsset, PortfolioAsset.id == Action.asset_id)
        .where(PortfolioAsset.fund_id == fund_id)
        .limit(limit)
        .offset(offset),
    )
    return [ActionOut.model_validate(row) for row in result.scalars().all()]


@router.patch("/funds/{fund_id}/portfolio/actions/{action_id}", response_model=ActionOut)
async def update_action(
    fund_id: uuid.UUID,
    action_id: uuid.UUID,
    payload: ActionUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ActionOut:
    result = await db.execute(
        select(Action)
        .join(PortfolioAsset, PortfolioAsset.id == Action.asset_id)
        .where(
            PortfolioAsset.fund_id == fund_id,
            Action.id == action_id,
        ),
    )
    action = result.scalar_one_or_none()

    if not action:
        raise HTTPException(status_code=404, detail="Not found")

    before = {"status": action.status.value if hasattr(action.status, "value") else action.status}

    action.status = payload.status
    action.evidence_notes = payload.evidence_notes
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="action.updated",
        entity_type="Action",
        entity_id=str(action.id),
        before=before,
        after=payload.model_dump(),
    )

    await db.commit()
    await db.refresh(action)
    return ActionOut.model_validate(action)

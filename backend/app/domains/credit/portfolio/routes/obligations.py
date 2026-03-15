from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.models.obligations import AssetObligation
from app.domains.credit.portfolio.schemas.obligations import (
    ObligationCreate,
    ObligationOut,
    ObligationUpdate,
)

router = APIRouter(tags=["Asset Obligations"])


@router.post(
    "/funds/{fund_id}/assets/{asset_id}/obligations",
    response_model=ObligationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_obligation(
    fund_id: uuid.UUID,
    asset_id: uuid.UUID,
    payload: ObligationCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ObligationOut:
    result = await db.execute(
        select(PortfolioAsset).where(
            PortfolioAsset.id == asset_id,
            PortfolioAsset.fund_id == fund_id,
        ),
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    ob = AssetObligation(asset_id=asset_id, **payload.model_dump())
    db.add(ob)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="obligation.created",
        entity_type="AssetObligation",
        entity_id=str(ob.id),
        before=None,
        after=payload.model_dump(),
    )

    await db.commit()
    await db.refresh(ob)
    return ObligationOut.model_validate(ob)


@router.get("/funds/{fund_id}/obligations", response_model=list[ObligationOut])
async def list_obligations(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[ObligationOut]:
    result = await db.execute(
        select(AssetObligation)
        .join(PortfolioAsset, PortfolioAsset.id == AssetObligation.asset_id)
        .where(PortfolioAsset.fund_id == fund_id)
        .limit(limit)
        .offset(offset),
    )
    return [ObligationOut.model_validate(row) for row in result.scalars().all()]


@router.patch("/funds/{fund_id}/obligations/{obligation_id}", response_model=ObligationOut)
async def update_obligation(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    payload: ObligationUpdate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> ObligationOut:
    result = await db.execute(
        select(AssetObligation)
        .join(PortfolioAsset, PortfolioAsset.id == AssetObligation.asset_id)
        .where(
            PortfolioAsset.fund_id == fund_id,
            AssetObligation.id == obligation_id,
        ),
    )
    ob = result.scalar_one_or_none()

    if not ob:
        raise HTTPException(status_code=404, detail="Not found")

    before = {"status": ob.status.value if hasattr(ob.status, "value") else ob.status}

    ob.status = payload.status
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="obligation.updated",
        entity_type="AssetObligation",
        entity_id=str(ob.id),
        before=before,
        after=payload.model_dump(),
    )

    await db.commit()
    await db.refresh(ob)
    return ObligationOut.model_validate(ob)

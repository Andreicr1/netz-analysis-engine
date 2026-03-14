from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.deals.enums import DealStage
from app.domains.credit.deals.models.deals import Deal
from app.domains.credit.deals.services.conversion import convert_deal_to_asset

router = APIRouter(tags=["Deal Conversion"])


@router.post("/funds/{fund_id}/deals/{deal_id}/convert", response_model=dict)
async def convert_deal(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> dict:
    result = await db.execute(
        select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id),
    )
    deal = result.scalar_one_or_none()

    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if deal.stage != DealStage.APPROVED:
        raise HTTPException(status_code=400, detail="Deal must be APPROVED before conversion")

    if deal.asset_id:
        raise HTTPException(status_code=409, detail="Deal already converted")

    try:
        asset = await convert_deal_to_asset(db, deal, actor_id=actor.id, fund_id=fund_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    await db.commit()
    return {"deal_id": str(deal.id), "asset_id": str(asset.id)}

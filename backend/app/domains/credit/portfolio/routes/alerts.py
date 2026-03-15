from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.portfolio.models.alerts import Alert
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.schemas.alerts import AlertOut

router = APIRouter(tags=["Alerts"])


@router.get("/funds/{fund_id}/alerts", response_model=list[AlertOut])
async def list_alerts(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[AlertOut]:
    result = await db.execute(
        select(Alert)
        .join(PortfolioAsset, PortfolioAsset.id == Alert.asset_id)
        .where(PortfolioAsset.fund_id == fund_id)
        .limit(limit)
        .offset(offset),
    )
    return [AlertOut.model_validate(row) for row in result.scalars().all()]

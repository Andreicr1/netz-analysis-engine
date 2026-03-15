from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.schemas.assets import PortfolioAssetCreate, PortfolioAssetOut
from app.shared.utils import sa_model_to_dict

router = APIRouter(prefix="/funds/{fund_id}/assets", tags=["Assets"])


@router.post("", response_model=PortfolioAssetOut, status_code=status.HTTP_201_CREATED)
async def create_asset(
    fund_id: uuid.UUID,
    payload: PortfolioAssetCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> PortfolioAssetOut:
    asset = PortfolioAsset(
        fund_id=fund_id,
        asset_type=payload.asset_type,
        strategy=payload.strategy,
        name=payload.name,
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(asset)
    await db.flush()

    await write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="portfolio_asset.created",
        entity_type="PortfolioAsset",
        entity_id=asset.id,
        before=None,
        after=sa_model_to_dict(asset),
    )
    await db.commit()
    await db.refresh(asset)
    return PortfolioAssetOut.model_validate(asset)

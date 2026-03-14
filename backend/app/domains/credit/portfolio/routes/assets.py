from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.schemas.assets import PortfolioAssetCreate, PortfolioAssetOut
from app.shared.utils import sa_model_to_dict

router = APIRouter(prefix="/funds/{fund_id}/assets", tags=["Assets"], dependencies=[Depends(require_fund_access())])


@router.post("", response_model=PortfolioAssetOut, status_code=status.HTTP_201_CREATED)
def create_asset(
    fund_id: uuid.UUID,
    payload: PortfolioAssetCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(require_role(["ADMIN", "INVESTMENT_TEAM"])),
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
    db.flush()

    write_audit_event(
        db,
        fund_id=fund_id,
        action="portfolio_asset.created",
        entity_type="PortfolioAsset",
        entity_id=asset.id,
        before=None,
        after=sa_model_to_dict(asset),
    )
    db.commit()
    db.refresh(asset)
    return asset


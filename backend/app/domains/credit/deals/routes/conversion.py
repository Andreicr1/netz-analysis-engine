from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.deals.enums import DealStage
from app.domains.credit.deals.models.deals import Deal
from app.domains.credit.deals.services.conversion import convert_deal_to_asset

router = APIRouter(tags=["Deal Conversion"], dependencies=[Depends(require_fund_access())])


@router.post("/funds/{fund_id}/deals/{deal_id}/convert")
def convert_deal(
    fund_id: uuid.UUID,
    deal_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "INVESTMENT_TEAM"])),
):
    deal = db.execute(select(Deal).where(Deal.fund_id == fund_id, Deal.id == deal_id)).scalar_one_or_none()

    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")

    if deal.stage != DealStage.APPROVED:
        raise HTTPException(status_code=400, detail="Deal must be APPROVED before conversion")

    if deal.asset_id:
        raise HTTPException(status_code=409, detail="Deal already converted")

    try:
        asset = convert_deal_to_asset(db, deal, actor_id=actor.id, fund_id=fund_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    db.commit()
    return {"deal_id": str(deal.id), "asset_id": str(asset.id)}


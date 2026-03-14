from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.portfolio.enums import AssetType, ObligationType
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.models.fund_investments import FundInvestment
from app.domains.credit.portfolio.models.obligations import AssetObligation
from app.domains.credit.portfolio.schemas.fund_investments import (
    FundInvestmentCreate,
    FundInvestmentOut,
)

router = APIRouter(
    prefix="/funds/{fund_id}/assets/{asset_id}/fund-investment",
    tags=["Fund Investments"],
)


@router.post("", response_model=FundInvestmentOut, status_code=status.HTTP_201_CREATED)
async def attach_fund_investment(
    fund_id: uuid.UUID,
    asset_id: uuid.UUID,
    payload: FundInvestmentCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> FundInvestmentOut:
    result = await db.execute(
        select(PortfolioAsset).where(PortfolioAsset.id == asset_id, PortfolioAsset.fund_id == fund_id),
    )
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.asset_type != AssetType.FUND_INVESTMENT:
        raise HTTPException(status_code=400, detail="Asset type must be FUND_INVESTMENT")

    existing_result = await db.execute(
        select(FundInvestment).where(FundInvestment.asset_id == asset_id),
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="FundInvestment already attached")

    fi = FundInvestment(asset_id=asset_id, **payload.model_dump())
    db.add(fi)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="fund_investment.attached",
        entity_type="FundInvestment",
        entity_id=str(asset_id),
        before=None,
        after={**payload.model_dump(), "asset_id": str(asset_id)},
    )

    # AUTO-GENERATE NAV REPORT OBLIGATION
    nav_due = date.today() + timedelta(days=90)

    nav_ob = AssetObligation(
        asset_id=asset_id,
        obligation_type=ObligationType.NAV_REPORT,
        due_date=nav_due,
    )

    db.add(nav_ob)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="obligation.generated.nav_report",
        entity_type="AssetObligation",
        entity_id=str(nav_ob.id),
        before=None,
        after={
            "asset_id": str(asset_id),
            "obligation_type": "NAV_REPORT",
            "due_date": str(nav_due),
        },
    )

    await db.commit()
    await db.refresh(fi)
    return FundInvestmentOut.model_validate(fi)


@router.get("", response_model=FundInvestmentOut)
async def get_fund_investment(
    fund_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> FundInvestmentOut:
    result = await db.execute(
        select(FundInvestment)
        .join(PortfolioAsset, PortfolioAsset.id == FundInvestment.asset_id)
        .where(PortfolioAsset.fund_id == fund_id, FundInvestment.asset_id == asset_id),
    )
    fi = result.scalar_one_or_none()

    if not fi:
        raise HTTPException(status_code=404, detail="Not found")

    return FundInvestmentOut.model_validate(fi)

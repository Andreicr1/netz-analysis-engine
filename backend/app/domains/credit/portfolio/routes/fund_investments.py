from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
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
    dependencies=[Depends(require_fund_access())],
)


@router.post("", response_model=FundInvestmentOut, status_code=status.HTTP_201_CREATED)
def attach_fund_investment(
    fund_id: uuid.UUID,
    asset_id: uuid.UUID,
    payload: FundInvestmentCreate,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "INVESTMENT_TEAM"])),
):
    asset = db.execute(
        select(PortfolioAsset).where(PortfolioAsset.id == asset_id, PortfolioAsset.fund_id == fund_id),
    ).scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if asset.asset_type != AssetType.FUND_INVESTMENT:
        raise HTTPException(status_code=400, detail="Asset type must be FUND_INVESTMENT")

    existing = db.execute(select(FundInvestment).where(FundInvestment.asset_id == asset_id)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="FundInvestment already attached")

    fi = FundInvestment(asset_id=asset_id, **payload.model_dump())
    db.add(fi)
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="fund_investment.attached",
        entity_type="FundInvestment",
        entity_id=str(asset_id),
        before=None,
        after={**payload.model_dump(), "asset_id": str(asset_id)},
    )

    db.flush()

    # AUTO-GENERATE NAV REPORT OBLIGATION
    nav_due = date.today() + timedelta(days=90)

    nav_ob = AssetObligation(
        asset_id=asset_id,
        obligation_type=ObligationType.NAV_REPORT,
        due_date=nav_due,
    )

    db.add(nav_ob)
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
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

    db.commit()
    db.refresh(fi)
    return fi


@router.get("", response_model=FundInvestmentOut)
def get_fund_investment(
    fund_id: uuid.UUID,
    asset_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "INVESTMENT_TEAM", "AUDITOR"])),
):
    fi = db.execute(
        select(FundInvestment)
        .join(PortfolioAsset, PortfolioAsset.id == FundInvestment.asset_id)
        .where(PortfolioAsset.fund_id == fund_id, FundInvestment.asset_id == asset_id),
    ).scalar_one_or_none()

    if not fi:
        raise HTTPException(status_code=404, detail="Not found")

    return fi


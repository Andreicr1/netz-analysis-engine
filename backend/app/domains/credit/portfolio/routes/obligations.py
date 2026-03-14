from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.models.obligations import AssetObligation
from app.domains.credit.portfolio.schemas.obligations import (
    ObligationCreate,
    ObligationOut,
    ObligationUpdate,
)


def _limit(limit: int = Query(default=50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(default=0, ge=0)) -> int:
    return offset


router = APIRouter(tags=["Asset Obligations"], dependencies=[Depends(require_fund_access())])


@router.post("/funds/{fund_id}/assets/{asset_id}/obligations", response_model=ObligationOut, status_code=status.HTTP_201_CREATED)
def create_obligation(
    fund_id: uuid.UUID,
    asset_id: uuid.UUID,
    payload: ObligationCreate,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "COMPLIANCE", "INVESTMENT_TEAM"])),
):
    asset = db.execute(
        select(PortfolioAsset).where(
            PortfolioAsset.id == asset_id,
            PortfolioAsset.fund_id == fund_id,
        )
    ).scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    ob = AssetObligation(asset_id=asset_id, **payload.model_dump())
    db.add(ob)
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="obligation.created",
        entity_type="AssetObligation",
        entity_id=str(ob.id),
        before=None,
        after=payload.model_dump(),
    )

    db.commit()
    db.refresh(ob)
    return ob


@router.get("/funds/{fund_id}/obligations", response_model=list[ObligationOut])
def list_obligations(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "COMPLIANCE", "AUDITOR"])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
):
    return list(
        db.execute(
            select(AssetObligation)
            .join(PortfolioAsset, PortfolioAsset.id == AssetObligation.asset_id)
            .where(PortfolioAsset.fund_id == fund_id)
            .limit(limit)
            .offset(offset)
        ).scalars().all()
    )


@router.patch("/funds/{fund_id}/obligations/{obligation_id}", response_model=ObligationOut)
def update_obligation(
    fund_id: uuid.UUID,
    obligation_id: uuid.UUID,
    payload: ObligationUpdate,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "COMPLIANCE"])),
):
    ob = db.execute(
        select(AssetObligation)
        .join(PortfolioAsset, PortfolioAsset.id == AssetObligation.asset_id)
        .where(
            PortfolioAsset.fund_id == fund_id,
            AssetObligation.id == obligation_id,
        )
    ).scalar_one_or_none()

    if not ob:
        raise HTTPException(status_code=404, detail="Not found")

    before = {"status": ob.status.value if hasattr(ob.status, "value") else ob.status}

    ob.status = payload.status
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="obligation.updated",
        entity_type="AssetObligation",
        entity_id=str(ob.id),
        before=before,
        after=payload.model_dump(),
    )

    db.commit()
    db.refresh(ob)
    return ob


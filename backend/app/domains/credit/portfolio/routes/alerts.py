from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.portfolio.models.alerts import Alert
from app.domains.credit.portfolio.models.assets import PortfolioAsset
from app.domains.credit.portfolio.schemas.alerts import AlertOut


def _limit(limit: int = Query(default=50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(default=0, ge=0)) -> int:
    return offset


router = APIRouter(tags=["Alerts"], dependencies=[Depends(require_fund_access())])


@router.get("/funds/{fund_id}/alerts", response_model=list[AlertOut])
def list_alerts(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["ADMIN", "COMPLIANCE", "AUDITOR"])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
):
    return list(
        db.execute(
            select(Alert)
            .join(PortfolioAsset, PortfolioAsset.id == Alert.asset_id)
            .where(PortfolioAsset.fund_id == fund_id)
            .limit(limit)
            .offset(offset),
        ).scalars().all(),
    )


from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.reporting.enums import ReportPackStatus
from app.domains.credit.reporting.models.report_packs import MonthlyReportPack

logger = logging.getLogger(__name__)


def _limit(limit: int = Query(default=50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(default=0, ge=0)) -> int:
    return offset


router = APIRouter(tags=["Investor Portal"], dependencies=[Depends(require_fund_access())])


def _bg_audit_investor_view(
    fund_id: uuid.UUID, actor_id: str, pack_count: int,
) -> None:
    """Fire-and-forget audit write with its own DB session."""
    db = async_session_factory()
    try:
        write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor_id,
            action="investor.report_pack.viewed",
            entity_type="MonthlyReportPack",
            entity_id=str(fund_id),
            before=None,
            after={"count": pack_count},
        )
        db.commit()
    except Exception:
        logger.warning("Background audit write failed for investor portal view", exc_info=True)
        db.rollback()
    finally:
        db.close()


@router.get("/funds/{fund_id}/investor/report-packs")
def list_published_packs(
    fund_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTOR", "ADMIN"])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
):
    packs = list(
        db.execute(
            select(MonthlyReportPack).where(
                MonthlyReportPack.fund_id == fund_id,
                MonthlyReportPack.status == ReportPackStatus.PUBLISHED,
            ).limit(limit).offset(offset),
        ).scalars().all(),
    )

    background_tasks.add_task(
        _bg_audit_investor_view, fund_id=fund_id, actor_id=actor.id, pack_count=len(packs),
    )

    return packs


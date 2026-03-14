from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor, require_fund_access, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.reporting.enums import ReportPackStatus
from app.domains.credit.reporting.models.report_packs import MonthlyReportPack

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Investor Portal"], dependencies=[Depends(require_fund_access())])


@router.get("/funds/{fund_id}/investor/report-packs")
async def list_published_packs(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTOR", "ADMIN"])),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    result = await db.execute(
        select(MonthlyReportPack).where(
            MonthlyReportPack.fund_id == fund_id,
            MonthlyReportPack.status == ReportPackStatus.PUBLISHED,
        ).limit(limit).offset(offset),
    )
    packs = list(result.scalars().all())

    # Fire-and-forget audit write using a separate session
    from app.core.db.engine import async_session_factory

    async def _bg_audit() -> None:
        try:
            async with async_session_factory() as audit_db:
                await write_audit_event(
                    audit_db,
                    fund_id=fund_id,
                    actor_id=actor.actor_id,
                    action="investor.report_pack.viewed",
                    entity_type="MonthlyReportPack",
                    entity_id=str(fund_id),
                    before=None,
                    after={"count": len(packs)},
                )
                await audit_db.commit()
        except Exception:
            logger.warning("Background audit write failed for investor portal view", exc_info=True)

    import asyncio
    asyncio.ensure_future(_bg_audit())

    return packs

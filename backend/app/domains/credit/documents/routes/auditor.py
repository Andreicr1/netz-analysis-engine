from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, get_actor, require_fund_access, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.documents.models.evidence import EvidenceDocument

router = APIRouter(tags=["Auditor"], dependencies=[Depends(require_fund_access())])


@router.get("/funds/{fund_id}/auditor/evidence")
async def list_all_evidence(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["AUDITOR", "ADMIN"])),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    result = await db.execute(
        select(EvidenceDocument)
        .where(EvidenceDocument.fund_id == fund_id)
        .limit(limit)
        .offset(offset),
    )
    return list(result.scalars().all())

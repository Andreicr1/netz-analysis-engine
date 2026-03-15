from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor, require_fund_access, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.documents.models.evidence import EvidenceDocument

router = APIRouter(tags=["Evidence"], dependencies=[Depends(require_fund_access())])


@router.patch("/funds/{fund_id}/evidence/{evidence_id}/complete")
async def mark_uploaded(
    fund_id: uuid.UUID,
    evidence_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "ADMIN"])),
):
    result = await db.execute(
        select(EvidenceDocument).where(
            EvidenceDocument.fund_id == fund_id,
            EvidenceDocument.id == evidence_id,
        ),
    )
    evidence = result.scalar_one_or_none()

    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence.uploaded_at = datetime.now(UTC)
    await db.flush()

    await write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="evidence.upload_completed",
        entity_type="EvidenceDocument",
        entity_id=str(evidence.id),
        before=None,
        after={"uploaded_at": evidence.uploaded_at.isoformat()},
    )

    return {"status": "uploaded"}

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.documents.models.evidence import EvidenceDocument

router = APIRouter(tags=["Evidence"], dependencies=[Depends(require_fund_access())])


@router.patch("/funds/{fund_id}/evidence/{evidence_id}/complete")
def mark_uploaded(
    fund_id: uuid.UUID,
    evidence_id: uuid.UUID,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "ADMIN"])),
):
    evidence = db.execute(
        select(EvidenceDocument).where(
            EvidenceDocument.fund_id == fund_id,
            EvidenceDocument.id == evidence_id,
        )
    ).scalar_one_or_none()

    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")

    evidence.uploaded_at = datetime.utcnow()
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="evidence.upload_completed",
        entity_type="EvidenceDocument",
        entity_id=str(evidence.id),
        before=None,
        after={"uploaded_at": evidence.uploaded_at.isoformat()},
    )

    db.commit()
    return {"status": "uploaded"}


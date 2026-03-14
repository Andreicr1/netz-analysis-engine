from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config.settings import settings
from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.clerk_auth import require_fund_access, require_role
from app.domains.credit.documents.models.evidence import EvidenceDocument

router = APIRouter(tags=["Evidence Uploads"], dependencies=[Depends(require_fund_access())])


@router.post("/funds/{fund_id}/evidence/upload-request")
def request_evidence_upload(
    fund_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor=Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "ADMIN"])),
):
    if "filename" not in payload:
        raise HTTPException(status_code=400, detail="filename is required")

    filename = payload["filename"]

    if not settings.AZURE_STORAGE_ACCOUNT:
        raise HTTPException(status_code=501, detail="Azure storage account not configured")

    blob_name = f"{fund_id}/{uuid.uuid4()}_{filename}"

    # Evidence registry entry (metadata first)
    evidence = EvidenceDocument(
        fund_id=fund_id,
        deal_id=payload.get("deal_id"),
        action_id=payload.get("action_id"),
        filename=filename,
        blob_uri=f"https://{settings.AZURE_STORAGE_ACCOUNT}.blob.core.windows.net/{settings.AZURE_STORAGE_CONTAINER}/{blob_name}",
        uploaded_at=None,
    )

    db.add(evidence)
    db.flush()

    write_audit_event(
        db=db,
        fund_id=fund_id,
        actor_id=actor.id,
        action="evidence.upload_requested",
        entity_type="EvidenceDocument",
        entity_id=str(evidence.id),
        before=None,
        after={"filename": filename},
    )

    db.commit()
    db.refresh(evidence)

    # SAS placeholder (real SAS in prod)
    return {
        "evidence_id": str(evidence.id),
        "blob_uri": evidence.blob_uri,
        "upload_url": evidence.blob_uri + "?SAS_TOKEN_PLACEHOLDER",
    }


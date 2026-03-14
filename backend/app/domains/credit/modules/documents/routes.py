from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session

from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_readonly_allowed
from app.domains.credit.modules.documents import service
from app.domains.credit.modules.documents.schemas import (
    DocumentCreate,
    DocumentOut,
    DocumentVersionCreate,
    DocumentVersionOut,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
def create_document(
    fund_id: uuid.UUID,
    payload: DocumentCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> DocumentOut:
    doc = service.create_document(db, fund_id=fund_id, actor=actor, payload=payload)
    return DocumentOut.model_validate(doc)


@router.post("/{document_id}/versions", response_model=DocumentVersionOut, status_code=status.HTTP_201_CREATED)
def create_document_version(
    fund_id: uuid.UUID,
    document_id: uuid.UUID,
    payload: DocumentVersionCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _write_guard: Actor = Depends(require_readonly_allowed()),
) -> DocumentVersionOut:
    try:
        version = service.create_version(db, fund_id=fund_id, actor=actor, document_id=document_id, payload=payload)
        return DocumentVersionOut.model_validate(version)
    except NoResultFound:
        raise HTTPException(status_code=404, detail="Document not found")


from __future__ import annotations

import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db.audit import write_audit_event
from app.core.db.engine import get_db
from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_readonly_allowed, require_roles
from app.domains.credit.documents import service
from app.domains.credit.documents.services.ingestion_worker import process_pending_versions
from app.domains.credit.modules.documents.models import Document, DocumentVersion
from app.domains.credit.modules.documents.schemas import DocumentOut, DocumentVersionOut, Page
from app.shared.enums import Role

router = APIRouter(prefix="/documents", tags=["documents.ingest"])


def _limit(limit: int = Query(50, ge=1, le=200)) -> int:
    return limit


def _offset(offset: int = Query(0, ge=0, le=10_000)) -> int:
    return offset


@router.post("/upload")
async def upload(
    fund_id: uuid.UUID,
    root_folder: str = Form(...),
    subfolder_path: str | None = Form(None),
    domain: str | None = Form(None),
    title: str | None = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM])),
    _write_guard: Actor = Depends(require_readonly_allowed()),
):
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="file is empty")
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
    try:
        res = service.upload_document(
            db,
            fund_id=fund_id,
            actor=actor,
            root_folder=root_folder,
            subfolder_path=subfolder_path,
            domain=domain,
            title=title or (file.filename or "Document"),
            filename=file.filename or "document.pdf",
            content_type=file.content_type,
            data=data,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Document upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {type(e).__name__}")

    return {
        "document_id": str(res.document.id),
        "version_id": str(res.version.id),
        "blob_path": res.blob_path,
    }


@router.get("", response_model=Page[DocumentOut])
def list_docs(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
    limit: int = Depends(_limit),
    offset: int = Depends(_offset),
    root_folder: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    updated_after: datetime | None = Query(default=None),
    q: str | None = Query(default=None, description="Title search"),
):
    items = service.list_documents(
        db,
        fund_id=fund_id,
        limit=limit,
        offset=offset,
        root_folder=root_folder,
        domain=domain,
        updated_after=updated_after,
        title_q=q,
    )
    return Page(items=items, limit=limit, offset=offset)


@router.get("/root-folders")
def list_root_folders(
    fund_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    """List allowed root folders (canonical + active custom), for governed UI selects."""
    items = sorted(service.allowed_root_folders(db, fund_id=fund_id))
    return {"items": items}


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    fund_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    doc = db.execute(select(Document).where(Document.fund_id == fund_id, Document.id == document_id)).scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/versions", response_model=list[DocumentVersionOut])
def list_document_versions(
    fund_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Session = Depends(get_db),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR])),
):
    vers = list(
        db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.fund_id == fund_id, DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version_number.asc()),
        ).scalars().all(),
    )
    return vers


@router.post("/root-folders", status_code=status.HTTP_201_CREATED)
def create_root_folder(
    fund_id: uuid.UUID,
    payload: dict,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN])),
    _write_guard: Actor = Depends(require_readonly_allowed()),
):
    if "name" not in payload:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        folder = service.create_root_folder(db, fund_id=fund_id, actor=actor, name=str(payload["name"]))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": str(folder.id), "name": folder.name}


@router.post("/ingestion/process-pending")
def process_pending(
    fund_id: uuid.UUID,
    payload: dict | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM])),
    _write_guard: Actor = Depends(require_readonly_allowed()),
):
    """Operational endpoint to process pending document versions.
    This is a stopgap until an Azure Functions / queue worker is wired.
    """
    limit = 10
    if payload and isinstance(payload, dict) and "limit" in payload:
        try:
            limit = int(payload["limit"])
        except Exception:
            limit = 10
    limit = max(1, min(limit, 50))

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="INGESTION_WORKER_TRIGGERED",
        entity_type="document_ingestion",
        entity_id=str(fund_id),
        before=None,
        after={"limit": limit},
    )
    db.commit()

    res = process_pending_versions(db, fund_id=fund_id, limit=limit, actor_id=actor.actor_id)
    return {"processed": res.processed, "indexed": res.indexed, "failed": res.failed, "skipped": res.skipped}


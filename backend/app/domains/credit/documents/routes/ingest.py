from __future__ import annotations

import logging
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, get_actor, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.documents import service
from app.domains.credit.documents.enums import DocumentIngestionStatus
from app.domains.credit.modules.documents.models import Document, DocumentVersion
from app.domains.credit.modules.documents.schemas import DocumentOut, DocumentVersionOut, Page
from app.shared.enums import Role

router = APIRouter(prefix="/documents", tags=["documents.ingest"])


@router.post("/upload")
async def upload(
    fund_id: uuid.UUID,
    root_folder: str = Form(...),
    subfolder_path: str | None = Form(None),
    domain: str | None = Form(None),
    title: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM)),
):
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="file is empty")
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")
    try:
        res = await service.upload_document(
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
async def list_docs(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR)),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
    root_folder: str | None = Query(default=None),
    domain: str | None = Query(default=None),
    updated_after: datetime | None = Query(default=None),
    q: str | None = Query(default=None, description="Title search"),
):
    items = await service.list_documents(
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
async def list_root_folders(
    fund_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR)),
):
    """List allowed root folders (canonical + active custom), for governed UI selects."""
    items = sorted(await service.allowed_root_folders(db, fund_id=fund_id))
    return {"items": items}


@router.get("/{document_id}", response_model=DocumentOut)
async def get_document(
    fund_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR)),
):
    result = await db.execute(
        select(Document).where(Document.fund_id == fund_id, Document.id == document_id),
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.get("/{document_id}/versions", response_model=list[DocumentVersionOut])
async def list_document_versions(
    fund_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM, Role.AUDITOR)),
):
    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.fund_id == fund_id, DocumentVersion.document_id == document_id)
        .order_by(DocumentVersion.version_number.asc()),
    )
    return list(result.scalars().all())


@router.post("/root-folders", status_code=status.HTTP_201_CREATED)
async def create_root_folder(
    fund_id: uuid.UUID,
    payload: dict,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN)),
):
    if "name" not in payload:
        raise HTTPException(status_code=400, detail="name is required")
    try:
        folder = await service.create_root_folder(db, fund_id=fund_id, actor=actor, name=str(payload["name"]))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"id": str(folder.id), "name": folder.name}


@router.post("/ingestion/process-pending")
async def process_pending(
    fund_id: uuid.UUID,
    payload: dict | None = None,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM)),
):
    """Process pending document versions through the unified pipeline."""
    from ai_engine.pipeline.models import IngestRequest
    from ai_engine.pipeline.unified_pipeline import process as run_pipeline

    limit = 10
    if payload and isinstance(payload, dict) and "limit" in payload:
        try:
            limit = int(payload["limit"])
        except Exception:
            limit = 10
    limit = max(1, min(limit, 50))

    await write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="INGESTION_WORKER_TRIGGERED",
        entity_type="document_ingestion",
        entity_id=str(fund_id),
        before=None,
        after={"limit": limit},
    )

    # Fetch pending versions
    result = await db.execute(
        select(DocumentVersion)
        .where(
            DocumentVersion.fund_id == fund_id,
            DocumentVersion.ingestion_status == DocumentIngestionStatus.PENDING,
        )
        .order_by(DocumentVersion.created_at.asc())
        .limit(limit),
    )
    versions = result.scalars().all()

    processed = indexed = failed = skipped = 0
    for version in versions:
        processed += 1

        # Same-document concurrency guard
        if version.ingestion_status == DocumentIngestionStatus.PROCESSING:
            skipped += 1
            continue

        # Mark PROCESSING
        version.ingestion_status = DocumentIngestionStatus.PROCESSING
        version.updated_by = actor.actor_id
        await db.commit()

        try:
            # Fetch parent document for metadata
            doc_result = await db.execute(
                select(Document).where(
                    Document.fund_id == fund_id,
                    Document.id == version.document_id,
                ),
            )
            doc = doc_result.scalar_one()

            request = IngestRequest(
                source="ui",
                org_id=actor.organization_id,
                vertical="credit",
                document_id=version.document_id,
                blob_uri=version.blob_uri or "",
                filename=doc.title or "document.pdf",
                fund_id=fund_id,
                version_id=version.id,
            )
            pipeline_result = await run_pipeline(request, db=db, actor_id=actor.actor_id)

            if pipeline_result.success:
                version.ingestion_status = DocumentIngestionStatus.INDEXED
                version.indexed_at = datetime.now()
                indexed += 1
            else:
                version.ingestion_status = DocumentIngestionStatus.FAILED
                version.ingest_error = {
                    "stage": pipeline_result.stage,
                    "errors": pipeline_result.errors,
                }
                failed += 1

        except Exception as e:
            logger.exception("Pipeline failed for version %s", version.id)
            version.ingestion_status = DocumentIngestionStatus.FAILED
            version.ingest_error = {"reason": "processing_error", "type": type(e).__name__}
            failed += 1

        version.updated_by = actor.actor_id
        await db.commit()

    return {"processed": processed, "indexed": indexed, "failed": failed, "skipped": skipped}

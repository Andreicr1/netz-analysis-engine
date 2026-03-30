"""Wealth document upload & ingestion routes.

Two entry points:
  1. Two-step presigned URL flow (POST /upload-url → POST /upload-complete)
  2. Single-step API upload (POST /upload)

Both feed ``unified_pipeline.process()`` with ``vertical="wealth"``.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_engine.pipeline.storage_routing import bronze_upload_blob_path
from app.core.db.audit import write_audit_event
from app.core.jobs.tracker import publish_event
from app.core.security.clerk_auth import Actor, get_actor, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.models.document import WealthDocument, WealthDocumentVersion
from app.domains.wealth.schemas.document import (
    WealthDocumentOut,
    WealthDocumentPage,
    WealthProcessPendingRequest,
    WealthProcessPendingResponse,
    WealthUploadCompleteRequest,
    WealthUploadCompleteResponse,
    WealthUploadUrlRequest,
    WealthUploadUrlResponse,
)
from app.domains.wealth.services import document_service as service
from app.services.storage_client import get_storage_client
from app.shared.enums import DocumentIngestionStatus, Role

logger = logging.getLogger(__name__)

_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\- ]*$")


def _sanitize_filename(raw: str) -> str:
    """Strip path traversal components from a user-supplied filename."""
    # Normalise backslashes so os.path.basename works on all platforms
    name = os.path.basename(raw.replace("\\", "/"))
    name = name.replace("/", "").replace("\\", "").replace("..", "")
    return name or "upload"


def _sanitize_title(raw: str) -> str:
    """Strip path traversal prefixes from a user-supplied title."""
    cleaned = re.sub(r"[\\/]+", "/", raw)
    cleaned = cleaned.replace("..", "")
    # Take only the final path component if slashes remain
    cleaned = cleaned.rsplit("/", 1)[-1] if "/" in cleaned else cleaned
    return cleaned.strip() or "Untitled"


router = APIRouter(prefix="/wealth/documents", tags=["wealth.documents"])

_WRITE_ROLES = (Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM)
_READ_ROLES = (Role.ADMIN, Role.GP, Role.INVESTMENT_TEAM, Role.AUDITOR, Role.COMPLIANCE)


# ── Two-step presigned URL upload ────────────────────────────


@router.post("/upload-url", response_model=WealthUploadUrlResponse)
async def generate_upload_url(
    payload: WealthUploadUrlRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_WRITE_ROLES)),
):
    """Generate a pre-signed upload URL and create a pending WealthDocumentVersion."""
    storage = get_storage_client()

    # Sanitize filename and title BEFORE any persistence or service call
    safe_filename = _sanitize_filename(payload.filename)
    if not safe_filename or not _SAFE_FILENAME_RE.match(safe_filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    safe_title = _sanitize_title(payload.title or safe_filename)

    try:
        res = await service.create_document_pending(
            db,
            actor=actor,
            portfolio_id=payload.portfolio_id,
            instrument_id=payload.instrument_id,
            root_folder=payload.root_folder,
            subfolder_path=payload.subfolder_path,
            domain=payload.domain,
            title=safe_title,
            filename=safe_filename,
            content_type=payload.content_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Use portfolio_id or instrument_id as fund_id path segment
    path_id = payload.portfolio_id or payload.instrument_id or res.document.id
    blob_path = bronze_upload_blob_path(
        org_id=actor.organization_id,
        fund_id=path_id,
        version_id=res.version.id,
        filename=safe_filename,
    )
    upload_url = await storage.generate_upload_url(blob_path)

    res.version.blob_uri = blob_path
    res.version.blob_path = blob_path
    res.version.updated_by = actor.actor_id

    await write_audit_event(
        db,
        actor_id=actor.actor_id,
        action="WEALTH_UPLOAD_URL_GENERATED",
        entity_type="wealth_document_version",
        entity_id=res.version.id,
        before=None,
        after={"blob_path": blob_path, "filename": payload.filename},
    )

    return WealthUploadUrlResponse(
        upload_id=str(res.version.id),
        upload_url=upload_url,
        blob_path=blob_path,
    )


@router.post("/upload-complete", response_model=WealthUploadCompleteResponse)
async def upload_complete(
    payload: WealthUploadCompleteRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_WRITE_ROLES)),
):
    """Mark upload as complete and transition to PROCESSING."""
    version_id = uuid.UUID(payload.upload_id)

    result = await db.execute(
        select(WealthDocumentVersion).where(WealthDocumentVersion.id == version_id),
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Upload not found")

    if version.ingestion_status != DocumentIngestionStatus.PENDING.value:
        raise HTTPException(
            status_code=409,
            detail=f"Upload already in state: {version.ingestion_status}",
        )

    version.ingestion_status = DocumentIngestionStatus.PROCESSING.value
    version.updated_by = actor.actor_id

    job_id = str(version_id)

    await write_audit_event(
        db,
        actor_id=actor.actor_id,
        action="WEALTH_UPLOAD_COMPLETE",
        entity_type="wealth_document_version",
        entity_id=version_id,
        before=None,
        after={"job_id": job_id},
    )

    await publish_event(job_id, "upload_complete", {"version_id": str(version_id)})

    return WealthUploadCompleteResponse(
        job_id=job_id,
        version_id=str(version_id),
        document_id=str(version.document_id),
    )


# ── Single-step API upload ───────────────────────────────────


@router.post("/upload")
async def upload(
    root_folder: str = Form("documents"),
    subfolder_path: str | None = Form(None),
    domain: str | None = Form(None),
    title: str | None = Form(None),
    portfolio_id: uuid.UUID | None = Form(None),
    instrument_id: uuid.UUID | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_WRITE_ROLES)),
):
    """Single-step upload: file in body, writes to storage directly."""
    MAX_UPLOAD_SIZE = 100 * 1024 * 1024  # 100 MB
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="file is empty")
    if len(data) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 100 MB)")

    storage = get_storage_client()

    safe_filename = _sanitize_filename(file.filename or "document.pdf")
    safe_title = _sanitize_title(title or safe_filename or "Document")

    try:
        res = await service.upload_document(
            db,
            actor=actor,
            portfolio_id=portfolio_id,
            instrument_id=instrument_id,
            root_folder=root_folder,
            subfolder_path=subfolder_path,
            domain=domain,
            title=safe_title,
            filename=safe_filename,
            content_type=file.content_type,
            data=data,
            storage_client=storage,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Wealth document upload failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Upload failed — see server logs")

    return {
        "document_id": str(res.document.id),
        "version_id": str(res.version.id),
        "blob_path": res.blob_path,
    }


# ── Process pending (trigger pipeline) ───────────────────────


@router.post("/ingestion/process-pending", response_model=WealthProcessPendingResponse)
async def process_pending(
    payload: WealthProcessPendingRequest | None = None,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_WRITE_ROLES)),
):
    """Process pending wealth document versions through the unified pipeline."""
    from ai_engine.pipeline.models import IngestRequest
    from ai_engine.pipeline.unified_pipeline import process as run_pipeline

    limit = payload.limit if payload else 10

    await write_audit_event(
        db,
        actor_id=actor.actor_id,
        action="WEALTH_INGESTION_WORKER_TRIGGERED",
        entity_type="wealth_document_ingestion",
        entity_id=str(actor.organization_id),
        before=None,
        after={"limit": limit},
    )

    result = await db.execute(
        select(WealthDocumentVersion)
        .where(WealthDocumentVersion.ingestion_status == DocumentIngestionStatus.PENDING.value)
        .order_by(WealthDocumentVersion.created_at.asc())
        .limit(limit),
    )
    versions = list(result.scalars().all())

    if not versions:
        return WealthProcessPendingResponse(processed=0, indexed=0, failed=0, skipped=0)

    doc_ids = {v.document_id for v in versions}
    doc_result = await db.execute(
        select(WealthDocument).where(WealthDocument.id.in_(doc_ids)),
    )
    docs_by_id = {d.id: d for d in doc_result.scalars().all()}

    # Semaphore created inside async function (CLAUDE.md rule)
    sem = asyncio.Semaphore(3)

    async def _process_one(version: WealthDocumentVersion) -> tuple[str, str]:
        async with sem:
            if version.ingestion_status == DocumentIngestionStatus.PROCESSING.value:
                return ("skipped", str(version.id))

            version.ingestion_status = DocumentIngestionStatus.PROCESSING.value
            version.updated_by = actor.actor_id
            await db.flush()

            try:
                doc = docs_by_id[version.document_id]

                request = IngestRequest(
                    source="api",
                    org_id=actor.organization_id,
                    vertical="wealth",
                    document_id=version.document_id,
                    blob_uri=version.blob_uri or "",
                    filename=doc.title or "document.pdf",
                    fund_id=doc.portfolio_id,
                    version_id=version.id,
                )
                pipeline_result = await run_pipeline(request, db=db, actor_id=actor.actor_id)

                if pipeline_result.success:
                    version.ingestion_status = DocumentIngestionStatus.INDEXED.value
                    version.indexed_at = datetime.now(UTC)
                    result_status = "indexed"
                else:
                    version.ingestion_status = DocumentIngestionStatus.FAILED.value
                    version.ingestion_error = {
                        "stage": pipeline_result.stage,
                        "errors": pipeline_result.errors,
                    }
                    result_status = "failed"

            except Exception as e:
                logger.error("Pipeline failed for wealth version %s: %s", version.id, e, exc_info=True)
                version.ingestion_status = DocumentIngestionStatus.FAILED.value
                version.ingestion_error = {"reason": "processing_error"}
                result_status = "failed"

            version.updated_by = actor.actor_id
            return (result_status, str(version.id))

    gather_results = await asyncio.gather(
        *[_process_one(v) for v in versions],
        return_exceptions=True,
    )

    processed = len(versions)
    indexed = failed = skipped = 0
    for r in gather_results:
        if isinstance(r, Exception):
            logger.error("Unexpected error in _process_one: %s", r, exc_info=True)
            failed += 1
        elif r[0] == "indexed":
            indexed += 1
        elif r[0] == "failed":
            failed += 1
        elif r[0] == "skipped":
            skipped += 1

    return WealthProcessPendingResponse(processed=processed, indexed=indexed, failed=failed, skipped=skipped)


# ── List & get documents ─────────────────────────────────────


@router.get("", response_model=WealthDocumentPage)
async def list_documents(
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_READ_ROLES)),
    portfolio_id: uuid.UUID | None = Query(default=None),
    instrument_id: uuid.UUID | None = Query(default=None),
    domain: str | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10_000),
):
    items = await service.list_documents(
        db,
        portfolio_id=portfolio_id,
        instrument_id=instrument_id,
        domain=domain,
        limit=limit,
        offset=offset,
    )
    return WealthDocumentPage(
        items=[WealthDocumentOut.model_validate(doc) for doc in items],
        limit=limit,
        offset=offset,
    )


@router.get("/{document_id}", response_model=WealthDocumentOut)
async def get_document(
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(*_READ_ROLES)),
):
    result = await db.execute(
        select(WealthDocument).where(WealthDocument.id == document_id),
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return WealthDocumentOut.model_validate(doc)

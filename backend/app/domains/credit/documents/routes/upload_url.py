"""Upload URL endpoints — SAS URL generation + upload completion.

Two-step upload flow:
  1. ``POST /documents/upload-url`` → client receives SAS URL + upload_id
  2. ``POST /documents/upload-complete`` → server enqueues processing, returns job_id
  3. ``GET /jobs/{job_id}/stream`` → SSE events (existing endpoint)

The upload_id is the DocumentVersion UUID.  The job_id is the same UUID,
used as the Redis pub/sub channel for SSE progress streaming.
"""

from __future__ import annotations

import logging
import os
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ai_engine.pipeline.storage_routing import bronze_upload_blob_path
from app.core.db.audit import write_audit_event
from app.core.jobs.tracker import publish_event
from app.core.security.clerk_auth import Actor, get_actor, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.credit.documents import service
from app.domains.credit.documents.enums import DocumentIngestionStatus
from app.domains.credit.modules.documents.models import DocumentVersion
from app.services.storage_client import get_storage_client
from app.shared.enums import Role

logger = logging.getLogger(__name__)

_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\- ]*$")


def _sanitize_filename(raw: str) -> str:
    """Strip path traversal components from a user-supplied filename."""
    name = os.path.basename(raw)
    name = name.replace("/", "").replace("\\", "").replace("..", "")
    return name or "upload"


def _sanitize_title(raw: str) -> str:
    """Strip path traversal prefixes from a user-supplied title."""
    cleaned = re.sub(r"[\\/]+", "/", raw)
    cleaned = cleaned.replace("..", "")
    cleaned = cleaned.rsplit("/", 1)[-1] if "/" in cleaned else cleaned
    return cleaned.strip() or "Untitled"


router = APIRouter(prefix="/documents", tags=["documents.upload"])


# ── Request / Response schemas ────────────────────────────────────────────────


class UploadUrlRequest(BaseModel):
    fund_id: uuid.UUID
    filename: str
    content_type: str = "application/pdf"
    root_folder: str = "dataroom"
    subfolder_path: str | None = None
    domain: str | None = None
    title: str | None = None


class UploadUrlResponse(BaseModel):
    upload_id: str
    upload_url: str
    blob_path: str
    expires_in: int = 3600


class UploadCompleteRequest(BaseModel):
    upload_id: str
    fund_id: uuid.UUID


class UploadCompleteResponse(BaseModel):
    job_id: str
    version_id: str
    document_id: str


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.post("/upload-url", response_model=UploadUrlResponse)
async def generate_upload_url(
    payload: UploadUrlRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM)),
):
    """Generate a pre-signed upload URL and create a pending DocumentVersion.

    The client uploads directly to the URL (ADLS SAS or local file://),
    then calls ``/upload-complete`` to trigger processing.
    """
    storage = get_storage_client()

    # Sanitize filename and title BEFORE any persistence or service call
    safe_filename = _sanitize_filename(payload.filename)
    if not safe_filename or not _SAFE_FILENAME_RE.match(safe_filename):
        raise HTTPException(status_code=400, detail="Invalid filename")
    safe_title = _sanitize_title(payload.title or safe_filename)

    # Create document + pending version record
    try:
        res = await service.create_document_pending(
            db,
            fund_id=payload.fund_id,
            actor=actor,
            root_folder=payload.root_folder,
            subfolder_path=payload.subfolder_path,
            domain=payload.domain,
            title=safe_title,
            filename=safe_filename,
            content_type=payload.content_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Generate SAS upload URL
    blob_path = bronze_upload_blob_path(
        org_id=actor.organization_id,
        fund_id=payload.fund_id,
        version_id=res.version.id,
        filename=safe_filename,
    )
    upload_url = await storage.generate_upload_url(blob_path)

    # Store blob_path on version for later retrieval
    res.version.blob_uri = blob_path
    res.version.updated_by = actor.actor_id
    await db.commit()

    await write_audit_event(
        db,
        fund_id=payload.fund_id,
        actor_id=actor.actor_id,
        action="UPLOAD_URL_GENERATED",
        entity_type="document_version",
        entity_id=res.version.id,
        before=None,
        after={"blob_path": blob_path, "filename": payload.filename},
    )

    return UploadUrlResponse(
        upload_id=str(res.version.id),
        upload_url=upload_url,
        blob_path=blob_path,
    )


@router.post("/upload-complete", response_model=UploadCompleteResponse)
async def upload_complete(
    payload: UploadCompleteRequest,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM)),
):
    """Mark upload as complete and enqueue ingestion processing.

    Returns a ``job_id`` that the client can use to subscribe to SSE
    progress events at ``GET /api/v1/jobs/{job_id}/stream``.
    """
    version_id = uuid.UUID(payload.upload_id)

    result = await db.execute(
        select(DocumentVersion).where(
            DocumentVersion.fund_id == payload.fund_id,
            DocumentVersion.id == version_id,
        ),
    )
    version = result.scalar_one_or_none()
    if not version:
        raise HTTPException(status_code=404, detail="Upload not found")

    if version.ingestion_status != DocumentIngestionStatus.PENDING:
        raise HTTPException(
            status_code=409,
            detail=f"Upload already in state: {version.ingestion_status.value}",
        )

    # Mark as ready for processing
    version.ingestion_status = DocumentIngestionStatus.PROCESSING
    version.updated_by = actor.actor_id
    await db.commit()

    # Use version_id as job_id for SSE channel
    job_id = str(version_id)

    await write_audit_event(
        db,
        fund_id=payload.fund_id,
        actor_id=actor.actor_id,
        action="UPLOAD_COMPLETE",
        entity_type="document_version",
        entity_id=version_id,
        before=None,
        after={"job_id": job_id},
    )

    # Publish initial SSE event
    await publish_event(job_id, "upload_complete", {"version_id": str(version_id)})

    # TODO(Sprint 4+): Enqueue to Azure Service Bus instead of inline processing.
    # For now, processing is triggered manually via POST /documents/ingestion/process-pending
    # or will be picked up by the worker loop.

    return UploadCompleteResponse(
        job_id=job_id,
        version_id=str(version_id),
        document_id=str(version.document_id),
    )

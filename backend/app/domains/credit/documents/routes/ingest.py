from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
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


class ProcessPendingRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


class ProcessPendingResponse(BaseModel):
    processed: int
    indexed: int
    failed: int
    skipped: int


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


@router.post("/ingestion/process-pending", response_model=ProcessPendingResponse)
async def process_pending(
    fund_id: uuid.UUID,
    payload: ProcessPendingRequest | None = None,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(Role.ADMIN, Role.GP, Role.COMPLIANCE, Role.INVESTMENT_TEAM)),
):
    """Process pending document versions through the unified pipeline."""
    from ai_engine.pipeline.models import IngestRequest
    from ai_engine.pipeline.unified_pipeline import process as run_pipeline

    limit = payload.limit if payload else 10

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

    if not versions:
        return ProcessPendingResponse(processed=0, indexed=0, failed=0, skipped=0)

    # Batch-fetch parent documents to avoid N+1 queries
    doc_ids = {v.document_id for v in versions}
    doc_result = await db.execute(
        select(Document).where(
            Document.fund_id == fund_id,
            Document.id.in_(doc_ids),
        ),
    )
    docs_by_id = {d.id: d for d in doc_result.scalars().all()}

    # Semaphore created inside async function (CLAUDE.md rule)
    sem = asyncio.Semaphore(3)

    async def _process_one(version: DocumentVersion) -> tuple[str, str]:
        """Process a single version. Returns (status, version_id)."""
        async with sem:
            # Same-document concurrency guard
            if version.ingestion_status == DocumentIngestionStatus.PROCESSING:
                return ("skipped", str(version.id))

            # Mark PROCESSING
            version.ingestion_status = DocumentIngestionStatus.PROCESSING
            version.updated_by = actor.actor_id
            await db.commit()

            try:
                doc = docs_by_id[version.document_id]

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
                    version.indexed_at = datetime.now(UTC)
                    result_status = "indexed"
                else:
                    version.ingestion_status = DocumentIngestionStatus.FAILED
                    version.ingest_error = {
                        "stage": pipeline_result.stage,
                        "errors": pipeline_result.errors,
                    }
                    result_status = "failed"

            except Exception as e:
                logger.error("Pipeline failed for version %s: %s", version.id, e, exc_info=True)
                version.ingestion_status = DocumentIngestionStatus.FAILED
                version.ingest_error = {"reason": "processing_error"}
                result_status = "failed"

            version.updated_by = actor.actor_id
            await db.commit()
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

    return ProcessPendingResponse(processed=processed, indexed=indexed, failed=failed, skipped=skipped)

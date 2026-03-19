"""Wealth document service — CRUD + upload logic for wealth documents.

Mirrors Credit's documents/service.py but scoped to wealth vertical.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor
from app.domains.wealth.models.document import (
    WealthDocument,
    WealthDocumentVersion,
)
from app.shared.enums import DocumentIngestionStatus

PATH_SEGMENT_RE = re.compile(r"^[^\\/:*?\"<>|]+$")


@dataclass(frozen=True)
class UploadResult:
    document: WealthDocument
    version: WealthDocumentVersion
    blob_path: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_subfolder_path(subfolder_path: str | None) -> str:
    if not subfolder_path:
        return ""
    p = subfolder_path.strip().replace("\\", "/").strip("/")
    if not p:
        return ""
    parts = [x.strip() for x in p.split("/") if x.strip()]
    for seg in parts:
        if seg in (".", ".."):
            raise ValueError("subfolder_path contains invalid segment")
        if not PATH_SEGMENT_RE.match(seg):
            raise ValueError("subfolder_path contains invalid characters")
    return "/".join(parts)


def _safe_root_folder(root_folder: str) -> str:
    rf = root_folder.strip().strip("/")
    if not rf:
        raise ValueError("root_folder is required")
    if "/" in rf or "\\" in rf:
        raise ValueError("root_folder must be a single folder name")
    return rf


async def create_document_pending(
    db: AsyncSession,
    *,
    actor: Actor,
    portfolio_id: uuid.UUID | None,
    instrument_id: uuid.UUID | None,
    root_folder: str,
    subfolder_path: str | None,
    domain: str | None,
    title: str,
    filename: str,
    content_type: str | None,
) -> UploadResult:
    """Create WealthDocument + WealthDocumentVersion in PENDING state.

    Used by the two-step presigned URL upload flow.
    """
    rf = _safe_root_folder(root_folder)
    sub = _normalize_subfolder_path(subfolder_path)

    if not (filename.lower().endswith(".pdf") or (content_type or "").lower() == "application/pdf"):
        raise ValueError("Only PDF uploads are supported")

    dom = domain or None

    # Stable doc identity: org + root_folder + subfolder_path + title
    result = await db.execute(
        select(WealthDocument).where(
            WealthDocument.root_folder == rf,
            WealthDocument.subfolder_path == (sub or None),
            WealthDocument.title == title,
        ),
    )
    doc = result.scalar_one_or_none()

    if not doc:
        doc = WealthDocument(
            organization_id=actor.organization_id,
            portfolio_id=portfolio_id,
            instrument_id=instrument_id,
            title=title,
            filename=filename,
            content_type=content_type,
            root_folder=rf,
            subfolder_path=sub or None,
            domain=dom,
            current_version=0,
            created_by=actor.actor_id,
            updated_by=actor.actor_id,
        )
        db.add(doc)
        await db.flush()

    next_ver = int(doc.current_version or 0) + 1

    ver = WealthDocumentVersion(
        organization_id=actor.organization_id,
        document_id=doc.id,
        portfolio_id=portfolio_id,
        version_number=next_ver,
        blob_uri=None,
        blob_path=None,
        content_type=content_type or "application/pdf",
        ingestion_status=DocumentIngestionStatus.PENDING,
        uploaded_by=actor.actor_id,
        uploaded_at=_utcnow(),
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(ver)
    await db.flush()

    doc.current_version = next_ver
    doc.updated_by = actor.actor_id

    return UploadResult(document=doc, version=ver, blob_path="")


async def upload_document(
    db: AsyncSession,
    *,
    actor: Actor,
    portfolio_id: uuid.UUID | None,
    instrument_id: uuid.UUID | None,
    root_folder: str,
    subfolder_path: str | None,
    domain: str | None,
    title: str,
    filename: str,
    content_type: str | None,
    data: bytes,
    storage_client,
) -> UploadResult:
    """Single-step upload: create records + write to storage."""
    from ai_engine.pipeline.storage_routing import bronze_upload_blob_path

    rf = _safe_root_folder(root_folder)
    sub = _normalize_subfolder_path(subfolder_path)

    if not (filename.lower().endswith(".pdf") or (content_type or "").lower() == "application/pdf"):
        raise ValueError("Only PDF uploads are supported")

    dom = domain or None

    result = await db.execute(
        select(WealthDocument).where(
            WealthDocument.root_folder == rf,
            WealthDocument.subfolder_path == (sub or None),
            WealthDocument.title == title,
        ),
    )
    doc = result.scalar_one_or_none()

    if not doc:
        doc = WealthDocument(
            organization_id=actor.organization_id,
            portfolio_id=portfolio_id,
            instrument_id=instrument_id,
            title=title,
            filename=filename,
            content_type=content_type,
            root_folder=rf,
            subfolder_path=sub or None,
            domain=dom,
            current_version=0,
            created_by=actor.actor_id,
            updated_by=actor.actor_id,
        )
        db.add(doc)
        await db.flush()

    next_ver = int(doc.current_version or 0) + 1

    # Use portfolio_id or instrument_id as the "fund_id" path segment
    path_id = portfolio_id or instrument_id or doc.id
    blob_path = bronze_upload_blob_path(
        org_id=actor.organization_id,
        fund_id=path_id,
        version_id=doc.id,
        filename=f"v{next_ver}.pdf",
    )
    await storage_client.write(blob_path, data, content_type or "application/pdf")

    ver = WealthDocumentVersion(
        organization_id=actor.organization_id,
        document_id=doc.id,
        portfolio_id=portfolio_id,
        version_number=next_ver,
        blob_uri=blob_path,
        blob_path=blob_path,
        content_type=content_type or "application/pdf",
        ingestion_status=DocumentIngestionStatus.PENDING,
        uploaded_by=actor.actor_id,
        uploaded_at=_utcnow(),
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(ver)
    await db.flush()

    doc.current_version = next_ver
    doc.updated_by = actor.actor_id

    return UploadResult(document=doc, version=ver, blob_path=blob_path)


async def list_documents(
    db: AsyncSession,
    *,
    portfolio_id: uuid.UUID | None = None,
    instrument_id: uuid.UUID | None = None,
    domain: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WealthDocument]:
    stmt = select(WealthDocument).order_by(WealthDocument.updated_at.desc())
    if portfolio_id:
        stmt = stmt.where(WealthDocument.portfolio_id == portfolio_id)
    if instrument_id:
        stmt = stmt.where(WealthDocument.instrument_id == instrument_id)
    if domain:
        stmt = stmt.where(WealthDocument.domain == domain)
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())

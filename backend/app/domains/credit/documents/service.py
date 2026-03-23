from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor
from app.domains.credit.documents.constants import CANONICAL_ROOT_FOLDERS
from app.domains.credit.documents.enums import DocumentDomain, DocumentIngestionStatus
from app.domains.credit.modules.documents.models import (
    Document,
    DocumentRootFolder,
    DocumentVersion,
)
from app.shared.utils import sa_model_to_dict

PATH_SEGMENT_RE = re.compile(r"^[^\\\\/:*?\"<>|]+$")  # conservative for blob names


@dataclass(frozen=True)
class UploadResult:
    document: Document
    version: DocumentVersion
    blob_path: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def allowed_root_folders(db: AsyncSession, *, fund_id: uuid.UUID) -> set[str]:
    result = await db.execute(
        select(DocumentRootFolder.name).where(DocumentRootFolder.fund_id == fund_id, DocumentRootFolder.is_active == True),  # noqa: E712
    )
    rows = result.all()
    custom = {r[0] for r in rows}
    return set(CANONICAL_ROOT_FOLDERS).union(custom)


def _normalize_subfolder_path(subfolder_path: str | None) -> str:
    if not subfolder_path:
        return ""
    p = subfolder_path.strip().replace("\\", "/")
    p = p.strip("/")
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
    # allow spaces; only deny obvious bad path chars
    if "/" in rf or "\\" in rf:
        raise ValueError("root_folder must be a single folder name")
    return rf


async def create_root_folder(db: AsyncSession, *, fund_id: uuid.UUID, actor: Actor, name: str) -> DocumentRootFolder:
    rf = _safe_root_folder(name)
    if rf in set(CANONICAL_ROOT_FOLDERS):
        raise ValueError("root_folder already exists (canonical)")

    result = await db.execute(select(DocumentRootFolder).where(DocumentRootFolder.fund_id == fund_id, DocumentRootFolder.name == rf))
    existing = result.scalar_one_or_none()
    if existing:
        if existing.is_active:
            return existing
        before = sa_model_to_dict(existing)
        existing.is_active = True
        existing.updated_by = actor.actor_id
        await write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor.actor_id,
            action="ROOT_FOLDER_CREATED",
            entity_type="document_root_folder",
            entity_id=existing.id,
            before=before,
            after=sa_model_to_dict(existing),
        )
        await db.commit()
        await db.refresh(existing)
        return existing

    folder = DocumentRootFolder(
        fund_id=fund_id,
        access_level="internal",
        name=rf,
        is_active=True,
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(folder)
    await db.flush()
    await write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="ROOT_FOLDER_CREATED",
        entity_type="document_root_folder",
        entity_id=folder.id,
        before=None,
        after=sa_model_to_dict(folder),
    )
    await db.commit()
    await db.refresh(folder)
    return folder


async def create_document_pending(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID,
    actor: Actor,
    root_folder: str,
    subfolder_path: str | None,
    domain: str | None,
    title: str,
    filename: str,
    content_type: str | None,
) -> UploadResult:
    """Create a Document + DocumentVersion in PENDING state (no blob upload).

    Used by the two-step SAS URL upload flow:
      1. This function creates the records
      2. Client uploads directly to SAS URL
      3. ``upload-complete`` triggers ingestion
    """
    rf = _safe_root_folder(root_folder)
    if rf not in await allowed_root_folders(db, fund_id=fund_id):
        raise ValueError("root_folder is not allowed")

    sub = _normalize_subfolder_path(subfolder_path)
    folder_path = rf if not sub else f"{rf}/{sub}"

    if not (filename.lower().endswith(".pdf") or (content_type or "").lower() == "application/pdf"):
        raise ValueError("Only PDF uploads are supported for Data Room ingest")

    dom = None
    if domain:
        try:
            dom = DocumentDomain(domain)
        except Exception:
            dom = DocumentDomain.OTHER

    # Stable doc identity by folder_path+title within fund
    result = await db.execute(
        select(Document).where(
            Document.fund_id == fund_id,
            Document.root_folder == rf,
            Document.folder_path == folder_path,
            Document.title == title,
        ),
    )
    doc = result.scalar_one_or_none()

    if not doc:
        doc = Document(
            fund_id=fund_id,
            access_level="internal",
            source="dataroom",
            document_type="DATAROOM",
            title=title,
            status="uploaded",
            current_version=0,
            root_folder=rf,
            folder_path=folder_path,
            domain=dom,
            original_filename=filename,
            content_type=content_type,
            created_by=actor.actor_id,
            updated_by=actor.actor_id,
        )
        db.add(doc)
        await db.flush()

    next_ver = int(doc.current_version or 0) + 1

    ver = DocumentVersion(
        fund_id=fund_id,
        access_level="internal",
        document_id=doc.id,
        version_number=next_ver,
        blob_uri=None,  # Set later after SAS URL generation
        blob_path=None,
        checksum=None,
        file_size_bytes=None,
        is_final=False,
        content_type=content_type or "application/pdf",
        uploaded_by=actor.actor_id,
        uploaded_at=_utcnow(),
        ingestion_status=DocumentIngestionStatus.PENDING,
        meta={},
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(ver)
    await db.flush()

    doc.current_version = next_ver
    doc.updated_by = actor.actor_id
    await db.commit()

    return UploadResult(document=doc, version=ver, blob_path="")


async def list_documents(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID,
    limit: int,
    offset: int,
    root_folder: str | None,
    domain: str | None,
    updated_after: datetime | None,
    title_q: str | None,
) -> list[Document]:
    stmt = select(Document).where(Document.fund_id == fund_id).order_by(Document.updated_at.desc())
    if root_folder:
        stmt = stmt.where(Document.root_folder == root_folder)
    if domain:
        try:
            stmt = stmt.where(Document.domain == DocumentDomain(domain))
        except Exception:
            # unknown domain filter -> empty result
            return []
    if updated_after:
        stmt = stmt.where(Document.updated_at > updated_after)
    if title_q:
        stmt = stmt.where(Document.title.ilike(f"%{title_q}%"))
    stmt = stmt.offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())

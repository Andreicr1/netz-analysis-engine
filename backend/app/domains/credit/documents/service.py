from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db.audit import write_audit_event
from app.core.security.auth import Actor
from app.domains.credit.documents.constants import CANONICAL_ROOT_FOLDERS
from app.domains.credit.documents.enums import DocumentDomain, DocumentIngestionStatus
from app.domains.credit.modules.documents.models import (
    Document,
    DocumentRootFolder,
    DocumentVersion,
)
from app.services.blob_storage import upload_bytes_append_only
from app.services.search_index import AzureSearchMetadataClient
from app.shared.utils import sa_model_to_dict

PATH_SEGMENT_RE = re.compile(r"^[^\\\\/:*?\"<>|]+$")  # conservative for blob names


@dataclass(frozen=True)
class UploadResult:
    document: Document
    version: DocumentVersion
    blob_path: str


def _utcnow() -> datetime:
    return datetime.now(UTC)


def allowed_root_folders(db: Session, *, fund_id: uuid.UUID) -> set[str]:
    rows = db.execute(
        select(DocumentRootFolder.name).where(DocumentRootFolder.fund_id == fund_id, DocumentRootFolder.is_active == True),  # noqa: E712
    ).all()
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


def create_root_folder(db: Session, *, fund_id: uuid.UUID, actor: Actor, name: str) -> DocumentRootFolder:
    rf = _safe_root_folder(name)
    if rf in set(CANONICAL_ROOT_FOLDERS):
        raise ValueError("root_folder already exists (canonical)")

    existing = db.execute(select(DocumentRootFolder).where(DocumentRootFolder.fund_id == fund_id, DocumentRootFolder.name == rf)).scalar_one_or_none()
    if existing:
        if existing.is_active:
            return existing
        before = sa_model_to_dict(existing)
        existing.is_active = True
        existing.updated_by = actor.actor_id
        write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor.actor_id,
            action="ROOT_FOLDER_CREATED",
            entity_type="document_root_folder",
            entity_id=existing.id,
            before=before,
            after=sa_model_to_dict(existing),
        )
        db.commit()
        db.refresh(existing)
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
    db.flush()
    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="ROOT_FOLDER_CREATED",
        entity_type="document_root_folder",
        entity_id=folder.id,
        before=None,
        after=sa_model_to_dict(folder),
    )
    db.commit()
    db.refresh(folder)
    return folder


def upload_document(
    db: Session,
    *,
    fund_id: uuid.UUID,
    actor: Actor,
    root_folder: str,
    subfolder_path: str | None,
    domain: str | None,
    title: str,
    filename: str,
    content_type: str | None,
    data: bytes,
) -> UploadResult:
    rf = _safe_root_folder(root_folder)
    if rf not in allowed_root_folders(db, fund_id=fund_id):
        raise ValueError("root_folder is not allowed")

    sub = _normalize_subfolder_path(subfolder_path)
    folder_path = rf if not sub else f"{rf}/{sub}"

    # EPIC 3A: PDFs only for now (wire-governed data room)
    if not (filename.lower().endswith(".pdf") or (content_type or "").lower() == "application/pdf"):
        raise ValueError("Only PDF uploads are supported for Data Room ingest")

    dom = None
    if domain:
        try:
            dom = DocumentDomain(domain)
        except Exception:
            dom = DocumentDomain.OTHER

    # Stable doc identity by folder_path+title within fund
    doc = db.execute(
        select(Document).where(
            Document.fund_id == fund_id,
            Document.root_folder == rf,
            Document.folder_path == folder_path,
            Document.title == title,
        ),
    ).scalar_one_or_none()

    created = False
    if not doc:
        created = True
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
        db.flush()

    next_ver = int(doc.current_version or 0) + 1

    # Blob path convention (container dataroom; path is inside container)
    blob_rel = f"{folder_path}/{doc.id}/v{next_ver}.pdf"
    write_res = upload_bytes_append_only(
        container=settings.AZURE_STORAGE_DATAROOM_CONTAINER,
        blob_name=blob_rel,
        data=data,
        content_type="application/pdf",
        metadata={"fund_id": str(fund_id), "document_id": str(doc.id), "version": str(next_ver)},
    )

    ver = DocumentVersion(
        fund_id=fund_id,
        access_level="internal",
        document_id=doc.id,
        version_number=next_ver,
        blob_uri=write_res.blob_uri,
        blob_path=blob_rel,
        checksum=write_res.sha256,
        file_size_bytes=write_res.size_bytes,
        is_final=False,
        content_type="application/pdf",
        uploaded_by=actor.actor_id,
        uploaded_at=_utcnow(),
        ingestion_status=DocumentIngestionStatus.PENDING,
        meta={"etag": write_res.etag, "version_id": write_res.version_id},
        created_by=actor.actor_id,
        updated_by=actor.actor_id,
    )
    db.add(ver)
    db.flush()

    doc_before = sa_model_to_dict(doc)
    doc.current_version = next_ver
    doc.blob_uri = write_res.blob_uri
    doc.sha256 = write_res.sha256
    doc.updated_by = actor.actor_id

    if created:
        write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor.actor_id,
            action="DOCUMENT_UPLOADED",
            entity_type="document",
            entity_id=doc.id,
            before=None,
            after=sa_model_to_dict(doc),
        )

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="DOCUMENT_VERSION_CREATED",
        entity_type="document_version",
        entity_id=ver.id,
        before=None,
        after=sa_model_to_dict(ver),
    )
    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="DOCUMENT_UPLOADED",  # update snapshot on new version
        entity_type="document",
        entity_id=doc.id,
        before=doc_before,
        after=sa_model_to_dict(doc),
    )

    indexed = False
    if settings.AZURE_SEARCH_ENDPOINT and settings.SEARCH_INDEX_NAME:
        client = AzureSearchMetadataClient()
        client.upsert_dataroom_metadata(
            items=[
                {
                    "id": f"{fund_id}:{doc.id}:v{next_ver}",
                    "fund_id": str(fund_id),
                    "document_id": str(doc.id),
                    "title": doc.title,
                    "root_folder": doc.root_folder,
                    "folder_path": doc.folder_path,
                    "domain": (doc.domain.value if doc.domain else None),
                    "version_blob_path": ver.blob_path,
                    "uploaded_at": ver.uploaded_at.isoformat() if ver.uploaded_at else None,
                },
            ],
        )
        indexed = True

    write_audit_event(
        db,
        fund_id=fund_id,
        actor_id=actor.actor_id,
        action="DOCUMENT_INDEXED",
        entity_type="document_version",
        entity_id=ver.id,
        before=None,
        after={
            "indexed": indexed,
            "index": settings.SEARCH_INDEX_NAME,
            "id": f"{fund_id}:{doc.id}:v{next_ver}",
            "blob_path": ver.blob_path,
        },
    )

    db.commit()
    db.refresh(doc)
    db.refresh(ver)
    return UploadResult(document=doc, version=ver, blob_path=blob_rel)


def list_documents(
    db: Session,
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
    return list(db.execute(stmt).scalars().all())


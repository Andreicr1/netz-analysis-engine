from __future__ import annotations

import dataclasses
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security.clerk_auth import Actor, get_actor, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.services.blob_storage import generate_read_link, list_blobs
from app.services.dataroom_ingest import ingest_document_version, upload_dataroom_document
from app.services.search_index import AzureSearchMetadataClient

router = APIRouter(prefix="/api/dataroom", tags=["Dataroom"])
data_room_router = APIRouter(prefix="/api/data-room", tags=["Data Room"])


def _as_of() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_folder_path(path: str | None) -> str:
    raw = (path or "").strip().lstrip("/")
    if raw and not raw.endswith("/"):
        raw = f"{raw}/"
    return raw


def _basename(path: str) -> str:
    value = (path or "").rstrip("/")
    if not value:
        return ""
    return value.split("/")[-1]


def _access_label() -> str:
    return "External Eligible"


def _to_item(entry) -> dict:
    kind = "folder" if entry.is_folder else "file"
    return {
        "id": entry.name,
        "name": _basename(entry.name),
        "kind": kind,
        "path": entry.name,
        "mimeType": None if entry.is_folder else entry.content_type,
        "size": None if entry.is_folder else entry.size_bytes,
        "lastModified": None if entry.is_folder else entry.last_modified,
        "accessLabel": _access_label(),
    }


def _build_tree_node(path: str) -> dict:
    return {
        "id": path,
        "name": _basename(path),
        "path": path,
        "children": [],
        "childrenCount": 0,
    }


def _build_folder_tree(container: str) -> list[dict]:
    roots = [e for e in list_blobs(container=container, prefix=None) if e.is_folder]
    nodes_by_path: dict[str, dict] = {}

    for root in roots:
        nodes_by_path[root.name] = _build_tree_node(root.name)

    queue = [r.name for r in roots]
    while queue:
        folder = queue.pop(0)
        child_entries = [e for e in list_blobs(container=container, prefix=folder) if e.is_folder]
        parent = nodes_by_path[folder]
        parent["childrenCount"] = len(child_entries)
        children_nodes: list[dict] = []
        for child in child_entries:
            child_node = nodes_by_path.get(child.name)
            if child_node is None:
                child_node = _build_tree_node(child.name)
                nodes_by_path[child.name] = child_node
                queue.append(child.name)
            children_nodes.append(child_node)
        parent["children"] = children_nodes

    return [nodes_by_path[r.name] for r in roots]


@router.post("/documents")
async def upload_document(
    fund_id: uuid.UUID = Form(...),
    title: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN"])),
):
    if not actor.can_access_fund(fund_id) and not settings.AUTHZ_BYPASS_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden for this fund")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="file is empty")
    res = upload_dataroom_document(
        db,
        fund_id=fund_id,
        actor=actor,
        title=title or file.filename or "Dataroom Document",
        filename=file.filename or "document",
        content_type=file.content_type,
        data=data,
    )
    return {
        "document_id": str(res.document.id),
        "version_number": res.version.version_number,
        "idempotent": res.idempotent,
        "sha256": res.document.sha256,
        "blob_uri": res.document.blob_uri,
    }


@router.post("/documents/{document_id}/ingest")
async def ingest_document(
    document_id: uuid.UUID,
    fund_id: uuid.UUID = Query(...),
    version_number: int | None = Query(None),
    store_artifacts_in_evidence: bool = Query(True),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN"])),
):
    if not actor.can_access_fund(fund_id) and not settings.AUTHZ_BYPASS_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden for this fund")
    try:
        return ingest_document_version(
            db,
            fund_id=fund_id,
            actor=actor,
            document_id=document_id,
            version_number=version_number,
            store_artifacts_in_evidence=store_artifacts_in_evidence,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/search")
async def search(
    fund_id: uuid.UUID = Query(...),
    q: str = Query(..., min_length=2, max_length=400),
    top: int = Query(5, ge=1, le=20),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
):
    if not actor.can_access_fund(fund_id) and not settings.AUTHZ_BYPASS_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden for this fund")
    client = AzureSearchMetadataClient()
    hits = client.search(q=q, fund_id=str(fund_id), top=top)
    return {"query": q, "count": len(hits), "hits": [h.__dict__ for h in hits]}


@router.get("/browse")
async def browse(
    prefix: str = Query("", max_length=500),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
):
    """List folders and files in the dataroom blob container.
    Uses virtual directory (delimiter-based) listing.
    """
    container = settings.AZURE_STORAGE_DATAROOM_CONTAINER
    try:
        entries = list_blobs(container=container, prefix=prefix or None)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list dataroom storage: {exc}",
        )
    return {
        "container": container,
        "prefix": prefix or "",
        "count": len(entries),
        "items": [dataclasses.asdict(e) for e in entries],
    }


@data_room_router.get("/tree")
async def get_tree(
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
):
    container = settings.AZURE_STORAGE_DATAROOM_CONTAINER
    try:
        folders = _build_folder_tree(container)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list dataroom tree: {exc}",
        )
    return {
        "folders": folders,
        "asOf": _as_of(),
    }


@data_room_router.get("/list")
async def list_items(
    path: str = Query("", max_length=500),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
):
    container = settings.AZURE_STORAGE_DATAROOM_CONTAINER
    prefix = _normalize_folder_path(path)
    try:
        entries = list_blobs(container=container, prefix=prefix or None)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list dataroom items: {exc}",
        )

    folders_count = len([e for e in entries if e.is_folder])
    files_count = len([e for e in entries if not e.is_folder])

    return {
        "path": prefix,
        "items": [_to_item(e) for e in entries],
        "totals": {"folders": folders_count, "files": files_count},
        "asOf": _as_of(),
    }


@data_room_router.get("/file-link")
async def file_link(
    path: str = Query(..., max_length=1000),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
):
    normalized = (path or "").strip().lstrip("/")
    if not normalized or normalized.endswith("/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="path must point to a file")

    container = settings.AZURE_STORAGE_DATAROOM_CONTAINER
    try:
        signed_view_url = generate_read_link(container=container, blob_name=normalized, as_download=False)
        signed_download_url = generate_read_link(container=container, blob_name=normalized, as_download=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate dataroom link: {exc}",
        )

    return {
        "path": normalized,
        "signedViewUrl": signed_view_url,
        "signedDownloadUrl": signed_download_url,
        "asOf": _as_of(),
    }


PIPELINE_CONTAINER = "investment-pipeline-intelligence"

_PIPELINE_INTERNAL_SUFFIXES = frozenset({
    ".json", ".jsonl", ".log", ".tmp", ".pyc", ".gz",
})


def _is_user_visible_pipeline(entry) -> bool:
    """Exclude AI engine artefacts from user-facing listings."""
    if entry.is_folder:
        return True
    name = (entry.name or "").lower()
    return not any(name.endswith(ext) for ext in _PIPELINE_INTERNAL_SUFFIXES)


@data_room_router.get("/pipeline/list")
async def list_pipeline_items(
    path: str = Query("", max_length=500),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
):
    """List folders and files in the investment-pipeline-intelligence container."""
    prefix = _normalize_folder_path(path)
    try:
        entries = list_blobs(container=PIPELINE_CONTAINER, prefix=prefix or None)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to list pipeline storage: {exc}",
        )

    entries = [e for e in entries if _is_user_visible_pipeline(e)]

    folders_count = len([e for e in entries if e.is_folder])
    files_count = len([e for e in entries if not e.is_folder])

    return {
        "path": prefix,
        "items": [_to_item(e) for e in entries],
        "totals": {"folders": folders_count, "files": files_count},
        "asOf": _as_of(),
    }


@data_room_router.get("/pipeline/file-link")
async def pipeline_file_link(
    path: str = Query(..., max_length=1000),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN", "AUDITOR"])),
):
    """Generate signed view/download URLs for a file in the pipeline container."""
    normalized = (path or "").strip().lstrip("/")
    if not normalized or normalized.endswith("/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="path must point to a file")

    try:
        signed_view_url = generate_read_link(container=PIPELINE_CONTAINER, blob_name=normalized, as_download=False)
        signed_download_url = generate_read_link(container=PIPELINE_CONTAINER, blob_name=normalized, as_download=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to generate pipeline link: {exc}",
        )

    return {
        "path": normalized,
        "signedViewUrl": signed_view_url,
        "signedDownloadUrl": signed_download_url,
        "asOf": _as_of(),
    }


@data_room_router.post("/upload")
async def upload_to_path(
    path: str = Form(""),
    file: UploadFile = File(...),
    fund_id: uuid.UUID = Form(...),
    metadata: str | None = Form(None),
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_role(["INVESTMENT_TEAM", "COMPLIANCE", "GP", "ADMIN"])),
):
    if not actor.can_access_fund(fund_id) and not settings.AUTHZ_BYPASS_ENABLED:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden for this fund")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="file is empty")

    normalized_path = _normalize_folder_path(path)
    title = file.filename or "document"
    if metadata:
        title = title

    result = upload_dataroom_document(
        db,
        fund_id=fund_id,
        actor=actor,
        title=title,
        filename=f"{normalized_path}{file.filename or 'document'}",
        content_type=file.content_type,
        data=data,
    )

    item = {
        "id": str(result.document.id),
        "name": file.filename or "document",
        "kind": "file",
        "path": f"{normalized_path}{file.filename or 'document'}",
        "mimeType": file.content_type,
        "size": len(data),
        "lastModified": _as_of(),
        "accessLabel": _access_label(),
    }

    return {
        "item": item,
        "documentId": str(result.document.id),
        "versionNumber": result.version.version_number,
        "idempotent": result.idempotent,
        "asOf": _as_of(),
    }

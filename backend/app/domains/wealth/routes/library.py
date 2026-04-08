"""Wealth Library — HTTP API surface (Phase 2).

Implements §4.8 of the Wealth Library spec
(``docs/superpowers/specs/2026-04-08-wealth-library.md``). Ten
endpoints expose the library to the Svelte 5 shell:

* ``GET    /library/tree``                          — L1+L2 nested tree
* ``GET    /library/folders/{path:path}/children``  — cursor-paginated children
* ``GET    /library/search``                        — tsvector full-text search
* ``GET    /library/pins``                          — pinned + starred + recent
* ``POST   /library/pins``                          — idempotent pin create
* ``DELETE /library/pins/{id}``                     — pin removal
* ``GET    /library/documents/{id}``                — detail + ``recent`` upsert
* ``POST   /library/bundle``                        — dispatch bundle worker
* ``GET    /library/bundle/{bundle_id}/download``   — stream ZIP from storage
* ``GET    /library/redirect-dd-report/{old_fund_id}/{old_report_id}`` — 308

All routes rely on the ``get_db_with_rls`` dependency for tenant
isolation; the matching subselect-based RLS policies on
``wealth_library_index`` and ``wealth_library_pins`` enforce
``organization_id`` (and per-user scope on the pins table) at the
database layer. Handlers therefore avoid threading ``organization_id``
into every WHERE clause and instead let RLS do its job, with one
exception: the ``audit_events`` table has RLS disabled (TimescaleDB
columnstore incompatibility) so the bundle download endpoint passes
``organization_id`` explicitly when writing the audit row.

Sanitisation of free-form metadata happens inside the
``LibraryDocumentDetail`` Pydantic model_validator (see
``schemas/sanitized.py``); routes never inspect raw quant fields.
"""

from __future__ import annotations

import base64
import json
import urllib.parse
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ai_engine.pipeline.storage_routing import gold_library_bundle_path
from app.core.db.audit import write_audit_event
from app.core.security.clerk_auth import Actor, CurrentUser, get_actor, get_current_user
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.wealth.schemas.sanitized import (
    LibraryBundleAccepted,
    LibraryDocumentDetail,
    LibraryNode,
    LibraryNodePage,
    LibraryPin,
    LibraryPinCreate,
    LibraryPinsResponse,
    LibrarySearchResult,
    LibraryTree,
)
from app.services.storage_client import get_storage_client

logger = structlog.get_logger()

router = APIRouter(prefix="/library", tags=["wealth-library"])


_PAGE_LIMIT_DEFAULT = 50
_PAGE_LIMIT_MAX = 200


# ── Path & cursor encoding ──────────────────────────────────────────


def _decode_folder_path(raw: str) -> list[str]:
    """Decode a URL path component into a ``folder_path`` text array.

    The frontend passes each folder segment URL-encoded and joined with
    ``/``. We split on the unescaped slash boundary and ``urldecode``
    each segment back to the canonical label that lives in
    ``wealth_library_index.folder_path``. Empty trailing segments
    (caused by trailing slashes) are dropped.
    """
    if not raw:
        return []
    parts = [urllib.parse.unquote(p) for p in raw.split("/") if p]
    # Reject any segment containing a NUL byte — tightens injection surface
    if any("\x00" in p for p in parts):
        raise HTTPException(status_code=400, detail="Invalid folder path")
    return parts


def _encode_folder_path(parts: list[str]) -> str:
    """Inverse of ``_decode_folder_path`` — joins URL-encoded segments."""
    return "/".join(urllib.parse.quote(p, safe="") for p in parts)


def _encode_cursor(updated_at: datetime, row_id: uuid.UUID) -> str:
    payload = json.dumps(
        {"u": updated_at.isoformat(), "i": str(row_id)},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_cursor(raw: str | None) -> tuple[datetime, uuid.UUID] | None:
    """Validate and decode a pagination cursor.

    The cursor is a base64-encoded JSON object ``{"u": ISO datetime,
    "i": UUID}``. Anything that fails to parse — wrong base64, missing
    keys, malformed UUID, malformed timestamp — raises 400 so a forged
    cursor cannot reach the SQL layer.
    """
    if not raw:
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")))
        return (
            datetime.fromisoformat(payload["u"]),
            uuid.UUID(payload["i"]),
        )
    except Exception as exc:  # noqa: BLE001 — defensive boundary check
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


def _file_node_from_row(row: Any) -> LibraryNode:
    """Build a ``LibraryNode`` (file) from a wealth_library_index row."""
    return LibraryNode(
        node_type="file",
        path=_encode_folder_path(list(row.folder_path or [])),
        label=row.title,
        id=row.id,
        kind=row.kind,
        title=row.title,
        subtitle=row.subtitle,
        status=row.status,
        language=row.language,
        version=row.version,
        is_current=row.is_current,
        entity_kind=row.entity_kind,
        entity_label=row.entity_label,
        entity_slug=row.entity_slug,
        confidence=float(row.confidence_score) if row.confidence_score is not None else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ── GET /library/tree ───────────────────────────────────────────────


@router.get(
    "/tree",
    response_model=LibraryTree,
    summary="Library navigation tree (L1 + L2)",
)
async def get_library_tree(
    response: Response,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — RLS scope
) -> LibraryTree:
    """Return the L1 + L2 folder tree.

    Children below L2 are fetched lazily via the children endpoint.
    Counts and ``last_updated_at`` are aggregated by SQL so the client
    can render badges without enumerating files.
    """
    result = await db.execute(
        text(
            """
            SELECT
                folder_path[1]                AS l1,
                folder_path[2]                AS l2,
                count(*)                      AS child_count,
                max(updated_at)               AS last_updated_at
            FROM wealth_library_index
            WHERE folder_path IS NOT NULL
              AND array_length(folder_path, 1) >= 1
            GROUP BY folder_path[1], folder_path[2]
            ORDER BY folder_path[1], folder_path[2] NULLS FIRST
            """,
        ),
    )
    rows = result.fetchall()

    # Aggregate into a nested structure: { l1: {count, updated_at, children: {l2: ...}} }
    l1_map: dict[str, dict[str, Any]] = {}
    for row in rows:
        l1 = row.l1
        if l1 is None:
            continue
        bucket = l1_map.setdefault(
            l1,
            {"count": 0, "updated_at": None, "children": []},
        )
        bucket["count"] += int(row.child_count)
        if row.last_updated_at is not None and (
            bucket["updated_at"] is None or row.last_updated_at > bucket["updated_at"]
        ):
            bucket["updated_at"] = row.last_updated_at
        if row.l2 is not None:
            bucket["children"].append(
                {
                    "label": row.l2,
                    "count": int(row.child_count),
                    "updated_at": row.last_updated_at,
                },
            )

    roots: list[LibraryNode] = []
    for l1, bucket in l1_map.items():
        roots.append(
            LibraryNode(
                node_type="folder",
                path=_encode_folder_path([l1]),
                label=l1,
                child_count=bucket["count"],
                last_updated_at=bucket["updated_at"],
            ),
        )
        for child in bucket["children"]:
            roots.append(
                LibraryNode(
                    node_type="folder",
                    path=_encode_folder_path([l1, child["label"]]),
                    label=child["label"],
                    child_count=child["count"],
                    last_updated_at=child["updated_at"],
                ),
            )

    response.headers["Cache-Control"] = "private, max-age=30"
    return LibraryTree(roots=roots, generated_at=datetime.now(timezone.utc))


# ── GET /library/folders/{path:path}/children ───────────────────────


@router.get(
    "/folders/{path:path}/children",
    response_model=LibraryNodePage,
    summary="List children of a Library folder",
)
async def list_folder_children(
    path: str,
    response: Response,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — RLS scope
) -> LibraryNodePage:
    """Cursor-paginated listing of files inside a folder.

    The path parameter is the URL-encoded ``folder_path`` prefix. We
    match rows whose ``folder_path[1:N]`` exactly equals the supplied
    prefix array — children that live in deeper subfolders are
    included so the file pane is flat (the tree handles the hierarchy).
    """
    prefix = _decode_folder_path(path)
    if not prefix:
        raise HTTPException(status_code=400, detail="Folder path is required")

    cursor_decoded = _decode_cursor(cursor)
    params: dict[str, Any] = {
        "prefix": prefix,
        "depth": len(prefix),
        "limit": limit + 1,
    }
    cursor_clause = ""
    if cursor_decoded is not None:
        cursor_clause = "AND (updated_at, id) < (:cursor_updated_at, :cursor_id)"
        params["cursor_updated_at"] = cursor_decoded[0]
        params["cursor_id"] = str(cursor_decoded[1])

    sql = f"""
        SELECT
            id, kind, title, subtitle, status, language, version, is_current,
            entity_kind, entity_label, entity_slug, confidence_score,
            folder_path, created_at, updated_at
        FROM wealth_library_index
        WHERE folder_path[1:array_length(:prefix::text[], 1)] = :prefix::text[]
          AND array_length(folder_path, 1) >= :depth
          {cursor_clause}
        ORDER BY updated_at DESC, id DESC
        LIMIT :limit
    """  # noqa: S608 — only the cursor_clause is injected and it's a constant string
    result = await db.execute(text(sql), params)
    rows = result.fetchall()

    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [_file_node_from_row(r) for r in page_rows]

    next_cursor: str | None = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(last.updated_at, last.id)

    response.headers["Cache-Control"] = "private, max-age=30"
    return LibraryNodePage(items=items, next_cursor=next_cursor)


# ── GET /library/search ─────────────────────────────────────────────


@router.get(
    "/search",
    response_model=LibrarySearchResult,
    summary="Full-text search across the Library index",
)
async def search_library(
    response: Response,
    q: str = Query(..., min_length=1, max_length=200),
    kind: list[str] | None = Query(default=None),
    status_filter: list[str] | None = Query(default=None, alias="status"),
    from_date: datetime | None = Query(default=None, alias="from"),
    to_date: datetime | None = Query(default=None, alias="to"),
    entity_id: uuid.UUID | None = Query(default=None),
    language: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=_PAGE_LIMIT_DEFAULT, ge=1, le=_PAGE_LIMIT_MAX),
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — RLS scope
) -> LibrarySearchResult:
    """Full-text search via the generated ``search_vector`` column.

    Filters are AND-composed. The cursor uses the same
    ``(updated_at, id)`` keyset as the folder children endpoint so
    pagination is stable across queries.
    """
    cursor_decoded = _decode_cursor(cursor)
    where: list[str] = ["search_vector @@ websearch_to_tsquery('simple', :q)"]
    params: dict[str, Any] = {"q": q, "limit": limit + 1}

    if kind:
        where.append("kind = ANY(:kind)")
        params["kind"] = kind
    if status_filter:
        where.append("status = ANY(:status_filter)")
        params["status_filter"] = status_filter
    if from_date is not None:
        where.append("updated_at >= :from_date")
        params["from_date"] = from_date
    if to_date is not None:
        where.append("updated_at <= :to_date")
        params["to_date"] = to_date
    if entity_id is not None:
        where.append("entity_id = :entity_id")
        params["entity_id"] = entity_id
    if language is not None:
        where.append("language = :language")
        params["language"] = language
    if cursor_decoded is not None:
        where.append("(updated_at, id) < (:cursor_updated_at, :cursor_id)")
        params["cursor_updated_at"] = cursor_decoded[0]
        params["cursor_id"] = str(cursor_decoded[1])

    sql = f"""
        SELECT
            id, kind, title, subtitle, status, language, version, is_current,
            entity_kind, entity_label, entity_slug, confidence_score,
            folder_path, created_at, updated_at
        FROM wealth_library_index
        WHERE {' AND '.join(where)}
        ORDER BY updated_at DESC, id DESC
        LIMIT :limit
    """  # noqa: S608 — every WHERE fragment uses bind params, no string interpolation
    result = await db.execute(text(sql), params)
    rows = result.fetchall()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [_file_node_from_row(r) for r in page_rows]

    next_cursor: str | None = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(last.updated_at, last.id)

    response.headers["Cache-Control"] = "private, no-store"
    return LibrarySearchResult(items=items, next_cursor=next_cursor, query=q)


# ── Pin helpers ─────────────────────────────────────────────────────


def _pin_from_row(row: Any) -> LibraryPin:
    return LibraryPin(
        id=row.id,
        pin_type=row.pin_type,
        library_index_id=row.library_index_id,
        library_path=_encode_folder_path(list(row.folder_path or [])),
        label=row.title,
        kind=row.kind,
        created_at=row.created_at,
        last_accessed_at=row.last_accessed_at,
        position=row.position,
    )


# ── GET /library/pins ───────────────────────────────────────────────


@router.get(
    "/pins",
    response_model=LibraryPinsResponse,
    summary="List the caller's pinned/starred/recent Library items",
)
async def list_pins(
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — RLS scope
) -> LibraryPinsResponse:
    """Return all three pin lists in a single round-trip.

    Pins are scoped per user via the composite RLS policy on
    ``wealth_library_pins`` (see migration 0091). The JOIN with the
    index brings in folder_path/title for the badge label so the UI
    can render without a second call.
    """
    result = await db.execute(
        text(
            """
            SELECT
                p.id, p.pin_type, p.library_index_id,
                p.created_at, p.last_accessed_at, p.position,
                i.folder_path, i.title, i.kind
            FROM wealth_library_pins p
            JOIN wealth_library_index i ON i.id = p.library_index_id
            ORDER BY p.pin_type, p.last_accessed_at DESC
            """,
        ),
    )
    rows = result.fetchall()

    grouped: dict[str, list[LibraryPin]] = {"pinned": [], "starred": [], "recent": []}
    for row in rows:
        grouped.setdefault(row.pin_type, []).append(_pin_from_row(row))

    return LibraryPinsResponse(
        pinned=grouped["pinned"],
        starred=grouped["starred"],
        recent=grouped["recent"],
    )


# ── POST /library/pins ──────────────────────────────────────────────


@router.post(
    "/pins",
    response_model=LibraryPin,
    status_code=status.HTTP_200_OK,
    summary="Create or refresh a Library pin",
)
async def create_pin(
    body: LibraryPinCreate,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> LibraryPin:
    """Idempotent pin creation.

    On UNIQUE conflict (the user already has this pin) we update
    ``last_accessed_at`` and return the existing row with HTTP 200 —
    NOT 409 — per spec §4.8. The composite RLS policy guarantees the
    INSERT only sees the caller's row.
    """
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Organization required")

    result = await db.execute(
        text(
            """
            INSERT INTO wealth_library_pins (
                organization_id, user_id, library_index_id, pin_type, position
            )
            VALUES (:org_id, :user_id, :library_index_id, :pin_type, :position)
            ON CONFLICT (organization_id, user_id, library_index_id, pin_type)
            DO UPDATE SET
                last_accessed_at = now(),
                position = COALESCE(EXCLUDED.position, wealth_library_pins.position)
            RETURNING id, pin_type, library_index_id, created_at,
                      last_accessed_at, position
            """,
        ),
        {
            "org_id": str(actor.organization_id),
            "user_id": actor.actor_id,
            "library_index_id": str(body.library_index_id),
            "pin_type": body.pin_type,
            "position": body.position,
        },
    )
    pin_row = result.one()

    # Fetch denormalised folder_path/title/kind for the response
    detail = await db.execute(
        text(
            """
            SELECT folder_path, title, kind
            FROM wealth_library_index
            WHERE id = :id
            """,
        ),
        {"id": str(body.library_index_id)},
    )
    detail_row = detail.one_or_none()
    if detail_row is None:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Library entry not found")

    await db.commit()
    return LibraryPin(
        id=pin_row.id,
        pin_type=pin_row.pin_type,
        library_index_id=pin_row.library_index_id,
        library_path=_encode_folder_path(list(detail_row.folder_path or [])),
        label=detail_row.title,
        kind=detail_row.kind,
        created_at=pin_row.created_at,
        last_accessed_at=pin_row.last_accessed_at,
        position=pin_row.position,
    )


# ── DELETE /library/pins/{id} ───────────────────────────────────────


@router.delete(
    "/pins/{pin_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a Library pin",
)
async def delete_pin(
    pin_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — RLS scope
) -> Response:
    """Delete a pin owned by the caller.

    The composite RLS policy ensures rows belonging to other users are
    invisible — the DELETE either matches the caller's row or no row
    at all (still 204, idempotent).
    """
    await db.execute(
        text("DELETE FROM wealth_library_pins WHERE id = :id"),
        {"id": str(pin_id)},
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── GET /library/documents/{id} ─────────────────────────────────────


@router.get(
    "/documents/{document_id}",
    response_model=LibraryDocumentDetail,
    summary="Library document detail (records `recent` view)",
)
async def get_document_detail(
    document_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> LibraryDocumentDetail:
    """Detail view + automatic ``recent`` pin upsert.

    Server-side recording of "recently viewed" prevents the client
    from forgetting (or lying about) which documents the user opened.
    The TTL worker (lock 900_081) bounds the per-user list to 20.
    """
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Organization required")

    result = await db.execute(
        text(
            """
            SELECT
                id, source_table, source_id, kind, title, subtitle,
                status, language, version, is_current,
                entity_kind, entity_id, entity_slug, entity_label,
                folder_path, author_id, approver_id, approved_at,
                created_at, updated_at, confidence_score, decision_anchor,
                storage_path, metadata
            FROM wealth_library_index
            WHERE id = :id
            """,
        ),
        {"id": str(document_id)},
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # Side effect: upsert the `recent` pin so the user's history is
    # populated server-side. Failures are non-fatal — the read must
    # still succeed even if the pins table is unavailable.
    try:
        await db.execute(
            text(
                """
                INSERT INTO wealth_library_pins (
                    organization_id, user_id, library_index_id, pin_type
                )
                VALUES (:org_id, :user_id, :library_index_id, 'recent')
                ON CONFLICT (organization_id, user_id, library_index_id, pin_type)
                DO UPDATE SET last_accessed_at = now()
                """,
            ),
            {
                "org_id": str(actor.organization_id),
                "user_id": actor.actor_id,
                "library_index_id": str(document_id),
            },
        )
        await db.commit()
    except Exception:
        await db.rollback()
        logger.warning(
            "library.recent_pin_upsert_failed",
            document_id=str(document_id),
            user_id=actor.actor_id,
            exc_info=True,
        )

    response.headers["Cache-Control"] = "private, max-age=60"
    return LibraryDocumentDetail(
        id=row.id,
        source_table=row.source_table,
        source_id=row.source_id,
        kind=row.kind,
        title=row.title,
        subtitle=row.subtitle,
        status=row.status,
        language=row.language,
        version=row.version,
        is_current=row.is_current,
        entity_kind=row.entity_kind,
        entity_id=row.entity_id,
        entity_slug=row.entity_slug,
        entity_label=row.entity_label,
        folder_path=list(row.folder_path or []),
        author_id=row.author_id,
        approver_id=row.approver_id,
        approved_at=row.approved_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        confidence=float(row.confidence_score) if row.confidence_score is not None else None,
        decision_anchor=row.decision_anchor,
        storage_path=row.storage_path,
        metadata=row.metadata,
    )


# ── POST /library/bundle ────────────────────────────────────────────


class _BundleCreateRequest(BaseModel):
    """Body for the bundle endpoint — kept local to avoid pollution.

    The shape is intentionally tiny: a list of library_index ids and
    nothing else. The job_id and bundle_id are minted server-side so
    the client cannot forge collisions with another user's bundle.
    """

    library_index_ids: list[uuid.UUID]


@router.post(
    "/bundle",
    response_model=LibraryBundleAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Schedule a Library Committee Pack ZIP build",
)
async def create_bundle(
    body: _BundleCreateRequest,
    db: AsyncSession = Depends(get_db_with_rls),  # noqa: ARG001 — RLS scope
    actor: Actor = Depends(get_actor),
) -> LibraryBundleAccepted:
    """Dispatch the ``library_bundle_builder`` worker.

    Returns immediately with the bundle id and the SSE channel id the
    client must subscribe to. Idempotency at the worker level is
    enforced by the per-bundle advisory lock (900_082) so retries with
    the same bundle id are safe.
    """
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Organization required")
    if not body.library_index_ids:
        raise HTTPException(status_code=400, detail="library_index_ids must not be empty")

    bundle_id = uuid.uuid4()
    job_id = f"library-bundle-{bundle_id}"

    # Defer the heavy worker import to avoid a route-level cold start
    from app.core.jobs.tracker import register_job_owner
    from app.domains.wealth.workers.library_bundle_builder import run_library_bundle_builder

    await register_job_owner(job_id, str(actor.organization_id))

    # Schedule the worker as a fire-and-forget background task. The
    # worker manages its own DB session and emits SSE progress events.
    import asyncio

    asyncio.create_task(  # noqa: RUF006 — fire-and-forget background dispatch
        run_library_bundle_builder(
            organization_id=actor.organization_id,
            library_index_ids=list(body.library_index_ids),
            user_id=actor.actor_id,
            bundle_id=bundle_id,
            job_id=job_id,
        ),
    )

    return LibraryBundleAccepted(
        bundle_id=bundle_id,
        job_id=job_id,
        sse_channel=f"job:{job_id}:events",
        item_count=len(body.library_index_ids),
    )


# ── GET /library/bundle/{bundle_id}/download ────────────────────────


@router.get(
    "/bundle/{bundle_id}/download",
    summary="Stream a built Library Committee Pack ZIP",
)
async def download_bundle(
    bundle_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db_with_rls),
    actor: Actor = Depends(get_actor),
) -> StreamingResponse:
    """Stream the bundle ZIP from the canonical StorageClient.

    Audit event is written before the bytes leave the server so a
    failed audit aborts delivery; the audit table has RLS disabled so
    we pass ``organization_id`` explicitly (CLAUDE.md §audit_events).
    """
    if actor.organization_id is None:
        raise HTTPException(status_code=400, detail="Organization required")

    storage_path = gold_library_bundle_path(actor.organization_id, str(bundle_id))
    storage = get_storage_client()
    if not await storage.exists(storage_path):
        raise HTTPException(status_code=404, detail="Bundle not found")

    payload = await storage.read(storage_path)

    await write_audit_event(
        db,
        organization_id=actor.organization_id,
        actor_id=actor.actor_id,
        actor_roles=[r.value if hasattr(r, "value") else str(r) for r in actor.roles],
        request_id=request.headers.get("x-request-id"),
        action="download",
        entity_type="library_bundle",
        entity_id=str(bundle_id),
        after={"size_bytes": len(payload), "storage_path": storage_path},
    )
    await db.commit()

    def _iter_payload() -> Any:
        yield payload

    return StreamingResponse(
        _iter_payload(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="library-bundle-{bundle_id}.zip"',
            "Cache-Control": "no-store",
            "Content-Length": str(len(payload)),
        },
    )


# ── GET /library/redirect-dd-report/{old_fund_id}/{old_report_id} ───


@router.get(
    "/redirect-dd-report/{old_fund_id}/{old_report_id}",
    status_code=status.HTTP_308_PERMANENT_REDIRECT,
    summary="Resolve legacy DD report URLs to new Library paths",
)
async def redirect_dd_report(
    old_fund_id: uuid.UUID,
    old_report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_with_rls),
    user: CurrentUser = Depends(get_current_user),  # noqa: ARG001 — RLS scope
) -> RedirectResponse:
    """Resolve a legacy ``/screener/dd-reports/...`` URL.

    Single SQL hop to grab the instrument slug + report version, then
    a 308 to the canonical Library deep link. Designed for <20ms p95.
    Falls back to a search redirect when the report has been archived.
    """
    result = await db.execute(
        text(
            """
            SELECT iu.slug, dr.version
            FROM dd_reports dr
            JOIN instruments_universe iu ON iu.instrument_id = dr.instrument_id
            WHERE dr.id = :report_id
              AND dr.instrument_id = :fund_id
            """,
        ),
        {"report_id": str(old_report_id), "fund_id": str(old_fund_id)},
    )
    row = result.one_or_none()
    if row is None or not row.slug:
        # Report archived or slug missing — soft fall-through
        return RedirectResponse(
            url="/library",
            status_code=status.HTTP_308_PERMANENT_REDIRECT,
        )

    target = f"/library/due-diligence/by-fund/{row.slug}/v{row.version}"
    return RedirectResponse(url=target, status_code=status.HTTP_308_PERMANENT_REDIRECT)

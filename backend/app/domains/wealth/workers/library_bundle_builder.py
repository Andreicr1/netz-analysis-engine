"""Wealth Library — on-demand Committee Pack ZIP builder.

Phase 1.2 of the Wealth Library sprint
(docs/superpowers/specs/2026-04-08-wealth-library.md §4.4 / §10).

Builds a ZIP archive bundling multiple Library documents (DD reports,
macro reviews, content) on demand for a Committee Pack export. Designed
to be invoked by an HTTP route as a background task once Phase 2 ships.

Architecture
============

1. **Selection** — caller provides a list of ``wealth_library_index.id``
   UUIDs alongside an ``organization_id`` (the export is strictly tenant
   scoped). The worker resolves each into ``(title, storage_path)``.
2. **Download** — pulls every referenced object from the canonical
   ``StorageClient`` (R2 in production, local filesystem in dev).
   Reads run inside the event loop because the client is async.
3. **Pack** — the ZIP build itself is delegated to ``asyncio.to_thread``
   so the event loop never blocks on the CPU/IO of zipping. The
   archive is assembled into an in-memory ``BytesIO``; for the
   expected upper bound of ~50 PDFs (well under 200 MiB) this is
   safer than spilling to a temp file.
4. **Manifest** — emits a ``manifest.json`` describing every entry
   (title, kind, source table, source id, sha256 of bytes, file size).
5. **Upload** — the ZIP and manifest are written via
   ``StorageClient.write`` to paths produced by
   ``gold_library_bundle_path`` and ``gold_library_bundle_manifest_path``
   from ``ai_engine.pipeline.storage_routing``. Manual path
   construction is forbidden (CLAUDE.md §Critical Rules).
6. **SSE progress** — the worker emits ``generating``, ``uploading``
   and ``completed`` events on the supplied job channel via
   ``publish_event``/``publish_terminal_event`` so the client UI can
   stream progress.

Locking: PostgreSQL advisory lock 900_082 is acquired *per bundle* —
the lock key incorporates the bundle UUID via ``hashtext`` so concurrent
builds of *different* bundles are allowed but two simultaneous builds
of the same bundle are serialised. Idempotent on retries.

Usage
-----

The worker is invoked by ``run_library_bundle_builder`` from a route or
HTTP trigger. It is *not* a cron worker — there is no top-level
``__main__`` entry point because invocation requires user input.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import text

from ai_engine.pipeline.storage_routing import (
    gold_library_bundle_manifest_path,
    gold_library_bundle_path,
)
from app.core.db.engine import async_session_factory as async_session
from app.core.jobs.tracker import publish_event, publish_terminal_event
from app.services.storage_client import StorageClient, get_storage_client

logger = structlog.get_logger()

LIBRARY_BUNDLE_BUILDER_LOCK_ID = 900_082


async def _publish(job_id: str | None, event_type: str, **data: Any) -> None:
    """Publish an SSE event if a job channel was provided.

    SSE delivery is best-effort — bundle building must succeed even if
    the Redis pub/sub layer is degraded, so any exception during
    publish is logged and swallowed.
    """
    if not job_id:
        return
    try:
        await publish_event(job_id, event_type, data)
    except Exception:
        logger.warning(
            "library_bundle_builder.sse_publish_failed",
            job_id=job_id,
            event_type=event_type,
            exc_info=True,
        )


async def _publish_terminal(
    job_id: str | None,
    event_type: str,
    **data: Any,
) -> None:
    if not job_id:
        return
    try:
        await publish_terminal_event(job_id, event_type, data)
    except Exception:
        logger.warning(
            "library_bundle_builder.sse_terminal_publish_failed",
            job_id=job_id,
            event_type=event_type,
            exc_info=True,
        )


async def _resolve_entries(
    organization_id: UUID,
    library_index_ids: list[UUID],
) -> list[dict[str, Any]]:
    """Resolve library_index ids into download manifests.

    Sets the RLS GUC for the duration of the SELECT so the standard
    org_isolation policy on ``wealth_library_index`` enforces tenancy
    even at the worker layer.
    """
    async with async_session() as db:
        await db.execute(
            text("SELECT set_config('app.current_organization_id', :oid, true)"),
            {"oid": str(organization_id)},
        )
        result = await db.execute(
            text(
                """
                SELECT id, source_table, source_id, kind, title, storage_path
                FROM wealth_library_index
                WHERE id = ANY(:ids)
                  AND organization_id = :oid
                """,
            ),
            {"ids": [str(i) for i in library_index_ids], "oid": str(organization_id)},
        )
        rows = result.fetchall()

    return [
        {
            "id": str(row.id),
            "source_table": row.source_table,
            "source_id": str(row.source_id),
            "kind": row.kind,
            "title": row.title,
            "storage_path": row.storage_path,
        }
        for row in rows
    ]


def _build_zip_in_memory(
    fetched: list[tuple[dict[str, Any], bytes]],
    manifest: dict[str, Any],
) -> bytes:
    """Synchronously assemble a ZIP archive in memory.

    Designed to be wrapped in ``asyncio.to_thread`` from the worker so
    the event loop never blocks on zipping CPU/IO. Returns the raw
    bytes of the archive (manifest is included as ``manifest.json``
    inside the ZIP and also uploaded separately for cheap discovery).
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for entry, payload in fetched:
            arc_name = _safe_arc_name(entry)
            zf.writestr(arc_name, payload)
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, sort_keys=True))
    return buffer.getvalue()


def _safe_arc_name(entry: dict[str, Any]) -> str:
    """Return a deterministic, filesystem-safe archive entry name.

    Uses the entry id as a prefix so collisions on duplicate titles
    cannot overwrite each other inside the ZIP. The original storage
    extension (if any) is preserved so PDF readers open the file
    natively after extraction.
    """
    title = entry.get("title") or entry.get("kind") or "document"
    safe_title = "".join(
        c if c.isalnum() or c in ("-", "_", " ") else "_" for c in title
    ).strip().replace(" ", "_")[:80] or "document"

    storage_path = entry.get("storage_path") or ""
    suffix = ""
    if "." in storage_path.rsplit("/", 1)[-1]:
        suffix = "." + storage_path.rsplit(".", 1)[-1].lower()
        # Cap pathological extensions
        if len(suffix) > 6:
            suffix = ""
    return f"{entry['id'][:8]}_{safe_title}{suffix}"


async def _download_entries(
    storage: StorageClient,
    entries: list[dict[str, Any]],
) -> tuple[list[tuple[dict[str, Any], bytes]], list[dict[str, Any]]]:
    """Download every entry's payload from storage.

    Returns a tuple of ``(fetched, missing)`` where ``missing`` lists
    entries whose ``storage_path`` was empty or whose object could not
    be retrieved. Missing entries are recorded in the manifest but do
    not abort the bundle.
    """
    fetched: list[tuple[dict[str, Any], bytes]] = []
    missing: list[dict[str, Any]] = []
    for entry in entries:
        storage_path = entry.get("storage_path")
        if not storage_path:
            missing.append({**entry, "reason": "no_storage_path"})
            continue
        try:
            payload = await storage.read(storage_path)
        except FileNotFoundError:
            missing.append({**entry, "reason": "not_found"})
            continue
        except Exception as exc:
            missing.append({**entry, "reason": f"read_failed:{type(exc).__name__}"})
            logger.warning(
                "library_bundle_builder.read_failed",
                storage_path=storage_path,
                error=str(exc),
            )
            continue
        fetched.append((entry, payload))
    return fetched, missing


async def run_library_bundle_builder(
    *,
    organization_id: UUID,
    library_index_ids: list[UUID],
    user_id: str,
    bundle_id: UUID | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Build a Committee Pack ZIP bundle and upload it via StorageClient.

    Args:
        organization_id: tenant scope — enforced by RLS during the
            wealth_library_index lookup.
        library_index_ids: the rows to bundle. Must already exist in
            wealth_library_index for ``organization_id``.
        user_id: Clerk subject of the requester (used for the manifest
            and audit fields).
        bundle_id: optional pre-allocated bundle UUID. When None a new
            v4 UUID is generated. Useful when the caller wants the path
            up-front for the response payload.
        job_id: SSE channel id for progress streaming. When None the
            worker runs silently.

    Returns:
        Summary dict with the bundle id, storage paths, and counts of
        included / missing entries.
    """
    bundle_uuid = bundle_id or uuid4()
    log = logger.bind(
        worker="library_bundle_builder",
        bundle_id=str(bundle_uuid),
        organization_id=str(organization_id),
        user_id=user_id,
        job_id=job_id,
        item_count=len(library_index_ids),
    )
    log.info("library_bundle_builder.started")
    await _publish(job_id, "generating", bundle_id=str(bundle_uuid), step="resolve")

    if not library_index_ids:
        log.warning("library_bundle_builder.empty_payload")
        await _publish_terminal(
            job_id,
            "error",
            bundle_id=str(bundle_uuid),
            error="empty_payload",
        )
        return {"status": "failed", "reason": "empty_payload"}

    # Per-bundle advisory lock keyed off the bundle UUID via hashtext.
    # The (LOCK_ID, hashtext) two-int form serialises only this bundle.
    async with async_session() as lock_db:
        lock_result = await lock_db.execute(
            text(
                "SELECT pg_try_advisory_lock(:lock_id, hashtext(:bundle_key))",
            ),
            {"lock_id": LIBRARY_BUNDLE_BUILDER_LOCK_ID, "bundle_key": str(bundle_uuid)},
        )
        acquired = bool(lock_result.scalar())
        if not acquired:
            log.info("library_bundle_builder.skipped", reason="advisory_lock_held")
            await _publish_terminal(
                job_id,
                "error",
                bundle_id=str(bundle_uuid),
                error="bundle_already_running",
            )
            return {"status": "skipped", "reason": "advisory_lock_held"}

        try:
            entries = await _resolve_entries(organization_id, library_index_ids)
            if not entries:
                log.warning("library_bundle_builder.no_entries_resolved")
                await _publish_terminal(
                    job_id,
                    "error",
                    bundle_id=str(bundle_uuid),
                    error="no_entries_resolved",
                )
                return {"status": "failed", "reason": "no_entries_resolved"}

            await _publish(
                job_id,
                "generating",
                bundle_id=str(bundle_uuid),
                step="download",
                resolved=len(entries),
            )

            storage = get_storage_client()
            fetched, missing = await _download_entries(storage, entries)

            await _publish(
                job_id,
                "generating",
                bundle_id=str(bundle_uuid),
                step="zip",
                fetched=len(fetched),
                missing=len(missing),
            )

            manifest = {
                "bundle_id": str(bundle_uuid),
                "organization_id": str(organization_id),
                "created_by": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "entry_count": len(fetched),
                "missing_count": len(missing),
                "entries": [
                    {
                        "id": entry["id"],
                        "source_table": entry["source_table"],
                        "source_id": entry["source_id"],
                        "kind": entry["kind"],
                        "title": entry["title"],
                        "arc_name": _safe_arc_name(entry),
                        "size_bytes": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                    for entry, payload in fetched
                ],
                "missing": missing,
            }

            zip_bytes = await asyncio.to_thread(
                _build_zip_in_memory, fetched, manifest,
            )

            await _publish(
                job_id,
                "uploading",
                bundle_id=str(bundle_uuid),
                size_bytes=len(zip_bytes),
            )

            zip_path = gold_library_bundle_path(organization_id, str(bundle_uuid))
            manifest_path = gold_library_bundle_manifest_path(
                organization_id, str(bundle_uuid),
            )

            await storage.write(zip_path, zip_bytes, content_type="application/zip")
            await storage.write(
                manifest_path,
                json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
                content_type="application/json",
            )

            log.info(
                "library_bundle_builder.completed",
                zip_path=zip_path,
                manifest_path=manifest_path,
                size_bytes=len(zip_bytes),
                fetched=len(fetched),
                missing=len(missing),
            )
            await _publish_terminal(
                job_id,
                "completed",
                bundle_id=str(bundle_uuid),
                zip_path=zip_path,
                manifest_path=manifest_path,
                size_bytes=len(zip_bytes),
                fetched=len(fetched),
                missing=len(missing),
            )

            return {
                "status": "completed",
                "bundle_id": str(bundle_uuid),
                "zip_path": zip_path,
                "manifest_path": manifest_path,
                "size_bytes": len(zip_bytes),
                "fetched": len(fetched),
                "missing": len(missing),
            }
        except Exception as exc:
            log.exception("library_bundle_builder.failed")
            await _publish_terminal(
                job_id,
                "error",
                bundle_id=str(bundle_uuid),
                error=type(exc).__name__,
            )
            raise
        finally:
            await lock_db.execute(
                text(
                    "SELECT pg_advisory_unlock(:lock_id, hashtext(:bundle_key))",
                ),
                {
                    "lock_id": LIBRARY_BUNDLE_BUILDER_LOCK_ID,
                    "bundle_key": str(bundle_uuid),
                },
            )

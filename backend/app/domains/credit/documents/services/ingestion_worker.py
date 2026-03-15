from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db.audit import write_audit_event
from app.core.jobs.tracker import publish_event
from app.domains.credit.documents.enums import DocumentIngestionStatus
from app.domains.credit.modules.documents.models import Document, DocumentChunk, DocumentVersion
from app.services.blob_storage import download_bytes
from app.services.chunking import chunk_pdf_pages
from app.services.document_text_extractor import extract_pdf_pages
from app.services.search_index import AzureSearchChunksClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WorkerResult:
    processed: int
    indexed: int
    failed: int
    skipped: int


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _emit(version_id: uuid.UUID, event_type: str, data: dict | None = None) -> None:
    """Publish SSE event for a document version (job_id = version_id)."""
    try:
        await publish_event(str(version_id), event_type, data)
    except Exception:
        # Redis unavailable should not break ingestion
        logger.warning("Failed to publish SSE event %s for %s", event_type, version_id, exc_info=True)


async def process_pending_versions(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID,
    limit: int = 10,
    actor_id: str = "ingestion-worker",
) -> WorkerResult:
    result = await db.execute(
        select(DocumentVersion)
        .where(DocumentVersion.fund_id == fund_id, DocumentVersion.ingestion_status == DocumentIngestionStatus.PENDING)
        .order_by(DocumentVersion.created_at.asc())
        .limit(limit),
    )
    vers = result.scalars().all()
    processed = indexed = failed = skipped = 0
    for v in vers:
        processed += 1
        try:
            await _process_one(db, fund_id=fund_id, version=v, actor_id=actor_id)
            indexed += 1
        except Exception:
            failed += 1
    return WorkerResult(processed=processed, indexed=indexed, failed=failed, skipped=skipped)


async def process_version(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID,
    version_id: uuid.UUID,
    actor_id: str = "ingestion-worker",
) -> None:
    result = await db.execute(select(DocumentVersion).where(DocumentVersion.fund_id == fund_id, DocumentVersion.id == version_id))
    v = result.scalar_one()
    await _process_one(db, fund_id=fund_id, version=v, actor_id=actor_id)


async def _process_one(db: AsyncSession, *, fund_id: uuid.UUID, version: DocumentVersion, actor_id: str) -> None:
    if version.ingestion_status == DocumentIngestionStatus.INDEXED:
        return

    job_id = version.id  # SSE channel key

    # Mark PROCESSING early
    version.ingestion_status = DocumentIngestionStatus.PROCESSING
    version.updated_by = actor_id
    await db.commit()
    await _emit(job_id, "processing", {"stage": "started"})

    try:
        result = await db.execute(select(Document).where(Document.fund_id == fund_id, Document.id == version.document_id))
        doc = result.scalar_one()

        if not version.blob_uri:
            raise ValueError("document_version.blob_uri is missing")

        data = download_bytes(blob_uri=version.blob_uri)

        # ── Text extraction ───────────────────────────────────────
        extracted = extract_pdf_pages(data)
        extracted_text = extracted.text
        page_count = len(extracted.pages)

        await _emit(job_id, "ocr_complete", {"pages": page_count, "text_chars": len(extracted_text or "")})

        await write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor_id,
            action="DOCUMENT_TEXT_EXTRACTED",
            entity_type="document_version",
            entity_id=version.id,
            before=None,
            after={
                "document_id": str(doc.id),
                "version_id": str(version.id),
                "page_count": page_count,
                "text_chars": len(extracted_text or ""),
            },
        )

        # Scanned / no-text placeholder (OCR future EPIC)
        if not (extracted_text or "").strip():
            version.ingestion_status = DocumentIngestionStatus.FAILED
            version.ingest_error = {"reason": "scanned_pdf_or_no_text", "detail": "OCR not implemented yet"}
            version.updated_by = actor_id
            await write_audit_event(
                db,
                fund_id=fund_id,
                actor_id=actor_id,
                action="INGESTION_FAILED",
                entity_type="document_version",
                entity_id=version.id,
                before=None,
                after={"reason": "scanned_pdf_or_no_text"},
            )
            await db.commit()
            await _emit(job_id, "error", {"reason": "scanned_pdf_or_no_text"})
            return

        # ── Chunking ─────────────────────────────────────────────
        existing_result = await db.execute(select(func.count(DocumentChunk.id)).where(DocumentChunk.fund_id == fund_id, DocumentChunk.version_id == version.id))
        existing = existing_result.scalar_one()

        if existing == 0:
            drafts = chunk_pdf_pages(pages=extracted.pages)
            for d in drafts:
                db.add(
                    DocumentChunk(
                        fund_id=fund_id,
                        access_level="internal",
                        document_id=doc.id,
                        version_id=version.id,
                        chunk_index=d.chunk_index,
                        text=d.text,
                        embedding_vector=None,
                        version_checksum=version.checksum,
                        page_start=d.page_start,
                        page_end=d.page_end,
                        created_by=actor_id,
                        updated_by=actor_id,
                    ),
                )
            await db.flush()

            await _emit(job_id, "chunking_complete", {"chunks": len(drafts)})

            await write_audit_event(
                db,
                fund_id=fund_id,
                actor_id=actor_id,
                action="DOCUMENT_CHUNKED",
                entity_type="document_version",
                entity_id=version.id,
                before=None,
                after={"chunks_created": len(drafts), "document_id": str(doc.id), "version_id": str(version.id)},
            )
            await db.commit()

        # ── Indexing ──────────────────────────────────────────────
        chunks_result = await db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.fund_id == fund_id, DocumentChunk.version_id == version.id)
            .order_by(DocumentChunk.chunk_index.asc()),
        )
        chunks = chunks_result.scalars().all()

        client = AzureSearchChunksClient()
        items = []
        for c in chunks:
            items.append(
                {
                    "chunk_id": str(c.id),
                    "fund_id": str(fund_id),
                    "document_id": str(doc.id),
                    "version_id": str(version.id),
                    "root_folder": doc.root_folder,
                    "folder_path": doc.folder_path,
                    "title": doc.title,
                    "chunk_index": int(c.chunk_index),
                    "content_text": c.text,
                    "uploaded_at": (version.uploaded_at or version.created_at).astimezone(UTC).isoformat(),
                },
            )
        client.upsert_chunks(items=items)

        await _emit(job_id, "indexing_complete", {"chunks_indexed": len(items)})

        await write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor_id,
            action="DOCUMENT_CHUNKS_INDEXED",
            entity_type="document_version",
            entity_id=version.id,
            before=None,
            after={"chunks_indexed": len(items), "index": settings.SEARCH_CHUNKS_INDEX_NAME},
        )

        # ── Done ──────────────────────────────────────────────────
        version.ingestion_status = DocumentIngestionStatus.INDEXED
        version.indexed_at = _utcnow()
        version.updated_by = actor_id
        await db.commit()

        await _emit(job_id, "ingestion_complete", {
            "version_id": str(version.id),
            "document_id": str(doc.id),
            "chunks_indexed": len(items),
        })

    except Exception as e:
        version.ingestion_status = DocumentIngestionStatus.FAILED
        version.ingest_error = {"reason": "exception", "detail": str(e)}
        version.updated_by = actor_id
        await write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor_id,
            action="INGESTION_FAILED",
            entity_type="document_version",
            entity_id=version.id,
            before=None,
            after={"reason": "exception", "detail": str(e)},
        )
        await db.commit()
        await _emit(job_id, "error", {"reason": "exception", "detail": str(e)})
        raise

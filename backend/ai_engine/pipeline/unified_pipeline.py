"""Unified document processing pipeline.

Single pipeline for all ingestion sources (UI, batch, API).
Source-agnostic: the difference between UI and batch is priority and
feedback (SSE events), not analytical quality.

Stages: pre-filter → OCR → [gate] → classify → [gate] → governance
        → chunk → [gate] → extract metadata → [gate] → embed → [gate]
        → storage (ADLS) → index (Azure Search) → done

Each gate returns ``PipelineStageResult``. On failure the pipeline halts
for this document (other documents in a batch continue).

Storage follows dual-write pattern (Phase 3):
  1. Write to ADLS (StorageClient) — source of truth
  2. Upsert to Azure AI Search — derived index
  3. If ADLS succeeds but Search fails → document is safe, warning logged
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from ai_engine.pipeline.models import (
    HybridClassificationResult,
    IngestRequest,
    PipelineStageResult,
)
from ai_engine.pipeline.validation import (
    validate_chunks,
    validate_classification,
    validate_embeddings,
    validate_ocr_output,
)

logger = logging.getLogger(__name__)

# ── SSE helpers ─────────────────────────────────────────────────────


async def _emit(version_id: UUID | None, event_type: str, data: dict | None = None) -> None:
    """Publish SSE event for UI-sourced requests. Swallowed on failure."""
    if version_id is None:
        return
    try:
        from app.core.jobs.tracker import publish_event
        await publish_event(str(version_id), event_type, data)
    except Exception:
        logger.warning("SSE publish failed: %s for %s", event_type, version_id, exc_info=True)


# ── Audit trail helper ──────────────────────────────────────────────


async def _audit(
    db: AsyncSession | None,
    *,
    fund_id: UUID | None,
    actor_id: str,
    action: str,
    entity_id: UUID,
    after: dict[str, Any] | None,
) -> None:
    """Write audit event if db session is provided. Swallowed on failure."""
    if db is None or fund_id is None:
        return
    try:
        from app.core.db.audit import write_audit_event
        await write_audit_event(
            db,
            fund_id=fund_id,
            actor_id=actor_id,
            action=action,
            entity_type="document_version",
            entity_id=entity_id,
            before=None,
            after=after,
        )
    except Exception:
        logger.warning("Audit write failed: %s for %s", action, entity_id, exc_info=True)


# ── Gate helper ─────────────────────────────────────────────────────


async def _check_gate(
    gate: PipelineStageResult,
    stage: str,
    *,
    request: IngestRequest,
    db: AsyncSession | None,
    actor_id: str,
    metrics: dict[str, Any],
    warnings: list[str],
) -> PipelineStageResult | None:
    """Check a validation gate. Returns a failure result if gate failed, else None."""
    warnings.extend(gate.warnings)
    if gate.success:
        return None
    await _emit(request.version_id, "error", {"stage": stage, "errors": gate.errors})
    await _audit(db, fund_id=request.fund_id, actor_id=actor_id,
                 action="INGESTION_FAILED", entity_id=request.document_id,
                 after={"stage": stage, "errors": gate.errors})
    return PipelineStageResult(
        stage=stage, success=False, data=None, metrics=metrics, errors=gate.errors,
    )


# ── Storage helper (dual-write) ─────────────────────────────────────


async def _write_to_lake(path: str, data: bytes, *, content_type: str = "application/json") -> bool:
    """Write data to ADLS via StorageClient. Returns True on success.

    Feature-flagged: only writes when ``FEATURE_ADLS_ENABLED`` is true
    OR when using ``LocalStorageClient`` (always available in dev).
    Swallowed on failure — logs warning but does not halt the pipeline.
    """
    try:
        from app.services.storage_client import get_storage_client
        storage = get_storage_client()
        await storage.write(path, data, content_type=content_type)
        return True
    except Exception:
        logger.warning("Storage write failed: %s", path, exc_info=True)
        return False


def _build_chunks_parquet(chunks: list[dict[str, Any]], doc_id: str) -> bytes:
    """Serialize chunks + embeddings to Parquet bytes.

    Schema includes ``embedding_model`` and ``embedding_dim`` so the
    rebuild service can reject files from incompatible model versions.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    from ai_engine.validation.vector_integrity_guard import (
        EMBEDDING_DIMENSIONS,
        EMBEDDING_MODEL_NAME,
    )

    rows: list[dict[str, Any]] = []
    for chunk in chunks:
        rows.append({
            "doc_id": doc_id,
            "chunk_index": chunk.get("chunk_index", 0),
            "content": chunk.get("content", ""),
            "page_start": chunk.get("page_start", 0),
            "page_end": chunk.get("page_end", 0),
            "section_type": chunk.get("section_type", ""),
            "breadcrumb": chunk.get("breadcrumb", ""),
            "has_table": bool(chunk.get("has_table", False)),
            "has_numbers": bool(chunk.get("has_numbers", False)),
            "char_count": chunk.get("char_count", 0),
            "doc_type": chunk.get("doc_type", ""),
            "vehicle_type": chunk.get("vehicle_type", ""),
            "governance_critical": bool(chunk.get("governance_critical", False)),
            "governance_flags": json.dumps(chunk.get("governance_flags", [])),
            "embedding": chunk.get("embedding", []),
            "embedding_model": EMBEDDING_MODEL_NAME,
            "embedding_dim": EMBEDDING_DIMENSIONS,
        })

    table = pa.table({
        "doc_id": pa.array([r["doc_id"] for r in rows], type=pa.string()),
        "chunk_index": pa.array([r["chunk_index"] for r in rows], type=pa.int32()),
        "content": pa.array([r["content"] for r in rows], type=pa.string()),
        "page_start": pa.array([r["page_start"] for r in rows], type=pa.int32()),
        "page_end": pa.array([r["page_end"] for r in rows], type=pa.int32()),
        "section_type": pa.array([r["section_type"] for r in rows], type=pa.string()),
        "breadcrumb": pa.array([r["breadcrumb"] for r in rows], type=pa.string()),
        "has_table": pa.array([r["has_table"] for r in rows], type=pa.bool_()),
        "has_numbers": pa.array([r["has_numbers"] for r in rows], type=pa.bool_()),
        "char_count": pa.array([r["char_count"] for r in rows], type=pa.int32()),
        "doc_type": pa.array([r["doc_type"] for r in rows], type=pa.string()),
        "vehicle_type": pa.array([r["vehicle_type"] for r in rows], type=pa.string()),
        "governance_critical": pa.array([r["governance_critical"] for r in rows], type=pa.bool_()),
        "governance_flags": pa.array([r["governance_flags"] for r in rows], type=pa.string()),
        "embedding": pa.array(
            [r["embedding"] for r in rows],
            type=pa.list_(pa.float32()),
        ),
        "embedding_model": pa.array([r["embedding_model"] for r in rows], type=pa.string()),
        "embedding_dim": pa.array([r["embedding_dim"] for r in rows], type=pa.int32()),
    })

    buf = pa.BufferOutputStream()
    pq.write_table(table, buf, compression="zstd")
    return buf.getvalue().to_pybytes()


# ── Main pipeline ───────────────────────────────────────────────────


async def process(
    request: IngestRequest,
    *,
    db: AsyncSession | None = None,
    actor_id: str = "unified-pipeline",
) -> PipelineStageResult:
    """Process a single document through the full pipeline.

    Args:
        request: Frozen ingest request with document metadata.
        db: Optional ``AsyncSession`` for audit trail and status updates.
            When provided, ``write_audit_event()`` is called after each gate
            and ``DocumentVersion.ingestion_status`` is updated.
        actor_id: Actor identifier for audit events.

    Returns the final ``PipelineStageResult`` with aggregated metrics
    from all stages.  On gate failure the pipeline halts and returns
    the failing stage result.
    """
    t0 = time.monotonic()
    metrics: dict[str, Any] = {"source": request.source}
    warnings: list[str] = []

    # Register job→org ownership in Redis so the SSE endpoint can enforce
    # tenant isolation (todo #030).
    if request.version_id:
        try:
            from app.core.jobs.tracker import register_job_owner
            await register_job_owner(str(request.version_id), str(request.org_id))
        except Exception:
            logger.warning("Failed to register job owner for %s", request.version_id, exc_info=True)

    await _emit(request.version_id, "processing", {"stage": "started"})

    # ── 1. Pre-filter ───────────────────────────────────────────
    from ai_engine.extraction.skip_filter import should_skip_document

    if should_skip_document(request.filename):
        logger.info("[pipeline] SKIP %s — standard compliance form", request.filename)
        return PipelineStageResult(
            stage="pre_filter",
            success=True,
            data=None,
            metrics={"skipped": True, "reason": "standard_compliance_form"},
            warnings=["Skipped — standard compliance form"],
        )

    # ── 2. OCR ──────────────────────────────────────────────────
    from ai_engine.extraction.mistral_ocr import async_extract_pdf_with_mistral
    from app.services.blob_storage import download_bytes

    pdf_bytes = await asyncio.to_thread(download_bytes, blob_uri=request.blob_uri)
    page_blocks = await async_extract_pdf_with_mistral(pdf_bytes)
    del pdf_bytes  # release potentially large PDF from memory
    ocr_text = "\n\n".join(pb.text for pb in page_blocks)
    page_count = len(page_blocks)
    del page_blocks  # release OCR page blocks from memory

    metrics["ocr_chars"] = len(ocr_text)
    metrics["page_count"] = page_count

    await _emit(request.version_id, "ocr_complete", {
        "pages": page_count, "text_chars": len(ocr_text),
    })
    await _audit(db, fund_id=request.fund_id, actor_id=actor_id,
                 action="DOCUMENT_OCR_COMPLETE", entity_id=request.document_id,
                 after={"page_count": page_count, "text_chars": len(ocr_text)})

    # ── Gate: OCR validation ────────────────────────────────────
    ocr_gate = validate_ocr_output(ocr_text, request.filename)
    failure = await _check_gate(ocr_gate, "ocr", request=request, db=db, actor_id=actor_id, metrics=metrics, warnings=warnings)
    if failure:
        return failure

    # ── 3. Classification ───────────────────────────────────────
    from ai_engine.classification.hybrid_classifier import classify

    classification: HybridClassificationResult = await classify(
        text=ocr_text,
        filename=request.filename,
    )

    metrics["doc_type"] = classification.doc_type
    metrics["vehicle_type"] = classification.vehicle_type
    metrics["classification_confidence"] = classification.confidence
    metrics["classification_layer"] = classification.layer

    await _emit(request.version_id, "classification_complete", {
        "doc_type": classification.doc_type,
        "vehicle_type": classification.vehicle_type,
        "confidence": classification.confidence,
        "layer": classification.layer,
    })
    await _audit(db, fund_id=request.fund_id, actor_id=actor_id,
                 action="DOCUMENT_CLASSIFIED", entity_id=request.document_id,
                 after={"doc_type": classification.doc_type,
                        "vehicle_type": classification.vehicle_type,
                        "confidence": classification.confidence,
                        "layer": classification.layer})

    # ── Gate: Classification validation ─────────────────────────
    cls_gate = validate_classification(classification)
    failure = await _check_gate(cls_gate, "classification", request=request, db=db, actor_id=actor_id, metrics=metrics, warnings=warnings)
    if failure:
        return failure

    # ── 4. Governance detection ─────────────────────────────────
    from ai_engine.extraction.governance_detector import detect_governance

    gov_result = detect_governance(ocr_text)
    gov_critical = gov_result.governance_critical
    gov_flags = gov_result.governance_flags
    metrics["governance_critical"] = gov_critical
    metrics["governance_flags"] = gov_flags

    # ── 5. Chunking ─────────────────────────────────────────────
    from ai_engine.extraction.semantic_chunker import chunk_document

    doc_id = str(request.document_id)

    # Build metadata dict for chunker (mirrors prepare_pdfs_full.py)
    chunk_metadata: dict[str, Any] = {
        "doc_type": classification.doc_type,
        "vehicle_type": classification.vehicle_type,
        "governance_critical": gov_critical,
        "governance_flags": gov_flags,
        "confidence": classification.confidence,
        "source_file": request.filename,
    }
    # Enrich from fund_context if available
    if request.fund_context:
        fc = request.fund_context
        chunk_metadata["deal_name"] = fc.get("deal_name", "")
        chunk_metadata["fund_name"] = fc.get("fund_name", "")
        if fc.get("fund_strategy"):
            chunk_metadata["fund_strategy"] = fc["fund_strategy"]
        if fc.get("fund_jurisdiction"):
            chunk_metadata["fund_jurisdiction"] = fc["fund_jurisdiction"]
        if fc.get("key_terms"):
            chunk_metadata["key_terms"] = fc["key_terms"]
        if fc.get("investment_manager"):
            chunk_metadata["investment_manager"] = fc["investment_manager"]

    chunks = chunk_document(
        ocr_markdown=ocr_text,
        doc_id=doc_id,
        doc_type=classification.doc_type,
        metadata=chunk_metadata,
    )

    metrics["chunk_count"] = len(chunks)

    await _emit(request.version_id, "chunking_complete", {
        "chunks": len(chunks),
    })
    await _audit(db, fund_id=request.fund_id, actor_id=actor_id,
                 action="DOCUMENT_CHUNKED", entity_id=request.document_id,
                 after={"chunk_count": len(chunks)})

    # ── Gate: Chunk validation ──────────────────────────────────
    chunk_gate = validate_chunks(chunks, len(ocr_text))
    failure = await _check_gate(chunk_gate, "chunking", request=request, db=db, actor_id=actor_id, metrics=metrics, warnings=warnings)
    if failure:
        return failure

    # ── 6. Extract metadata + summarize (parallel) ──────────────
    from ai_engine.extraction.document_intelligence import (
        async_extract_metadata,
        async_summarize_document,
    )

    # Use head of OCR text for extraction/summarization (matches existing behavior)
    title = request.filename
    content_for_extraction = ocr_text

    meta_task = async_extract_metadata(
        title=title,
        doc_type=classification.doc_type,
        content=content_for_extraction,
    )
    summary_task = async_summarize_document(
        title=title,
        doc_type=classification.doc_type,
        content=content_for_extraction,
    )

    metadata_result, summary_result = await asyncio.gather(
        meta_task, summary_task, return_exceptions=True,
    )

    # Handle exceptions from gather
    extraction_metadata: dict[str, Any] = {}
    if isinstance(metadata_result, Exception):
        logger.error("Metadata extraction failed: %s", metadata_result, exc_info=True)
        warnings.append("Metadata extraction failed")
    else:
        extraction_metadata = {
            "dates": metadata_result.dates,
            "amounts": metadata_result.amounts,
            "parties": metadata_result.parties,
            "counterparties": metadata_result.counterparties,
            "jurisdictions": metadata_result.jurisdictions,
        }

    summary_text = ""
    if isinstance(summary_result, Exception):
        logger.error("Summarization failed: %s", summary_result, exc_info=True)
        warnings.append("Summarization failed")
    else:
        summary_text = summary_result.summary

    metrics["has_metadata"] = bool(extraction_metadata)
    metrics["has_summary"] = bool(summary_text)

    await _emit(request.version_id, "extraction_complete", {
        "has_metadata": bool(extraction_metadata),
        "has_summary": bool(summary_text),
    })

    # ── 7. Embedding ────────────────────────────────────────────
    from ai_engine.extraction.embed_chunks import build_embed_text, embed_batch

    embed_texts = [build_embed_text(c) for c in chunks]

    # embed_batch() is synchronous — run in thread to avoid blocking event loop
    vectors = await asyncio.to_thread(embed_batch, embed_texts)

    # Attach vectors to chunks
    for chunk, vector in zip(chunks, vectors, strict=True):
        chunk["embedding"] = vector

    metrics["embedding_count"] = len(vectors)
    metrics["embedding_dim"] = len(vectors[0]) if vectors else 0

    # ── Gate: Embedding validation ──────────────────────────────
    emb_gate = validate_embeddings(vectors, len(chunks))
    failure = await _check_gate(emb_gate, "embedding", request=request, db=db, actor_id=actor_id, metrics=metrics, warnings=warnings)
    if failure:
        return failure

    # ── 8. Write to ADLS (source of truth) ────────────────────────
    from ai_engine.pipeline.storage_routing import (
        bronze_document_path,
        silver_chunks_path,
        silver_metadata_path,
    )

    doc_id_str = str(request.document_id)

    # 8a. Build all paths
    bronze_path = bronze_document_path(request.org_id, request.vertical, doc_id_str)
    silver_path = silver_chunks_path(request.org_id, request.vertical, doc_id_str)
    meta_path = silver_metadata_path(request.org_id, request.vertical, doc_id_str)

    # 8b. Build all payloads (before gather)
    bronze_payload = json.dumps({
        "document_id": doc_id_str,
        "filename": request.filename,
        "ocr_text": ocr_text,
        "page_count": page_count,
    }).encode()
    parquet_bytes = await asyncio.to_thread(_build_chunks_parquet, chunks, doc_id_str)
    meta_payload = json.dumps({
        "document_id": doc_id_str,
        "filename": request.filename,
        "doc_type": classification.doc_type,
        "vehicle_type": classification.vehicle_type,
        "classification_confidence": classification.confidence,
        "classification_layer": classification.layer,
        "governance_critical": gov_critical,
        "governance_flags": gov_flags,
        "metadata": extraction_metadata,
        "summary": summary_text,
    }).encode()

    # 8c. Write all three in parallel
    bronze_ok, silver_ok, meta_ok = await asyncio.gather(
        _write_to_lake(bronze_path, bronze_payload),
        _write_to_lake(silver_path, parquet_bytes, content_type="application/octet-stream"),
        _write_to_lake(meta_path, meta_payload),
    )

    metrics["storage_bronze"] = bronze_ok
    metrics["storage_silver_chunks"] = silver_ok
    metrics["storage_silver_metadata"] = meta_ok

    if not bronze_ok:
        warnings.append("ADLS bronze write failed — raw OCR not persisted to lake")
    if not silver_ok:
        warnings.append("ADLS silver chunks write failed — rebuild capability degraded")
    if not meta_ok:
        warnings.append("ADLS silver metadata write failed")

    await _emit(request.version_id, "storage_complete", {
        "bronze": bronze_ok,
        "silver_chunks": silver_ok,
        "silver_metadata": meta_ok,
    })

    # ── 9. Index to Azure Search (derived index) ────────────────
    from ai_engine.extraction.search_upsert_service import (
        build_search_document,
    )
    from ai_engine.extraction.search_upsert_service import (
        upsert_chunks as upsert_search_chunks,
    )

    search_docs = []
    for chunk in chunks:
        search_doc = build_search_document(
            deal_id=request.deal_id or request.document_id,
            # fund_id: use document_id as fallback (not org_id — semantically different).
            # Batch path may not have fund_id; document_id ensures unique scoping.
            fund_id=request.fund_id or request.document_id,
            domain=request.vertical,
            doc_type=classification.doc_type,
            authority="unified_pipeline",
            title=request.filename,
            chunk_index=chunk.get("chunk_index", 0),
            content=chunk.get("content", ""),
            embedding=chunk.get("embedding", []),
            page_start=chunk.get("page_start", 0),
            page_end=chunk.get("page_end", 0),
            document_id=request.document_id,
            doc_summary=summary_text or None,
            vehicle_type=classification.vehicle_type,
            section_type=chunk.get("section_type"),
            breadcrumb=chunk.get("breadcrumb"),
            has_table=chunk.get("has_table"),
            has_numbers=chunk.get("has_numbers"),
            char_count=chunk.get("char_count"),
            governance_critical=gov_critical,
            governance_flags=gov_flags if gov_flags else None,
            organization_id=request.org_id,
        )
        search_docs.append(search_doc)

    # upsert_chunks is synchronous
    indexed_count = await asyncio.to_thread(upsert_search_chunks, search_docs)

    metrics["chunks_indexed"] = indexed_count

    await _emit(request.version_id, "indexing_complete", {
        "chunks_indexed": indexed_count,
    })
    await _audit(db, fund_id=request.fund_id, actor_id=actor_id,
                 action="DOCUMENT_CHUNKS_INDEXED", entity_id=request.document_id,
                 after={"chunks_indexed": indexed_count})

    # ── 10. Done ────────────────────────────────────────────────
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    metrics["duration_ms"] = elapsed_ms

    await _emit(request.version_id, "ingestion_complete", {
        "document_id": str(request.document_id),
        "chunks_indexed": indexed_count,
        "duration_ms": elapsed_ms,
    })

    logger.info(
        "[pipeline] OK %s → %s (%s) | %d chunks | %dms",
        request.filename,
        classification.doc_type,
        f"L{classification.layer}",
        len(chunks),
        elapsed_ms,
    )

    # Assemble final result
    pipeline_data = {
        "doc_type": classification.doc_type,
        "vehicle_type": classification.vehicle_type,
        "classification_confidence": classification.confidence,
        "classification_layer": classification.layer,
        "governance_critical": gov_critical,
        "governance_flags": gov_flags,
        "chunk_count": len(chunks),
        "chunks_indexed": indexed_count,
        "metadata": extraction_metadata,
        "summary": summary_text,
    }

    return PipelineStageResult(
        stage="complete",
        success=True,
        data=pipeline_data,
        metrics=metrics,
        warnings=warnings,
    )

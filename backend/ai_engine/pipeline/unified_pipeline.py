"""Unified document processing pipeline.

Single pipeline for all ingestion sources (UI, batch, API).
Source-agnostic: the difference between UI and batch is priority and
feedback (SSE events), not analytical quality.

Stages: pre-filter → OCR → [gate] → classify → [gate] → governance
        → chunk → [gate] → extract metadata → [gate] → embed → [gate]
        → index → done

Each gate returns ``PipelineStageResult``. On failure the pipeline halts
for this document (other documents in a batch continue).
"""
from __future__ import annotations

import asyncio
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
        logger.error("Metadata extraction failed: %s", metadata_result)
        warnings.append(f"Metadata extraction failed: {metadata_result}")
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
        logger.error("Summarization failed: %s", summary_result)
        warnings.append(f"Summarization failed: {summary_result}")
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

    # ── 8. Index to Azure Search ────────────────────────────────
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

    # ── 9. Done ─────────────────────────────────────────────────
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

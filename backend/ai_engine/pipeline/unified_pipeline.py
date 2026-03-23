"""Unified document processing pipeline.

Single pipeline for all ingestion sources (UI, batch, API).
Source-agnostic: the difference between UI and batch is priority and
feedback (SSE events), not analytical quality.

Stages: pre-filter → OCR → [gate] → classify → [gate] → governance
        → chunk → [gate] → extract metadata → [gate] → embed → [gate]
        → storage (StorageClient) → index (pgvector) → done

Each gate returns ``PipelineStageResult``. On failure the pipeline halts
for this document (other documents in a batch continue).

Storage follows dual-write pattern (Phase 3):
  1. Write to StorageClient (R2 prod / LocalStorage dev) — source of truth
  2. Upsert to pgvector (PostgreSQL) — derived index
  3. If storage succeeds but pgvector fails → document is safe, warning logged
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import time
import uuid
from pathlib import Path
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

EXTRACTION_SOURCE_CONFIG: dict[str, dict[str, str]] = {
    "deals": {
        "input_container": "investment-pipeline-intelligence",
        "storage_prefix": "bronze/batch/deals",
        "description": "Pipeline deal PDFs through unified_pipeline",
    },
    "fund-data": {
        "input_container": "fund-data",
        "storage_prefix": "bronze/batch/fund-data",
        "description": "Fund data documents through unified_pipeline",
    },
    "market-data": {
        "input_container": "market-data",
        "storage_prefix": "bronze/batch/market-data",
        "description": "Market data documents through unified_pipeline",
    },
}

_EXTRACTION_JOBS: dict[str, dict[str, Any]] = {}
_MAX_EXTRACTION_JOBS = 50


def _extract_text_pymupdf(pdf_bytes: bytes) -> list:
    """Zero-cost text extraction via PyMuPDF (no external API call).

    Works well for text-based PDFs. Scanned images will return empty text.
    Returns list[PageBlock] matching mistral_ocr format.
    """
    import fitz

    from ai_engine.extraction.mistral_ocr import PageBlock

    blocks: list = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            text = page.get_text("text")
            if text.strip():
                blocks.append(PageBlock(
                    page_start=i + 1,
                    page_end=i + 1,
                    text=text.strip(),
                ))
    return blocks


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _trim_extraction_jobs() -> None:
    if len(_EXTRACTION_JOBS) <= _MAX_EXTRACTION_JOBS:
        return
    oldest_job_id = min(
        _EXTRACTION_JOBS,
        key=lambda item_job_id: _EXTRACTION_JOBS[item_job_id].get("created_at", ""),
    )
    del _EXTRACTION_JOBS[oldest_job_id]


def new_extraction_job(source: str, deals_filter: str, *, pipeline_name: str = "unified_pipeline") -> str:
    """Allocate a tracked extraction job ID for canonical batch ingestion."""
    job_id = str(uuid.uuid4())
    _EXTRACTION_JOBS[job_id] = {
        "job_id": job_id,
        "source": source,
        "deals_filter": deals_filter,
        "pipeline_name": pipeline_name,
        "legacy_path_invoked": False,
        "status": "pending",
        "created_at": _utc_now_iso(),
        "started_at": None,
        "finished_at": None,
        "results": [],
        "summary": {},
        "error": None,
    }
    _trim_extraction_jobs()
    return job_id


def _update_extraction_job(job_id: str, **kwargs: Any) -> None:
    if job_id in _EXTRACTION_JOBS:
        _EXTRACTION_JOBS[job_id].update(kwargs)


def get_extraction_job_status(job_id: str) -> dict[str, Any]:
    """Return canonical extraction job status."""
    return _EXTRACTION_JOBS.get(job_id, {"error": "Job not found", "job_id": job_id})


def list_extraction_jobs() -> list[dict[str, Any]]:
    """Return tracked extraction jobs, newest first."""
    return sorted(
        _EXTRACTION_JOBS.values(),
        key=lambda job: job.get("created_at") or "",
        reverse=True,
    )


async def list_extraction_source_items(source: str) -> list[str]:
    """List top-level folders for a canonical extraction source."""
    from app.services.storage_client import get_storage_client

    source_cfg = EXTRACTION_SOURCE_CONFIG[source]
    storage = get_storage_client()
    files = await storage.list_files(source_cfg["storage_prefix"])

    seen: set[str] = set()
    for file_path in files:
        if not file_path.lower().endswith(".pdf"):
            continue
        # Strip the prefix to get the relative path, then extract the top-level folder
        relative = file_path[len(source_cfg["storage_prefix"]):].lstrip("/")
        parts = relative.split("/", 1)
        if len(parts) == 2:
            seen.add(parts[0])
    return sorted(seen)


async def _run_extraction_pipeline_async(
    *,
    source: str,
    deals_filter: str,
    dry_run: bool,
    no_index: bool,
) -> list[dict[str, Any]]:
    from app.services.storage_client import get_storage_client

    storage = get_storage_client()
    filters = [item.strip().lower() for item in deals_filter.split(",") if item.strip()]
    sources_to_run = list(EXTRACTION_SOURCE_CONFIG) if source == "all" else [source]
    results: list[dict[str, Any]] = []

    for source_key in sources_to_run:
        source_cfg = EXTRACTION_SOURCE_CONFIG[source_key]
        all_files = await storage.list_files(source_cfg["storage_prefix"])
        pdf_paths = [p for p in all_files if p.lower().endswith(".pdf")]

        for storage_path in pdf_paths:
            # Use relative path from prefix for display and filtering
            relative = storage_path[len(source_cfg["storage_prefix"]):].lstrip("/")
            if filters and not any(f in relative.lower() for f in filters):
                continue

            filename = Path(relative).name
            item_result: dict[str, Any] = {
                "source": source_key,
                "blob_path": storage_path,
                "filename": filename,
                "pipeline_name": "unified_pipeline",
                "legacy_path_invoked": False,
                "status": "dry_run" if dry_run else "pending",
            }

            if dry_run:
                results.append(item_result)
                continue

            request = IngestRequest(
                source="batch",
                org_id=uuid.UUID(int=0),
                vertical="credit",
                document_id=uuid.uuid5(uuid.NAMESPACE_URL, storage_path),
                blob_uri=storage_path,
                filename=filename,
            )

            pipeline_result = await process(
                request,
                actor_id="unified_pipeline",
                skip_index=no_index,
            )
            item_result["status"] = "ok" if pipeline_result.success else "error"
            item_result["stage"] = pipeline_result.stage
            item_result["chunk_count"] = pipeline_result.metrics.get("chunk_count", 0)
            item_result["duration_ms"] = pipeline_result.metrics.get("duration_ms", 0)
            if pipeline_result.errors:
                item_result["errors"] = list(pipeline_result.errors)
            if pipeline_result.warnings:
                item_result["warnings"] = list(pipeline_result.warnings)
            results.append(item_result)

    return results


def run_extraction_pipeline(
    source: str = "deals",
    deals_filter: str = "",
    dry_run: bool = False,
    skip_bootstrap: bool = False,
    skip_prepare: bool = False,
    skip_embed: bool = False,
    skip_enrich: bool = False,
    no_index: bool = False,
    poll_timeout: int = 600,
    job_id: str | None = None,
) -> str:
    """Run canonical extraction batch ingestion through ``unified_pipeline``.

    Legacy orchestration flags are accepted for API compatibility and ignored.
    """
    del skip_bootstrap, skip_prepare, skip_embed, skip_enrich, poll_timeout

    if source not in EXTRACTION_SOURCE_CONFIG and source != "all":
        raise ValueError(f"Invalid source {source!r}. Expected one of {sorted(EXTRACTION_SOURCE_CONFIG)} or 'all'.")

    if job_id is None:
        job_id = new_extraction_job(source, deals_filter)
    elif job_id not in _EXTRACTION_JOBS:
        _EXTRACTION_JOBS[job_id] = {
            "job_id": job_id,
            "source": source,
            "deals_filter": deals_filter,
            "pipeline_name": "unified_pipeline",
            "legacy_path_invoked": False,
            "status": "pending",
            "created_at": _utc_now_iso(),
            "started_at": None,
            "finished_at": None,
            "results": [],
            "summary": {},
            "error": None,
        }
        _trim_extraction_jobs()

    _update_extraction_job(
        job_id,
        source=source,
        deals_filter=deals_filter,
        status="running",
        started_at=_utc_now_iso(),
        legacy_path_invoked=False,
        pipeline_name="unified_pipeline",
    )

    try:
        results = asyncio.run(
            _run_extraction_pipeline_async(
                source=source,
                deals_filter=deals_filter,
                dry_run=dry_run,
                no_index=no_index,
            )
        )
        ok_count = len([item for item in results if item["status"] == "ok"])
        dry_run_count = len([item for item in results if item["status"] == "dry_run"])
        error_count = len([item for item in results if item["status"] == "error"])
        _update_extraction_job(
            job_id,
            status="completed",
            finished_at=_utc_now_iso(),
            results=results,
            summary={
                "total": len(results),
                "ok": ok_count,
                "dry_run": dry_run_count,
                "errors": error_count,
            },
        )
    except Exception as exc:
        logger.error("Canonical extraction pipeline failed job=%s", job_id, exc_info=True)
        _update_extraction_job(
            job_id,
            status="failed",
            finished_at=_utc_now_iso(),
            error=str(exc),
        )

    return job_id

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


async def _emit_terminal(version_id: UUID | None, event_type: str, data: dict | None = None) -> None:
    """Publish a terminal SSE event and schedule ownership cleanup (ASYNC-01).

    Same as _emit but uses publish_terminal_event so the ownership key
    is set to a short grace TTL after the terminal event is published.
    """
    if version_id is None:
        return
    try:
        from app.core.jobs.tracker import publish_terminal_event
        await publish_terminal_event(str(version_id), event_type, data)
    except Exception:
        logger.warning("SSE terminal publish failed: %s for %s", event_type, version_id, exc_info=True)


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
    await _emit_terminal(request.version_id, "error", {"stage": stage, "errors": gate.errors})
    await _audit(db, fund_id=request.fund_id, actor_id=actor_id,
                 action="INGESTION_FAILED", entity_id=request.document_id,
                 after={"stage": stage, "errors": gate.errors})
    return PipelineStageResult(
        stage=stage, success=False, data=None, metrics=metrics, errors=gate.errors,
    )


# ── Storage helper (dual-write) ─────────────────────────────────────


async def _write_to_lake(path: str, data: bytes, *, content_type: str = "application/json") -> bool:
    """Write data via StorageClient (R2 prod / LocalStorage dev). Returns True on success.

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


def _build_chunks_parquet(chunks: list[dict[str, Any]], doc_id: str, org_id: str) -> bytes:
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
            "organization_id": org_id,
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
        "organization_id": pa.array([r["organization_id"] for r in rows], type=pa.string()),
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
    skip_index: bool = False,
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
    from app.services.storage_client import get_storage_client

    storage = get_storage_client()
    pdf_bytes = await storage.read(request.blob_uri)

    # Check OCR cache first (avoids paid API call on cache hit)
    from ai_engine.cache.provider_cache import ocr_cache

    cached_ocr = ocr_cache.get(pdf_bytes, filename=request.filename)
    if cached_ocr is not None:
        ocr_text = cached_ocr
        page_count = cached_ocr.count("\n\n") + 1  # approximate from cached text
        del pdf_bytes
    else:
        from app.core.config.settings import settings as _s
        ocr_provider = _s.local_ocr_provider if _s.use_local_ocr else "mistral"
        if ocr_provider == "local_vlm":
            from ai_engine.extraction.local_vlm_ocr import async_extract_pdf_with_local_vlm
            page_blocks = await async_extract_pdf_with_local_vlm(pdf_bytes)
        elif ocr_provider == "pymupdf":
            page_blocks = await asyncio.to_thread(_extract_text_pymupdf, pdf_bytes)
        else:
            from ai_engine.extraction.mistral_ocr import async_extract_pdf_with_mistral
            page_blocks = await async_extract_pdf_with_mistral(pdf_bytes)
        ocr_text = "\n\n".join(pb.text for pb in page_blocks)
        page_count = len(page_blocks)
        # Store in cache for future runs
        ocr_cache.put(pdf_bytes, ocr_text, filename=request.filename, page_count=page_count)
        del pdf_bytes  # release potentially large PDF from memory
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
    metrics["classification_model"] = classification.model_name

    await _emit(request.version_id, "classification_complete", {
        "doc_type": classification.doc_type,
        "vehicle_type": classification.vehicle_type,
        "confidence": classification.confidence,
        "layer": classification.layer,
        "model_name": classification.model_name,
    })
    await _audit(db, fund_id=request.fund_id, actor_id=actor_id,
                 action="DOCUMENT_CLASSIFIED", entity_id=request.document_id,
                 after={"doc_type": classification.doc_type,
                        "vehicle_type": classification.vehicle_type,
                        "confidence": classification.confidence,
                        "layer": classification.layer,
                        "model_name": classification.model_name})

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
        ExtractionQuality,
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

    meta_extraction_result, summary_extraction_result = await asyncio.gather(
        meta_task, summary_task, return_exceptions=True,
    )

    # Handle exceptions from gather — unwrap ExtractionResult
    extraction_metadata: dict[str, Any] = {}
    meta_quality = ExtractionQuality.SERVICE_OUTAGE
    summary_quality = ExtractionQuality.SUMMARY_FAILURE

    if isinstance(meta_extraction_result, Exception):
        logger.error("Metadata extraction failed: %s", meta_extraction_result, exc_info=True)
        warnings.append("Metadata extraction failed")
    else:
        meta_quality = meta_extraction_result.quality
        metadata_content = meta_extraction_result.content
        extraction_metadata = {
            "dates": metadata_content.dates,
            "counterparties": metadata_content.counterparties,
            "jurisdictions": metadata_content.jurisdictions,
        }
        if meta_quality.is_degraded:
            warnings.append(f"Metadata extraction degraded: {meta_extraction_result.reason}")

    summary_text = ""
    if isinstance(summary_extraction_result, Exception):
        logger.error("Summarization failed: %s", summary_extraction_result, exc_info=True)
        warnings.append("Summarization failed")
    else:
        summary_quality = summary_extraction_result.quality
        summary_text = summary_extraction_result.content.summary
        if summary_quality.is_degraded:
            warnings.append(f"Summarization degraded: {summary_extraction_result.reason}")

    # Collect extraction quality codes for metadata persistence
    extraction_quality_codes: dict[str, str] = {
        "metadata": meta_quality.value,
        "summary": summary_quality.value,
    }
    # Track whether any extraction stage is degraded
    extraction_degraded = meta_quality.is_degraded or summary_quality.is_degraded

    metrics["has_metadata"] = bool(extraction_metadata)
    metrics["has_summary"] = bool(summary_text)
    metrics["extraction_quality"] = extraction_quality_codes
    metrics["extraction_degraded"] = extraction_degraded

    await _emit(request.version_id, "extraction_complete", {
        "has_metadata": bool(extraction_metadata),
        "has_summary": bool(summary_text),
        "extraction_quality": extraction_quality_codes,
        "extraction_degraded": extraction_degraded,
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

    # ── 8. Write to storage (source of truth) ──────────────────────
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
    parquet_bytes = await asyncio.to_thread(
        _build_chunks_parquet, chunks, doc_id_str, str(request.org_id)
    )
    meta_payload = json.dumps({
        "document_id": doc_id_str,
        "filename": request.filename,
        "doc_type": classification.doc_type,
        "vehicle_type": classification.vehicle_type,
        "classification_confidence": classification.confidence,
        "classification_layer": classification.layer,
        "classification_model": classification.model_name,
        "governance_critical": gov_critical,
        "governance_flags": gov_flags,
        "metadata": extraction_metadata,
        "summary": summary_text,
        "extraction_quality": extraction_quality_codes,
        "extraction_degraded": extraction_degraded,
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
        warnings.append("Storage bronze write failed — raw OCR not persisted to lake")
    if not silver_ok:
        warnings.append("Storage silver chunks write failed — rebuild capability degraded")
    if not meta_ok:
        warnings.append("Storage silver metadata write failed")

    storage_all_failed = not bronze_ok and not silver_ok and not meta_ok
    storage_partial_failed = (not bronze_ok or not silver_ok or not meta_ok) and not storage_all_failed

    if storage_partial_failed:
        failed_writes = [
            name for name, ok in [("bronze", bronze_ok), ("silver_chunks", silver_ok), ("silver_metadata", meta_ok)]
            if not ok
        ]
        logger.warning(
            "[pipeline] Storage partial failure for %s — failed writes: %s; continuing to Search upsert",
            request.filename,
            failed_writes,
        )

    await _emit(request.version_id, "storage_complete", {
        "bronze": bronze_ok,
        "silver_chunks": silver_ok,
        "silver_metadata": meta_ok,
        "all_failed": storage_all_failed,
    })

    # SR-6: If ALL storage writes failed, skip Search upsert — source of truth has no data.
    if storage_all_failed:
        logger.error(
            "[pipeline] ALL storage writes failed for %s — skipping Search upsert (source of truth missing)",
            request.filename,
        )
        skip_index = True
        warnings.append("Search upsert skipped — all storage writes failed (no source of truth)")

    # ── 9. Index to pgvector (derived index) ─────────────────────
    from ai_engine.extraction.pgvector_search_service import (
        UpsertResult,
        build_search_document,
    )
    from ai_engine.extraction.pgvector_search_service import (
        upsert_chunks as pgvector_upsert,
    )

    upsert_result = UpsertResult(
        attempted_chunk_count=0,
        successful_chunk_count=0,
        failed_chunk_count=0,
        retryable=False,
    )
    if not skip_index:
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
                extraction_degraded=extraction_degraded if extraction_degraded else None,
                extraction_quality=extraction_quality_codes if extraction_degraded else None,
            )
            search_docs.append(search_doc)

        # pgvector upsert is async — requires db session
        if db is not None:
            upsert_result = await pgvector_upsert(db, search_docs)
        else:
            logger.warning("[pipeline] No db session — skipping pgvector upsert")
            upsert_result = UpsertResult(
                attempted_chunk_count=len(search_docs),
                successful_chunk_count=0,
                failed_chunk_count=len(search_docs),
                retryable=True,
                batch_errors=["No database session available for pgvector upsert"],
            )

    indexed_count = upsert_result.successful_chunk_count
    metrics["chunks_indexed"] = indexed_count
    metrics["attempted_chunk_count"] = upsert_result.attempted_chunk_count
    metrics["successful_chunk_count"] = upsert_result.successful_chunk_count
    metrics["failed_chunk_count"] = upsert_result.failed_chunk_count
    metrics["index_skipped"] = skip_index

    await _emit(request.version_id, "indexing_complete", {
        "chunks_indexed": indexed_count,
        "attempted_chunk_count": upsert_result.attempted_chunk_count,
        "successful_chunk_count": upsert_result.successful_chunk_count,
        "failed_chunk_count": upsert_result.failed_chunk_count,
        "index_skipped": skip_index,
    })
    await _audit(db, fund_id=request.fund_id, actor_id=actor_id,
                 action="DOCUMENT_CHUNKS_INDEXED", entity_id=request.document_id,
                 after={"chunks_indexed": indexed_count, "index_skipped": skip_index})

    # ── 10. Determine terminal state ───────────────────────────
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    metrics["duration_ms"] = elapsed_ms

    # Compute terminal state: degraded when partial, failed when total failure
    if storage_all_failed:
        terminal_state = "failed"
        pipeline_success = False
    elif upsert_result.is_total_failure and not skip_index:
        terminal_state = "failed"
        pipeline_success = False
        warnings.append(
            f"Search indexing failed completely: 0/{upsert_result.attempted_chunk_count} chunks indexed"
        )
    elif storage_partial_failed:
        terminal_state = "degraded"
        pipeline_success = True
    elif upsert_result.is_degraded:
        terminal_state = "degraded"
        pipeline_success = True  # pipeline itself succeeded; indexing is partial
        warnings.append(
            f"Search indexing degraded: {upsert_result.successful_chunk_count}/"
            f"{upsert_result.attempted_chunk_count} chunks indexed"
        )
    else:
        terminal_state = "success"
        pipeline_success = True

    # Persist terminal state and emit final event with chunk counts
    if request.version_id:
        try:
            from app.core.jobs.tracker import persist_job_state
            await persist_job_state(
                str(request.version_id),
                terminal_state=terminal_state,
                attempted_chunk_count=upsert_result.attempted_chunk_count,
                successful_chunk_count=upsert_result.successful_chunk_count,
                failed_chunk_count=upsert_result.failed_chunk_count,
                retryable=upsert_result.retryable,
                errors=upsert_result.batch_errors if upsert_result.batch_errors else None,
            )
        except Exception:
            logger.warning("Failed to persist job state for %s", request.version_id, exc_info=True)

    await _emit_terminal(request.version_id, "ingestion_complete", {
        "document_id": str(request.document_id),
        "terminal_state": terminal_state,
        "chunks_indexed": indexed_count,
        "attempted_chunk_count": upsert_result.attempted_chunk_count,
        "successful_chunk_count": upsert_result.successful_chunk_count,
        "failed_chunk_count": upsert_result.failed_chunk_count,
        "retryable": upsert_result.retryable,
        "duration_ms": elapsed_ms,
    })

    logger.info(
        "[pipeline] %s %s → %s (%s) | %d chunks | %d/%d indexed | %dms",
        terminal_state.upper(),
        request.filename,
        classification.doc_type,
        f"L{classification.layer}",
        len(chunks),
        indexed_count,
        upsert_result.attempted_chunk_count,
        elapsed_ms,
    )

    # Assemble final result
    pipeline_data = {
        "doc_type": classification.doc_type,
        "vehicle_type": classification.vehicle_type,
        "classification_confidence": classification.confidence,
        "classification_layer": classification.layer,
        "classification_model": classification.model_name,
        "governance_critical": gov_critical,
        "governance_flags": gov_flags,
        "chunk_count": len(chunks),
        "chunks_indexed": indexed_count,
        "attempted_chunk_count": upsert_result.attempted_chunk_count,
        "successful_chunk_count": upsert_result.successful_chunk_count,
        "failed_chunk_count": upsert_result.failed_chunk_count,
        "terminal_state": terminal_state,
        "retryable": upsert_result.retryable,
        "metadata": extraction_metadata,
        "summary": summary_text,
        "extraction_quality": extraction_quality_codes,
        "extraction_degraded": extraction_degraded,
    }

    return PipelineStageResult(
        stage="complete",
        success=pipeline_success,
        data=pipeline_data,
        metrics=metrics,
        warnings=warnings,
    )

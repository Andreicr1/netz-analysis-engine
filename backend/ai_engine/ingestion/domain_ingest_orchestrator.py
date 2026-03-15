"""Domain Ingest Orchestrator — cognitive backbone of Netz Private Credit OS.

Pipeline: Blob → Text Extraction → Chunking → Embedding → Azure Search Upsert
          → AI Analysis → Postgres Writeback.

All operations are:
- Idempotent (skip already-indexed docs, mergeOrUpload chunks)
- Transaction-safe (mark indexed only on success)
- Domain-aware (PIPELINE vs PORTFOLIO via entity type)
- Production-safe (batch processing, error isolation)
- Non-destructive (never deletes data, only appends/merges)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_engine.extraction.entity_bootstrap import FundContext

from sqlalchemy.orm import Session

from app.domains.credit.modules.deals.ai_mode import AIMode

logger = logging.getLogger(__name__)


# ── Result types ──────────────────────────────────────────────────────


@dataclass
class DocumentIngestResult:
    document_id: uuid.UUID
    deal_id: uuid.UUID
    domain: str
    chunks_created: int = 0
    chunks_upserted: int = 0
    success: bool = False
    error: str | None = None


@dataclass
class IngestRunResult:
    documents_processed: int = 0
    documents_succeeded: int = 0
    documents_failed: int = 0
    chunks_upserted: int = 0
    deals_analyzed: int = 0
    results: list[DocumentIngestResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ── Domain resolution ────────────────────────────────────────────────


def _resolve_document_domain(
    db: Session,
    *,
    deal_id: uuid.UUID,
    document_table: str,
) -> tuple[str, uuid.UUID, str, str | None]:
    """Resolve domain + metadata from the document's parent deal.

    Returns: (domain, fund_id, deal_name, sponsor_name)
    """
    if document_table == "pipeline_deal_documents":
        from sqlalchemy import select

        from app.domains.credit.modules.deals.models import PipelineDeal

        stmt = select(PipelineDeal).where(PipelineDeal.id == deal_id)
        deal = db.execute(stmt).scalar_one()

        # If deal has been approved, the documents should be in portfolio mode
        if deal.approved_deal_id is not None:
            domain = AIMode.PORTFOLIO.value
        else:
            domain = AIMode.PIPELINE.value

        return domain, deal.fund_id, deal.title, deal.sponsor_name or deal.borrower_name

    # For domain deal_documents table
    from sqlalchemy import select

    from app.domains.credit.deals.models.deals import Deal as DomainDeal

    stmt = select(DomainDeal).where(DomainDeal.id == deal_id)
    deal = db.execute(stmt).scalar_one()
    return AIMode.PORTFOLIO.value, deal.fund_id, deal.name, deal.sponsor_name


# ── Single document ingestion ────────────────────────────────────────


def _ingest_single_document(
    db: Session,
    *,
    document_id: uuid.UUID,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    domain: str,
    deal_name: str,
    blob_container: str,
    blob_path: str,
    doc_type: str,
    authority: str,
    filename: str,
) -> DocumentIngestResult:
    """Process a single document through the full ingest pipeline.

    Pipeline: Extract → Document Intelligence → Chunk → Embed → Upsert.
    Document Intelligence (classification + metadata extraction + summary)
    runs on the full extracted text BEFORE chunking to produce enriched
    doc_type, summary, and metadata for every chunk.
    """
    from ai_engine.extraction.chunking import chunk_document
    from ai_engine.extraction.document_intelligence import run_document_intelligence
    from ai_engine.extraction.embedding_service import generate_embeddings
    from ai_engine.extraction.search_upsert_service import build_search_document, upsert_chunks
    from ai_engine.extraction.text_extraction import extract_text_from_blob

    result = DocumentIngestResult(
        document_id=document_id,
        deal_id=deal_id,
        domain=domain,
    )

    try:
        # 1. Extract text
        pages = extract_text_from_blob(blob_container, blob_path)
        if not pages:
            logger.warning("No text extracted from %s/%s — skipping", blob_container, blob_path)
            result.success = True  # Not an error, just empty
            return result

        # 2. Document Intelligence — LLM classification + metadata + summary
        #    Runs on full concatenated text (pre-chunking) for maximum context.
        full_text = "\n\n".join(p["text"] for p in pages if p.get("text"))
        intel_doc_type = doc_type
        intel_summary: str | None = None
        intel_metadata: str | None = None

        try:
            intel = run_document_intelligence(
                title=f"{deal_name} — {filename}",
                filename=filename,
                container=blob_container,
                content=full_text,
            )
            # Use LLM-classified doc_type (overrides keyword-based type)
            if intel.classification.doc_type != "other" or doc_type in ("", "other", "attachment"):
                intel_doc_type = intel.classification.doc_type
                logger.info(
                    "DOC_TYPE_UPGRADED doc_id=%s old=%s new=%s confidence=%d",
                    document_id, doc_type, intel_doc_type,
                    intel.classification.confidence,
                )

            # Serialize summary + metadata for index enrichment
            if intel.summary.summary:
                summary_data = {
                    "summary": intel.summary.summary,
                    "key_findings": intel.summary.key_findings,
                    "relevance_score": intel.summary.deal_relevance_score,
                }
                intel_summary = json.dumps(summary_data, default=str)

            if intel.metadata.raw:
                intel_metadata = json.dumps(intel.metadata.raw, default=str)

        except Exception as intel_exc:
            # Document Intelligence failure is non-fatal — fall back to
            # keyword-based doc_type and proceed without enrichment.
            logger.warning(
                "Document Intelligence failed for %s (non-fatal, using keyword doc_type): %s",
                document_id, intel_exc,
            )

        # 3. Chunk
        chunks = chunk_document(pages)
        result.chunks_created = len(chunks)
        if not chunks:
            result.success = True
            return result

        # 4. Generate embeddings (batch)
        texts = [c["content"] for c in chunks]
        emb = generate_embeddings(texts)
        if len(emb.vectors) != len(chunks):
            raise ValueError(
                f"Embedding count mismatch: {len(emb.vectors)} vectors for {len(chunks)} chunks",
            )

        # 5. Build search documents (enriched with intelligence)
        search_docs = []
        for chunk, vector in zip(chunks, emb.vectors, strict=False):
            search_doc = build_search_document(
                deal_id=deal_id,
                fund_id=fund_id,
                domain=domain,
                doc_type=intel_doc_type,
                authority=authority or "",
                title=f"{deal_name} — {filename}",
                chunk_index=chunk["chunk_index"],
                content=chunk["content"],
                embedding=vector,
                page_start=chunk["page_start"],
                page_end=chunk["page_end"],
                container_name=blob_container,
                blob_name=blob_path,
                document_id=document_id,
                doc_summary=intel_summary,
                doc_metadata=intel_metadata,
            )
            search_docs.append(search_doc)

        # 6. Upsert to Azure Search
        upserted = upsert_chunks(search_docs)
        result.chunks_upserted = upserted

        result.success = True
        logger.info(
            "Ingested document %s: %d chunks, %d upserted (deal=%s, domain=%s, doc_type=%s)",
            document_id, len(chunks), upserted, deal_id, domain, intel_doc_type,
        )

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.error("Failed to ingest document %s: %s", document_id, result.error, exc_info=True)

    return result


# ── Main orchestrator entrypoint ─────────────────────────────────────


def run_ingest_for_unindexed_documents(
    db: Session,
    *,
    fund_id: uuid.UUID,
    deal_ids: list[uuid.UUID] | None = None,
    batch_size: int = 50,
    run_ai_analysis: bool = True,
) -> IngestRunResult:
    """Fetch unindexed documents, ingest them, then trigger AI analysis.

    Steps:
    1. Fetch documents where last_indexed_at IS NULL
    2. For each: extract → chunk → embed → upsert
    3. Mark indexed on success
    4. After all docs: trigger AI analysis per affected deal

    If *deal_ids* is provided, only documents belonging to those deals are
    processed — enabling incremental ingestion of newly-added deals without
    re-processing existing ones.

    Idempotent — safe to rerun.
    """
    from ai_engine.ingestion.registry_bridge import bridge_registry_to_deal_documents
    from app.domains.credit.modules.deals.deal_intelligence_repo import (
        get_unindexed_documents,
        mark_document_indexed,
    )

    run_result = IngestRunResult()

    # 0. Bridge: promote DocumentRegistry → DealDocument so the orchestrator
    #    can pick up blobs discovered by document_scanner / pipeline_intelligence.
    try:
        bridge = bridge_registry_to_deal_documents(db, fund_id=fund_id, deal_ids=deal_ids)
        if bridge.documents_created:
            logger.info(
                "Registry bridge created %d new DealDocument rows for fund %s",
                bridge.documents_created, fund_id,
            )
    except Exception as exc:
        logger.warning("Registry bridge failed (non-fatal, continuing): %s", exc, exc_info=True)

    # 1. Fetch unindexed documents
    docs = get_unindexed_documents(db, fund_id=fund_id, deal_ids=deal_ids, limit=batch_size)
    if not docs:
        logger.info("No unindexed documents found for fund %s", fund_id)
        return run_result

    logger.info("Found %d unindexed documents for fund %s", len(docs), fund_id)

    # Track deals that got new documents (for AI analysis)
    deals_with_new_docs: dict[uuid.UUID, tuple[str, uuid.UUID, str, str | None]] = {}

    # 2. Process each document.
    # Sequential by design: the shared SQLAlchemy session (db) is NOT thread-safe.
    # Each iteration reads from db (_resolve_document_domain), writes to db
    # (mark_document_indexed), and tracks cross-document state (deals_with_new_docs).
    # Parallelizing would require per-thread sessions and post-loop aggregation,
    # adding complexity disproportionate to the I/O savings since the heavy work
    # (_ingest_single_document) already batches its own embedding calls.
    for doc in docs:
        run_result.documents_processed += 1

        if not doc.blob_container or not doc.blob_path:
            logger.warning("Document %s has no blob path — skipping", doc.id)
            continue

        # Resolve domain from parent deal
        try:
            domain, doc_fund_id, deal_name, sponsor_name = _resolve_document_domain(
                db, deal_id=doc.deal_id, document_table=doc.__tablename__,
            )
        except Exception as exc:
            error_msg = f"Domain resolution failed for doc {doc.id}: {exc}"
            logger.error(error_msg)
            run_result.documents_failed += 1
            run_result.errors.append(error_msg)
            continue

        # Ingest
        doc_result = _ingest_single_document(
            db,
            document_id=doc.id,
            deal_id=doc.deal_id,
            fund_id=doc_fund_id,
            domain=domain,
            deal_name=deal_name,
            blob_container=doc.blob_container,
            blob_path=doc.blob_path,
            doc_type=doc.document_type,
            authority=doc.authority or "",
            filename=doc.filename,
        )
        run_result.results.append(doc_result)
        run_result.chunks_upserted += doc_result.chunks_upserted

        if doc_result.success:
            # 3. Mark indexed only on success
            try:
                mark_document_indexed(db, document_id=doc.id)
                run_result.documents_succeeded += 1

                # Track deal for AI analysis
                if doc.deal_id not in deals_with_new_docs:
                    deals_with_new_docs[doc.deal_id] = (domain, doc_fund_id, deal_name, sponsor_name)
            except Exception as exc:
                logger.error("Failed to mark document %s as indexed: %s", doc.id, exc)
                run_result.documents_failed += 1
        else:
            run_result.documents_failed += 1

    # 4. Trigger AI analysis for affected deals
    if run_ai_analysis and deals_with_new_docs:
        from vertical_engines.credit.domain_ai import run_deal_ai_analysis

        for deal_id, (domain, deal_fund_id, deal_name, sponsor_name) in deals_with_new_docs.items():
            try:
                run_deal_ai_analysis(
                    db,
                    deal_id=deal_id,
                    fund_id=deal_fund_id,
                    domain=domain,
                    deal_name=deal_name,
                    sponsor_name=sponsor_name,
                )
                run_result.deals_analyzed += 1
                logger.info("AI analysis completed for deal %s (domain=%s)", deal_id, domain)
            except Exception as exc:
                error_msg = f"AI analysis failed for deal {deal_id}: {exc}"
                logger.error(error_msg, exc_info=True)
                run_result.errors.append(error_msg)

            # REFACTOR (Phase 2, Step 5): For PIPELINE deals, the
            # consolidated pipeline_engine is now called inside
            # run_deal_ai_analysis → generate_pipeline_intelligence.
            # The separate generate_structured_intelligence() call has
            # been removed to prevent duplicate RAG + GPT invocations.

    logger.info(
        "Ingest run complete: %d processed, %d succeeded, %d failed, %d chunks, %d deals analyzed",
        run_result.documents_processed,
        run_result.documents_succeeded,
        run_result.documents_failed,
        run_result.chunks_upserted,
        run_result.deals_analyzed,
    )
    return run_result


# ── Async orchestrator ───────────────────────────────────────────────

_INGEST_DOC_CONCURRENCY = max(1, int(os.getenv("NETZ_INGEST_DOC_CONCURRENCY", "3")))


@dataclass(frozen=True)
class DocumentInfo:
    """Immutable ORM-detached container for async document processing.

    All fields are primitives — no ORM relationships, no session dependency.
    Frozen to guarantee no coroutine mutates shared state.
    """

    document_id: uuid.UUID
    deal_id: uuid.UUID
    fund_id: uuid.UUID
    domain: str
    deal_name: str
    blob_container: str
    blob_path: str
    document_type: str
    authority: str
    filename: str
    sponsor_name: str | None = None
    fund_context: FundContext | None = None  # FundContext from entity bootstrap (Stage 2.5)


async def _async_ingest_single_document(doc: DocumentInfo) -> DocumentIngestResult:
    """Process a single document through the async hybrid ingest pipeline.

    Pipeline:
    1. Skip filter (compliance forms)
    2. Text extraction (Mistral OCR for PDFs, pypdf fallback)
    3. Full Intelligence (Cohere Rerank + governance + LLM metadata/summary)
    4. Semantic chunking (adaptive sizing, breadcrumb, section_type)
    5. Per-chunk enrichment (borrower_sector, risk_flags, etc.)
    6. Embedding (text-embedding-3-large)
    7. Build enriched search documents (~23 fields)
    8. Upsert to Azure Search

    No DB session — all domain data is pre-fetched in DocumentInfo.
    """
    result = DocumentIngestResult(
        document_id=doc.document_id,
        deal_id=doc.deal_id,
        domain=doc.domain,
    )

    try:
        from ai_engine.extraction.chunking import chunk_document_semantic
        from ai_engine.extraction.search_upsert_service import build_search_document, upsert_chunks
        from ai_engine.extraction.skip_filter import should_skip_document
        from ai_engine.extraction.text_extraction import (
            async_extract_text_from_blob,
            extract_text_from_blob,
        )

        # 1. Skip filter — compliance forms (W-8BEN, FATCA, KYC)
        if should_skip_document(doc.filename):
            logger.info("Skipping compliance form: %s", doc.filename)
            result.success = True
            return result

        # 2. Text extraction (Mistral OCR for PDFs, pypdf fallback)
        try:
            pages = await async_extract_text_from_blob(doc.blob_container, doc.blob_path)
        except Exception:
            logger.warning(
                "Async text extraction failed, falling back to sync: %s",
                doc.filename, exc_info=True,
            )
            pages = await asyncio.to_thread(
                extract_text_from_blob, doc.blob_container, doc.blob_path,
            )

        if not pages:
            logger.warning(
                "No text extracted from %s/%s — skipping",
                doc.blob_container, doc.blob_path,
            )
            result.success = True
            return result

        full_text = "\n\n".join(p["text"] for p in pages if p.get("text"))

        # 3. Full Intelligence — Cohere + governance + LLM metadata/summary
        intel_doc_type = doc.document_type
        intel_vehicle_type: str | None = None
        intel_summary: str | None = None
        intel_metadata: str | None = None
        gov_critical: bool = False
        gov_flags: list[str] = []

        try:
            from ai_engine.extraction.document_intelligence import async_run_full_intelligence

            intel = await async_run_full_intelligence(
                title=f"{doc.deal_name} — {doc.filename}",
                filename=doc.filename,
                container=doc.blob_container,
                content=full_text,
                fund_context=doc.fund_context,
            )
            if intel.doc_type != "other" or doc.document_type in ("", "other", "attachment"):
                intel_doc_type = intel.doc_type
                logger.info(
                    "DOC_TYPE_UPGRADED doc_id=%s old=%s new=%s score=%.3f source=%s",
                    doc.document_id, doc.document_type, intel_doc_type,
                    intel.doc_type_score, intel.classification_source,
                )

            intel_vehicle_type = intel.vehicle_type
            gov_critical = intel.governance_critical
            gov_flags = intel.governance_flags

            if intel.summary.summary:
                summary_data = {
                    "summary": intel.summary.summary,
                    "key_findings": intel.summary.key_findings,
                    "relevance_score": intel.summary.deal_relevance_score,
                }
                intel_summary = json.dumps(summary_data, default=str)

            if intel.metadata.raw:
                intel_metadata = json.dumps(intel.metadata.raw, default=str)

        except Exception as intel_exc:
            logger.warning(
                "Full Intelligence failed for %s (non-fatal, using keyword doc_type): %s",
                doc.document_id, intel_exc,
            )

        # 4. Semantic chunking (adaptive sizing, breadcrumb, section_type)
        enriched_chunks = chunk_document_semantic(
            pages,
            doc_id=str(doc.document_id),
            doc_type=intel_doc_type,
            metadata={"doc_type": intel_doc_type},
        )
        # Free raw page data
        del pages

        result.chunks_created = len(enriched_chunks)
        if not enriched_chunks:
            result.success = True
            return result

        # 5. Per-chunk enrichment (borrower_sector, risk_flags, etc.)
        try:
            from ai_engine.extraction.deals_enrichment import async_enrich_chunks

            await async_enrich_chunks(
                enriched_chunks, intel_doc_type,
                fund_context=doc.fund_context,
            )
        except Exception as enrich_exc:
            logger.warning(
                "Per-chunk enrichment failed for %s (non-fatal): %s",
                doc.document_id, enrich_exc,
            )

        # 6. Generate embeddings (async)
        texts = [c.get("content", "") for c in enriched_chunks]
        from ai_engine.extraction.embedding_service import async_generate_embeddings

        emb = await async_generate_embeddings(texts)
        if len(emb.vectors) != len(enriched_chunks):
            raise ValueError(
                f"Embedding count mismatch: {len(emb.vectors)} vectors for {len(enriched_chunks)} chunks",
            )

        # 7. Build enriched search documents (~23 fields)
        search_docs = []
        for chunk, vector in zip(enriched_chunks, emb.vectors, strict=False):
            search_doc = build_search_document(
                deal_id=doc.deal_id,
                fund_id=doc.fund_id,
                domain=doc.domain,
                doc_type=intel_doc_type,
                authority=doc.authority,
                title=f"{doc.deal_name} — {doc.filename}",
                chunk_index=chunk.get("chunk_index", 0),
                content=chunk.get("content", ""),
                embedding=vector,
                page_start=chunk.get("page_start", 1),
                page_end=chunk.get("page_end", 1),
                container_name=doc.blob_container,
                blob_name=doc.blob_path,
                document_id=doc.document_id,
                doc_summary=intel_summary,
                doc_metadata=intel_metadata,
                # Hybrid pipeline enrichment fields
                vehicle_type=intel_vehicle_type,
                section_type=chunk.get("section_type"),
                breadcrumb=chunk.get("breadcrumb"),
                has_table=chunk.get("has_table"),
                has_numbers=chunk.get("has_numbers"),
                char_count=chunk.get("char_count"),
                governance_critical=gov_critical,
                governance_flags=gov_flags if gov_flags else None,
                borrower_sector=chunk.get("borrower_sector"),
                loan_structure=chunk.get("loan_structure"),
                key_persons_mentioned=chunk.get("key_persons_mentioned"),
                financial_metric_type=chunk.get("financial_metric_type"),
                risk_flags=chunk.get("risk_flags"),
            )
            search_docs.append(search_doc)

        # 8. Upsert to Azure Search (sync SDK → to_thread)
        upserted = await asyncio.to_thread(upsert_chunks, search_docs)
        result.chunks_upserted = upserted

        result.success = True
        logger.info(
            "Async ingested document %s: %d chunks, %d upserted "
            "(deal=%s, domain=%s, doc_type=%s, vehicle=%s, gov_flags=%d)",
            doc.document_id, len(enriched_chunks), upserted,
            doc.deal_id, doc.domain, intel_doc_type,
            intel_vehicle_type, len(gov_flags),
        )

    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        logger.error(
            "Async failed to ingest document %s: %s",
            doc.document_id, result.error, exc_info=True,
        )

    return result


async def async_run_ingest_for_unindexed_documents(
    fund_id: uuid.UUID,
    *,
    deal_ids: list[uuid.UUID] | None = None,
    batch_size: int = 200,
    run_ai_analysis: bool = True,
    fund_contexts: dict[uuid.UUID, object] | None = None,
) -> IngestRunResult:
    """Async parallel document ingestion with session-per-operation.

    Three-phase pattern:
      1. Pre-fetch (sync, session A) — fetch docs + resolve domains → DocumentInfo
      2. Parallel ingest (async, no DB) — bounded by Semaphore
      3. Post-write (sync, session B) — mark indexed + trigger AI analysis
    """
    from ai_engine.ingestion.registry_bridge import bridge_registry_to_deal_documents
    from app.domains.credit.modules.deals.deal_intelligence_repo import (
        get_unindexed_documents,
        mark_document_indexed,
    )

    run_result = IngestRunResult()

    # ── Phase 1: Pre-fetch (sync, session A) ──────────────────────────
    SessionLocal = async_session_factory
    db = SessionLocal()
    doc_infos: list[DocumentInfo] = []
    try:
        # Bridge registry → deal documents
        try:
            bridge = bridge_registry_to_deal_documents(db, fund_id=fund_id, deal_ids=deal_ids)
            if bridge.documents_created:
                logger.info(
                    "Registry bridge created %d new DealDocument rows for fund %s",
                    bridge.documents_created, fund_id,
                )
        except Exception as exc:
            logger.warning("Registry bridge failed (non-fatal): %s", exc, exc_info=True)

        # Fetch unindexed documents
        docs = get_unindexed_documents(db, fund_id=fund_id, deal_ids=deal_ids, limit=batch_size)
        if not docs:
            logger.info("No unindexed documents found for fund %s", fund_id)
            return run_result

        logger.info("Found %d unindexed documents for fund %s", len(docs), fund_id)

        # Resolve domains and capture into frozen dataclasses
        for doc in docs:
            if not doc.blob_container or not doc.blob_path:
                logger.warning("Document %s has no blob path — skipping", doc.id)
                continue

            try:
                domain, doc_fund_id, deal_name, sponsor_name = _resolve_document_domain(
                    db, deal_id=doc.deal_id, document_table=doc.__tablename__,
                )
            except Exception as exc:
                error_msg = f"Domain resolution failed for doc {doc.id}: {exc}"
                logger.error(error_msg)
                run_result.documents_failed += 1
                run_result.errors.append(error_msg)
                run_result.documents_processed += 1
                continue

            doc_infos.append(
                DocumentInfo(
                    document_id=doc.id,
                    deal_id=doc.deal_id,
                    fund_id=doc_fund_id,
                    domain=domain,
                    deal_name=deal_name,
                    blob_container=doc.blob_container,
                    blob_path=doc.blob_path,
                    document_type=doc.document_type,
                    authority=doc.authority or "",
                    filename=doc.filename,
                    sponsor_name=sponsor_name,
                    fund_context=(fund_contexts or {}).get(doc.deal_id),
                ),
            )
    finally:
        # Close session A before entering async context
        db.close()

    if not doc_infos:
        return run_result

    # ── Phase 2: Parallel ingest (async, no DB) ──────────────────────
    sem = asyncio.Semaphore(_INGEST_DOC_CONCURRENCY)

    async def _bounded_ingest(doc_info: DocumentInfo) -> DocumentIngestResult:
        async with sem:
            return await _async_ingest_single_document(doc_info)

    tasks = [_bounded_ingest(info) for info in doc_infos]
    raw_results: list[DocumentIngestResult | BaseException] = await asyncio.gather(
        *tasks, return_exceptions=True,
    )

    # ── Phase 3: Post-write (sync, fresh session B) ──────────────────
    db = SessionLocal()
    deals_with_new_docs: dict[uuid.UUID, tuple[str, uuid.UUID, str, str | None]] = {}
    try:
        for doc_info, raw_result in zip(doc_infos, raw_results, strict=False):
            run_result.documents_processed += 1

            if isinstance(raw_result, BaseException):
                run_result.documents_failed += 1
                error_msg = f"Document {doc_info.document_id} raised {type(raw_result).__name__}: {raw_result}"
                run_result.errors.append(error_msg)
                logger.error("Async ingest exception: %s", error_msg)
                continue

            doc_result = raw_result
            run_result.results.append(doc_result)
            run_result.chunks_upserted += doc_result.chunks_upserted

            if doc_result.success:
                try:
                    mark_document_indexed(db, document_id=doc_info.document_id)
                    run_result.documents_succeeded += 1

                    if doc_info.deal_id not in deals_with_new_docs:
                        deals_with_new_docs[doc_info.deal_id] = (
                            doc_info.domain,
                            doc_info.fund_id,
                            doc_info.deal_name,
                            doc_info.sponsor_name,
                        )
                except Exception as exc:
                    logger.error(
                        "Failed to mark document %s as indexed: %s",
                        doc_info.document_id, exc,
                    )
                    run_result.documents_failed += 1
            else:
                run_result.documents_failed += 1

        # Trigger AI analysis for affected deals (sequential, uses DB)
        if run_ai_analysis and deals_with_new_docs:
            from vertical_engines.credit.domain_ai import run_deal_ai_analysis

            for deal_id, (domain, deal_fund_id, deal_name, sponsor_name) in deals_with_new_docs.items():
                try:
                    run_deal_ai_analysis(
                        db,
                        deal_id=deal_id,
                        fund_id=deal_fund_id,
                        domain=domain,
                        deal_name=deal_name,
                        sponsor_name=sponsor_name,
                    )
                    run_result.deals_analyzed += 1
                    logger.info("AI analysis completed for deal %s (domain=%s)", deal_id, domain)
                except Exception as exc:
                    error_msg = f"AI analysis failed for deal {deal_id}: {exc}"
                    logger.error(error_msg, exc_info=True)
                    run_result.errors.append(error_msg)

        # Single commit for all mark_document_indexed + job status
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    logger.info(
        "Async ingest run complete: %d processed, %d succeeded, %d failed, %d chunks, %d deals analyzed",
        run_result.documents_processed,
        run_result.documents_succeeded,
        run_result.documents_failed,
        run_result.chunks_upserted,
        run_result.deals_analyzed,
    )
    return run_result


# ── Single-deal re-analysis ──────────────────────────────────────────


def reanalyze_deal(
    db: Session,
    *,
    pipeline_deal_id: uuid.UUID | None = None,
    deal_id: uuid.UUID | None = None,
) -> dict:
    """Re-run AI analysis for a specific deal without re-ingesting documents.

    Useful after manual corrections or additional context.
    """
    from app.domains.credit.modules.deals.ai_mode import resolve_ai_mode
    from vertical_engines.credit.domain_ai import run_deal_ai_analysis

    ctx = resolve_ai_mode(db, pipeline_deal_id=pipeline_deal_id, deal_id=deal_id)
    return run_deal_ai_analysis(
        db,
        deal_id=ctx.entity_id,
        fund_id=ctx.fund_id,
        domain=ctx.mode.value,
        deal_name=ctx.deal_name,
        sponsor_name=ctx.sponsor_name,
    )

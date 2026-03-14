"""Knowledge Ingest Runner — fund-level policy / governance / regulatory documents.

Indexes global fund documents stored directly in Azure Blob containers into
Azure AI Search (global-vector-chunks-v2).  These documents are NOT tracked
in Postgres via the deal-centric document registry — they are authoritative
sources that live at the fund level.

Target containers:
  • risk-policy-internal         → POLICY domain
  • fund-constitution-governance → GOVERNANCE domain
  • regulatory-library-cima      → REGULATORY domain

Pipeline:
  1. list_blobs_in_container()   — enumerate all supported files
  2. extract_blob_text()         — download + text extraction
  3. chunk_text()                — page-boundary chunking (~4 000 chars)
  4. generate + upsert           — embeddings via openai_client, upsert via search_upsert_service

Design constraints:
  • Chunk IDs are deterministic (SHA-256 of container:blob_path:chunk_index).
  • Reruns overwrite — no duplicate chunk IDs ever created.
  • No deal_id — these are fund-level documents.
  • Authority metadata always set for every chunk.
  • No hardcoded index names — uses settings.SEARCH_CHUNKS_INDEX_NAME.
"""
from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ai_engine.extraction.chunking import Chunk, PageInput
    from ai_engine.extraction.text_extraction import PageBlock

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════
#  Container configuration map
# ══════════════════════════════════════════════════════════════════════

KNOWLEDGE_CONTAINERS: dict[str, dict[str, str]] = {
    "risk-policy-internal": {
        "domain": "POLICY",
        "doc_type": "FUND_POLICY",
        "authority": "INTERNAL",
    },
    "fund-constitution-governance": {
        "domain": "GOVERNANCE",
        "doc_type": "FUND_CONSTITUTION",
        "authority": "FUND_GOVERNANCE",
    },
    "regulatory-library-cima": {
        "domain": "REGULATORY",
        "doc_type": "REGULATORY_CIMA",
        "authority": "CIMA",
    },
}

# Allowed file extensions for knowledge documents
_SUPPORTED_EXTENSIONS = frozenset({"pdf", "docx", "txt", "md"})


# ══════════════════════════════════════════════════════════════════════
#  Data types
# ══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class BlobDescriptor:
    """Metadata for a single blob to be ingested."""

    container: str
    blob_path: str
    filename: str
    extension: str
    size_bytes: int | None = None


@dataclass
class IngestResult:
    """Result for a single blob ingestion."""

    container: str
    blob_path: str
    chunks_indexed: int = 0
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None


@dataclass
class KnowledgeIngestReport:
    """Summary of an entire knowledge ingestion run."""

    fund_id: str
    containers_processed: list[str] = field(default_factory=list)
    total_blobs_found: int = 0
    total_blobs_processed: int = 0
    total_chunks_indexed: int = 0
    total_failures: int = 0
    results: list[IngestResult] = field(default_factory=list)
    started_at: str = ""
    completed_at: str = ""


# ══════════════════════════════════════════════════════════════════════
#  1. Blob enumeration
# ══════════════════════════════════════════════════════════════════════


def _get_extension(filename: str) -> str:
    """Extract lowercase file extension from filename."""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def list_blobs_in_container(container_name: str) -> list[BlobDescriptor]:
    """List all supported files in a Blob container recursively.

    Uses the Azure Blob SDK to do a flat listing (no delimiter) so all
    blobs at any depth are returned.

    Args:
        container_name: Azure Blob container name.

    Returns:
        Sorted list of BlobDescriptor for supported file types.

    """
    from app.services.azure.blob_client import get_blob_service_client

    svc = get_blob_service_client()
    container_client = svc.get_container_client(container_name)

    descriptors: list[BlobDescriptor] = []
    try:
        for blob in container_client.list_blobs():
            name: str = blob.name
            # Skip directory placeholders and empty names
            if not name or name.endswith("/"):
                continue
            filename = name.rsplit("/", 1)[-1] if "/" in name else name
            ext = _get_extension(filename)
            if ext not in _SUPPORTED_EXTENSIONS:
                continue
            descriptors.append(BlobDescriptor(
                container=container_name,
                blob_path=name,
                filename=filename,
                extension=ext,
                size_bytes=blob.size,
            ))
    except Exception as exc:
        logger.error(
            "KNOWLEDGE_INGEST_BLOB_LIST_ERROR container=%s error=%s",
            container_name,
            exc,
            exc_info=True,
        )
        raise

    # Deterministic ordering by blob path
    descriptors.sort(key=lambda d: d.blob_path)
    return descriptors


# ══════════════════════════════════════════════════════════════════════
#  2. Text extraction
# ══════════════════════════════════════════════════════════════════════


def extract_blob_text(container: str, blob_path: str) -> str:
    """Download blob and extract text content.

    Reuses ai_engine.extraction.text_extraction which supports PDF, DOCX, TXT, MD.
    Returns empty string if extraction fails or yields no text.
    """
    try:
        from ai_engine.extraction.text_extraction import extract_text_from_blob

        pages = extract_text_from_blob(container, blob_path)
        if not pages:
            return ""
        return "\n\n".join(p["text"] for p in pages if p.get("text"))
    except Exception as exc:
        logger.error(
            "KNOWLEDGE_INGEST_EXTRACT_ERROR container=%s blob=%s error=%s",
            container,
            blob_path,
            exc,
        )
        return ""


def _extract_pages(container: str, blob_path: str) -> list[PageBlock]:
    """Download blob and extract page-aware text blocks.

    Returns list of PageBlock dicts for the chunker.
    Returns empty list on failure.
    """
    try:
        from ai_engine.extraction.text_extraction import extract_text_from_blob

        return extract_text_from_blob(container, blob_path)
    except Exception as exc:
        logger.error(
            "KNOWLEDGE_INGEST_EXTRACT_ERROR container=%s blob=%s error=%s",
            container,
            blob_path,
            exc,
        )
        return []


# ══════════════════════════════════════════════════════════════════════
#  3. Chunking
# ══════════════════════════════════════════════════════════════════════


def chunk_text(pages: list[PageInput]) -> list[Chunk]:
    """Chunk page-aware text blocks using the existing ai_engine chunker.

    Args:
        pages: List of PageBlock dicts (page_start, page_end, text).

    Returns:
        List of Chunk dicts (chunk_index, page_start, page_end, content).

    """
    from ai_engine.extraction.chunking import chunk_document

    return chunk_document(pages)


# ══════════════════════════════════════════════════════════════════════
#  4. Stable chunk IDs (idempotency)
# ══════════════════════════════════════════════════════════════════════


def compute_chunk_id(container: str, blob_path: str, chunk_index: int) -> str:
    """Generate a deterministic chunk ID via SHA-256.

    Formula: sha256(f"{container}:{blob_path}:{chunk_index}")

    This ensures:
      • Same blob + same chunk_index → same ID on every run
      • mergeOrUpload action overwrites → no duplicates
    """
    raw = f"{container}:{blob_path}:{chunk_index}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ══════════════════════════════════════════════════════════════════════
#  5. Single-blob ingestion
# ══════════════════════════════════════════════════════════════════════


def _build_knowledge_search_document(
    *,
    chunk_id: str,
    fund_id: uuid.UUID,
    domain: str,
    doc_type: str,
    authority: str,
    container_name: str,
    blob_name: str,
    title: str,
    chunk_index: int,
    content: str,
    embedding: list[float],
    page_start: int,
    page_end: int,
) -> dict[str, Any]:
    """Build a search document for a knowledge chunk.

    Matches the global-vector-chunks-v2 schema.
    deal_id is set to a nil UUID since these are fund-level documents.
    """
    now = datetime.now(UTC).isoformat()
    return {
        "@search.action": "mergeOrUpload",
        "id": chunk_id,
        "fund_id": str(fund_id),
        "deal_id": str(uuid.UUID(int=0)),  # nil UUID — no deal
        "domain": domain,
        "doc_type": doc_type,
        "authority": authority,
        "title": title,
        "content": content,
        "embedding": embedding,
        "page_start": page_start,
        "page_end": page_end,
        "chunk_index": chunk_index,
        "container_name": container_name,
        "blob_name": blob_name,
        "created_at": now,
        "last_modified": now,
    }


def ingest_single_blob(
    *,
    descriptor: BlobDescriptor,
    fund_id: uuid.UUID,
    container_config: dict[str, str],
) -> IngestResult:
    """Ingest a single blob: extract → chunk → embed → upsert.

    Args:
        descriptor: Blob metadata.
        fund_id: Fund UUID for metadata tagging.
        container_config: Domain/doc_type/authority from KNOWLEDGE_CONTAINERS.

    Returns:
        IngestResult with chunk count or error details.

    """
    from ai_engine.extraction.embedding_service import generate_embeddings
    from ai_engine.extraction.search_upsert_service import upsert_chunks

    result = IngestResult(
        container=descriptor.container,
        blob_path=descriptor.blob_path,
    )

    # Step 1: Extract page-aware text
    pages = _extract_pages(descriptor.container, descriptor.blob_path)
    if not pages:
        result.skipped = True
        result.skip_reason = "No text extracted"
        logger.warning(
            "KNOWLEDGE_INGEST_SKIP blob=%s reason=no_text_extracted",
            descriptor.blob_path,
        )
        return result

    # Step 2: Chunk
    chunks = chunk_text(pages)
    if not chunks:
        result.skipped = True
        result.skip_reason = "Zero chunks produced"
        logger.warning(
            "KNOWLEDGE_INGEST_SKIP blob=%s reason=zero_chunks",
            descriptor.blob_path,
        )
        return result

    # Step 3: Generate embeddings
    texts = [c["content"] for c in chunks]
    try:
        emb_batch = generate_embeddings(texts)
    except Exception as exc:
        result.error = f"Embedding failed: {type(exc).__name__}: {exc}"
        logger.error(
            "KNOWLEDGE_INGEST_EMBED_ERROR blob=%s error=%s",
            descriptor.blob_path,
            exc,
        )
        return result

    if len(emb_batch.vectors) != len(chunks):
        result.error = (
            f"Embedding count mismatch: {len(emb_batch.vectors)} vectors "
            f"vs {len(chunks)} chunks"
        )
        return result

    # Step 4: Build search documents with deterministic IDs
    search_docs: list[dict[str, Any]] = []
    for chunk, vector in zip(chunks, emb_batch.vectors, strict=False):
        chunk_id = compute_chunk_id(
            descriptor.container, descriptor.blob_path, chunk["chunk_index"],
        )
        doc = _build_knowledge_search_document(
            chunk_id=chunk_id,
            fund_id=fund_id,
            domain=container_config["domain"],
            doc_type=container_config["doc_type"],
            authority=container_config["authority"],
            container_name=descriptor.container,
            blob_name=descriptor.blob_path,
            title=descriptor.filename,
            chunk_index=chunk["chunk_index"],
            content=chunk["content"],
            embedding=vector,
            page_start=chunk["page_start"],
            page_end=chunk["page_end"],
        )
        search_docs.append(doc)

    # Step 5: Upsert to Azure Search
    try:
        indexed = upsert_chunks(search_docs)
        result.chunks_indexed = indexed
    except Exception as exc:
        result.error = f"Upsert failed: {type(exc).__name__}: {exc}"
        logger.error(
            "KNOWLEDGE_INGEST_UPSERT_ERROR blob=%s error=%s",
            descriptor.blob_path,
            exc,
        )
        return result

    logger.info(
        "KNOWLEDGE_INGEST_OK blob=%s chunks=%d domain=%s",
        descriptor.blob_path,
        indexed,
        container_config["domain"],
    )
    return result


# ══════════════════════════════════════════════════════════════════════
#  6. Full ingestion run
# ══════════════════════════════════════════════════════════════════════


def run_knowledge_ingest(
    *,
    fund_id: uuid.UUID,
    containers: list[str] | None = None,
) -> KnowledgeIngestReport:
    """Run the knowledge ingestion pipeline for selected containers.

    Args:
        fund_id: Fund UUID for metadata tagging on all indexed chunks.
        containers: List of container names to ingest.  If None, ingests
                    all containers in KNOWLEDGE_CONTAINERS.

    Returns:
        KnowledgeIngestReport with per-blob results and totals.

    """
    target_containers = containers or list(KNOWLEDGE_CONTAINERS.keys())

    # Validate containers
    for c in target_containers:
        if c not in KNOWLEDGE_CONTAINERS:
            raise ValueError(
                f"Unknown knowledge container '{c}'. "
                f"Valid: {sorted(KNOWLEDGE_CONTAINERS.keys())}",
            )

    report = KnowledgeIngestReport(
        fund_id=str(fund_id),
        started_at=datetime.now(UTC).isoformat(),
    )

    for container_name in sorted(target_containers):
        config = KNOWLEDGE_CONTAINERS[container_name]
        report.containers_processed.append(container_name)

        logger.info(
            "KNOWLEDGE_INGEST_START container=%s domain=%s",
            container_name,
            config["domain"],
        )

        # Enumerate blobs
        try:
            blobs = list_blobs_in_container(container_name)
        except Exception as exc:
            logger.error(
                "KNOWLEDGE_INGEST_CONTAINER_ERROR container=%s error=%s",
                container_name,
                exc,
            )
            report.results.append(IngestResult(
                container=container_name,
                blob_path="*",
                error=f"Container listing failed: {type(exc).__name__}: {exc}",
            ))
            report.total_failures += 1
            continue

        report.total_blobs_found += len(blobs)
        logger.info(
            "KNOWLEDGE_INGEST_BLOBS_FOUND container=%s count=%d",
            container_name,
            len(blobs),
        )

        # Process blobs in parallel — each blob is fully independent
        # (no shared DB session; I/O pipeline: download → chunk → embed → upsert).
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_blob = {
                executor.submit(
                    ingest_single_blob,
                    descriptor=descriptor,
                    fund_id=fund_id,
                    container_config=config,
                ): descriptor
                for descriptor in blobs
            }
            for future in as_completed(future_to_blob):
                blob_result = future.result()
                report.results.append(blob_result)

                if blob_result.error:
                    report.total_failures += 1
                elif not blob_result.skipped:
                    report.total_blobs_processed += 1
                    report.total_chunks_indexed += blob_result.chunks_indexed

    report.completed_at = datetime.now(UTC).isoformat()

    logger.info(
        "KNOWLEDGE_INGEST_COMPLETE fund=%s containers=%s "
        "blobs_found=%d processed=%d chunks=%d failures=%d",
        fund_id,
        report.containers_processed,
        report.total_blobs_found,
        report.total_blobs_processed,
        report.total_chunks_indexed,
        report.total_failures,
    )

    return report

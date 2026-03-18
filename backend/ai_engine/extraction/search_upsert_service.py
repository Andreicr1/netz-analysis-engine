# DEPRECATED: use pgvector_search_service — Azure Search eliminated in favor of pgvector.
# Retained for rollback capability during re-ingestion migration.
"""Azure AI Search upsert service for the canonical env-scoped chunks index.

Uses mergeOrUpload action for idempotent upserts.
Handles id constraints (no colons or special characters).
Batches uploads for performance.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)

_UPLOAD_BATCH_SIZE = 100


@dataclass(frozen=True)
class UpsertResult:
    """Structured result from a search upsert operation.

    Callers use this to distinguish full success, partial (degraded), and
    total failure without inspecting logs.
    """

    attempted_chunk_count: int
    successful_chunk_count: int
    failed_chunk_count: int
    retryable: bool
    batch_errors: list[str] = field(default_factory=list)

    @property
    def is_full_success(self) -> bool:
        return self.failed_chunk_count == 0 and self.successful_chunk_count > 0

    @property
    def is_degraded(self) -> bool:
        return self.failed_chunk_count > 0 and self.successful_chunk_count > 0

    @property
    def is_total_failure(self) -> bool:
        return self.successful_chunk_count == 0 and self.attempted_chunk_count > 0

# ── OData injection prevention (Security F2/F5/F6) ──────────────────
_VALID_DOMAINS = frozenset({
    "credit", "wealth", "macro", "benchmark",
    "POLICY", "REGULATORY", "CONSTITUTION", "SERVICE_PROVIDER",
    "PIPELINE",
})


def validate_uuid(value: str | uuid.UUID, field_name: str = "id") -> str:
    """Validate and normalize UUID for safe OData filter interpolation.

    Returns lowercase hyphenated canonical form.
    Raises ValueError on invalid input — prevents OData injection on ID fields.
    """
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        raise ValueError(f"Invalid UUID for {field_name}: {value!r}")


def validate_domain(domain: str) -> str:
    """Validate domain against allowlist. Prevents OData injection on string fields.

    Update _VALID_DOMAINS when adding new verticals — see app/shared/enums.py.
    """
    if domain not in _VALID_DOMAINS:
        raise ValueError(f"Invalid domain filter: {domain!r}")
    return domain


def _safe_id(raw: str) -> str:
    """Sanitize a document id for Azure Search (alphanumeric, dash, underscore)."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)


def _chunks_index_name() -> str:
    from app.services.azure.search_client import resolve_chunks_index_name

    return resolve_chunks_index_name()


def build_search_document(
    *,
    deal_id: uuid.UUID,
    fund_id: uuid.UUID,
    domain: str,
    doc_type: str,
    authority: str,
    title: str,
    chunk_index: int,
    content: str,
    embedding: list[float],
    page_start: int,
    page_end: int,
    container_name: str | None = None,
    blob_name: str | None = None,
    document_id: uuid.UUID | None = None,
    doc_summary: str | None = None,
    doc_metadata: str | None = None,
    # ── Hybrid pipeline enrichment fields (Phase 6) ──────────────────
    vehicle_type: str | None = None,
    section_type: str | None = None,
    breadcrumb: str | None = None,
    has_table: bool | None = None,
    has_numbers: bool | None = None,
    char_count: int | None = None,
    governance_critical: bool | None = None,
    governance_flags: list[str] | None = None,
    borrower_sector: str | None = None,
    loan_structure: str | None = None,
    key_persons_mentioned: list[str] | None = None,
    financial_metric_type: str | None = None,
    risk_flags: list[str] | None = None,
    organization_id: uuid.UUID | None = None,
    extraction_degraded: bool | None = None,
    extraction_quality: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build a single document dict matching the canonical chunks schema.

    Chunk ID formula (v2): ``{deal_id}_{document_id}_{chunk_index}``
    Previous (v1) used ``{deal_id}_{doc_type}_{chunk_index}`` which caused
    collisions when two documents of the same doc_type belonged to one deal.
    The ``document_id`` discriminator is the DealDocument PK — always unique.
    If ``document_id`` is not available (backward compat), falls back to
    ``{deal_id}_{doc_type}_{chunk_index}``.
    """
    if document_id is not None:
        doc_id = _safe_id(f"{deal_id}_{document_id}_{chunk_index}")
    else:
        doc_id = _safe_id(f"{deal_id}_{doc_type}_{chunk_index}")
    now = datetime.now(UTC).isoformat()
    doc: dict[str, Any] = {
        "@search.action": "mergeOrUpload",
        "id": doc_id,
        "fund_id": str(fund_id),
        "deal_id": str(deal_id),
        "domain": domain,
        "doc_type": doc_type,
        "authority": authority or "",
        "title": title,
        "content": content,
        "embedding": embedding,
        "page_start": page_start,
        "page_end": page_end,
        "chunk_index": chunk_index,
        "created_at": now,
        "last_modified": now,
    }
    # ── Fields previously accepted but silently dropped (bug fix) ────
    if container_name:
        doc["container_name"] = container_name
    if blob_name:
        doc["blob_name"] = blob_name
    # ── Document Intelligence enrichment fields ─────────────────────
    if doc_summary:
        doc["doc_summary"] = doc_summary
    if doc_metadata:
        doc["doc_metadata"] = doc_metadata

    # ── Hybrid pipeline enrichment fields ────────────────────────────
    # Only include non-None fields (Azure Search ignores absent fields).
    if vehicle_type is not None:
        doc["vehicle_type"] = vehicle_type
    if section_type is not None:
        doc["section_type"] = section_type
    if breadcrumb is not None:
        doc["breadcrumb"] = breadcrumb
    if has_table is not None:
        doc["has_table"] = has_table
    if has_numbers is not None:
        doc["has_numbers"] = has_numbers
    if char_count is not None:
        doc["char_count"] = char_count
    if governance_critical is not None:
        doc["governance_critical"] = governance_critical
    if governance_flags is not None:
        doc["governance_flags"] = governance_flags
    if borrower_sector is not None:
        doc["borrower_sector"] = borrower_sector
    if loan_structure is not None:
        doc["loan_structure"] = loan_structure
    if key_persons_mentioned is not None:
        doc["key_persons_mentioned"] = key_persons_mentioned
    if financial_metric_type is not None:
        doc["financial_metric_type"] = financial_metric_type
    if risk_flags is not None:
        doc["risk_flags"] = risk_flags

    # ── Tenant isolation (Security F4) ──────────────────────────────
    # filterable=True, retrievable=False in the Azure Search schema.
    # All RAG queries MUST include $filter=organization_id eq '{org_id}'.
    if organization_id is not None:
        doc["organization_id"] = str(organization_id)

    # ── Extraction quality / degraded marker (FAIL-02) ────────────
    # Downstream indexing can filter on ``extraction_degraded`` to exclude
    # degraded outputs or include them with an explicit marker.
    if extraction_degraded is not None:
        doc["extraction_degraded"] = extraction_degraded
    if extraction_quality is not None:
        doc["extraction_quality"] = json.dumps(extraction_quality)

    return doc


def upsert_chunks(documents: list[dict[str, Any]]) -> UpsertResult:
    """Upsert a list of search documents into the canonical chunks index.

    Returns an ``UpsertResult`` with attempted/successful/failed counts so
    callers can distinguish full success from partial (degraded) persistence.
    Validates that all chunk IDs within the batch are unique before uploading.
    """
    if not documents:
        return UpsertResult(
            attempted_chunk_count=0,
            successful_chunk_count=0,
            failed_chunk_count=0,
            retryable=False,
        )

    # ── Duplicate ID guard ────────────────────────────────────────────
    ids = [d["id"] for d in documents]
    seen: set[str] = set()
    duplicates: list[str] = []
    for doc_id in ids:
        if doc_id in seen:
            duplicates.append(doc_id)
        seen.add(doc_id)
    if duplicates:
        logger.error(
            "Duplicate chunk IDs detected — aborting upsert to prevent silent overwrites: %s",
            duplicates[:10],
        )
        raise RuntimeError(
            f"Duplicate chunk IDs in batch ({len(duplicates)} collisions). "
            f"First: {duplicates[0]}. Ensure document_id is passed to build_search_document(). "
            f"Chunk ID format must be {{deal_id}}_{{document_id}}_{{chunk_index}}.",
        )

    from app.services.azure.search_client import get_search_client

    index_name = _chunks_index_name()
    client = get_search_client(index_name=index_name)
    total_uploaded = 0
    total_failed = 0
    batch_errors: list[str] = []
    has_transient_error = False

    for i in range(0, len(documents), _UPLOAD_BATCH_SIZE):
        batch = documents[i : i + _UPLOAD_BATCH_SIZE]
        try:
            result = client.upload_documents(documents=batch)
            succeeded = sum(1 for r in result if r.succeeded)
            failed = len(batch) - succeeded
            total_uploaded += succeeded
            total_failed += failed
            if failed > 0:
                logger.warning(
                    "Search upsert batch %d: %d succeeded, %d failed",
                    i // _UPLOAD_BATCH_SIZE,
                    succeeded,
                    failed,
                )
                batch_errors.append(
                    f"batch {i // _UPLOAD_BATCH_SIZE}: {failed}/{len(batch)} chunks failed"
                )
                # Partial batch failures are retryable (individual doc issues)
                has_transient_error = True
        except Exception as exc:
            logger.error(
                "Search upsert batch %d failed entirely (%d docs)",
                i // _UPLOAD_BATCH_SIZE,
                len(batch),
                exc_info=True,
            )
            total_failed += len(batch)
            batch_errors.append(
                f"batch {i // _UPLOAD_BATCH_SIZE}: entire batch of {len(batch)} failed — {type(exc).__name__}"
            )
            # Entire batch exception is typically transient (network, throttle)
            has_transient_error = True

    logger.info("Upserted %d/%d chunks to %s", total_uploaded, len(documents), index_name)
    return UpsertResult(
        attempted_chunk_count=len(documents),
        successful_chunk_count=total_uploaded,
        failed_chunk_count=total_failed,
        retryable=has_transient_error,
        batch_errors=batch_errors,
    )


def search_deal_chunks(
    *,
    deal_id: uuid.UUID,
    organization_id: uuid.UUID | str,
    query_text: str | None = None,
    query_vector: list[float] | None = None,
    top: int = 20,
    domain_filter: str | None = None,
) -> list[dict[str, Any]]:
    """Hybrid search (BM25 + vector) for chunks belonging to a deal.

    Supports optional domain filtering for cross-domain regulatory references.
    All queries include organization_id for tenant isolation (Security F2/F5).
    """
    from typing import cast

    from azure.search.documents.models import VectorizedQuery, VectorQuery

    from app.services.azure.search_client import get_search_client

    client = get_search_client(index_name=_chunks_index_name())

    safe_deal = validate_uuid(deal_id, "deal_id")
    safe_org = validate_uuid(organization_id, "organization_id")
    filter_expr = f"deal_id eq '{safe_deal}' and organization_id eq '{safe_org}'"
    if domain_filter:
        safe_domain = validate_domain(domain_filter)
        filter_expr = f"({filter_expr}) and (domain eq '{safe_domain}')"

    vector_queries: list[VectorQuery] | None = None
    if query_vector:
        vector_queries = cast(
            list[VectorQuery],
            [
                VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=top,
                    fields="embedding",
                ),
            ],
        )

    results = client.search(
        search_text=query_text or "*",
        filter=filter_expr,
        vector_queries=vector_queries,
        top=top,
        select=["id", "deal_id", "domain", "doc_type", "title", "content", "page_start", "page_end", "chunk_index"],
    )

    return [dict(r) for r in results]


def search_fund_policy_chunks(
    *,
    fund_id: uuid.UUID,
    organization_id: uuid.UUID | str,
    query_text: str | None = None,
    query_vector: list[float] | None = None,
    top: int = 30,
    domain_filter: str = "POLICY",
) -> list[dict[str, Any]]:
    """Search for fund-level policy / governance / regulatory chunks.

    Fund-level documents are indexed with a nil-UUID deal_id
    (00000000-0000-0000-0000-000000000000).  This function filters by
    fund_id + domain rather than by deal_id.

    All queries include organization_id for tenant isolation (Security F2/F5).
    Used by Deep Review v3 Stage 4 (policy compliance).
    """
    from typing import cast

    from azure.search.documents.models import VectorizedQuery, VectorQuery

    from app.services.azure.search_client import get_search_client

    client = get_search_client(index_name=_chunks_index_name())

    safe_fund = validate_uuid(fund_id, "fund_id")
    safe_org = validate_uuid(organization_id, "organization_id")
    safe_domain = validate_domain(domain_filter)
    filter_expr = f"fund_id eq '{safe_fund}' and organization_id eq '{safe_org}' and domain eq '{safe_domain}'"

    vector_queries: list[VectorQuery] | None = None
    if query_vector:
        vector_queries = cast(
            list[VectorQuery],
            [
                VectorizedQuery(
                    vector=query_vector,
                    k_nearest_neighbors=top,
                    fields="embedding",
                ),
            ],
        )

    results = client.search(
        search_text=query_text or "*",
        filter=filter_expr,
        vector_queries=vector_queries,
        top=top,
        select=["id", "deal_id", "fund_id", "domain", "doc_type", "title", "content", "page_start", "page_end", "chunk_index"],
    )

    return [dict(r) for r in results]

"""Azure AI Search KB adapter for regulatory indexes.

Used by the global agent for regulatory/constitution/service-provider
retrieval.
"""
from __future__ import annotations

import logging
import uuid as _uuid

from ai_engine.extraction.kb_schema import ComplianceChunk
from ai_engine.extraction.pgvector_search_service import validate_domain, validate_uuid

logger = logging.getLogger(__name__)

# Map compliance domains to their Azure AI Search index names
FUND_DATA_CATEGORY_MAP: dict[str, str] = {
    "REGULATORY": "fund-data-index",
    "CONSTITUTION": "fund-data-index",
    "SERVICE_PROVIDER": "fund-data-index",
}


class AzureComplianceKBAdapter:
    """Retrieves chunks from compliance-domain Azure AI Search indexes."""

    @staticmethod
    def search_live(
        query: str,
        domain: str,
        organization_id: _uuid.UUID | str,
        top: int = 20,
    ) -> list[ComplianceChunk]:
        """Full-text search against the fund-data-index for a compliance domain.

        All queries include organization_id for tenant isolation (Security F2/F5).
        """
        from app.services.azure.search_client import get_search_client

        safe_org = validate_uuid(organization_id, "organization_id")
        safe_domain = validate_domain(domain) if domain else None
        org_filter = f"organization_id eq '{safe_org}'"
        if safe_domain:
            odata_filter = f"{org_filter} and category eq '{safe_domain}'"
        else:
            odata_filter = org_filter

        index_name = FUND_DATA_CATEGORY_MAP.get(domain, "fund-data-index")
        try:
            client = get_search_client(index_name=index_name)
            results = client.search(
                search_text=query,
                top=top,
                filter=odata_filter,
            )

            chunks = []
            for r in results:
                chunks.append(
                    ComplianceChunk(
                        chunk_id=r.get("id", "UNKNOWN"),
                        doc_id=r.get("parent_id") or r.get("id", "UNKNOWN"),
                        domain=domain,
                        doc_type=r.get("doc_type", "OTHER"),
                        source_blob=r.get("blob_name") or r.get("title", "unknown"),
                        chunk_text=r.get("content", ""),
                        obligation_candidate=False,
                        extraction_confidence=r.get("@search.score", 0.5),
                        search_score=r.get("@search.score"),
                        last_modified=r.get("last_modified"),
                    )
                )

            logger.info(
                "COMPLIANCE_KB query=%r domain=%s hits=%d",
                query[:80],
                domain,
                len(chunks),
            )
            return chunks

        except Exception as exc:
            logger.warning(
                "SEARCH_INDEX_UNAVAILABLE: compliance search degraded, "
                "RAG query returned empty results. domain=%s error=%s: %s",
                domain,
                type(exc).__name__,
                exc,
            )
            return []

    @staticmethod
    def fetch_live(
        domain: str,
        organization_id: _uuid.UUID | str,
        top: int = 50,
    ) -> list[ComplianceChunk]:
        """Fetch chunks for a domain using a broad wildcard query."""
        return AzureComplianceKBAdapter.search_live(
            query="*", domain=domain, organization_id=organization_id, top=top,
        )

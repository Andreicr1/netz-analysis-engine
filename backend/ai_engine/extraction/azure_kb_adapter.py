"""Azure AI Search KB adapter for compliance/regulatory indexes.

Relocated from app.domains.credit.compliance.kb.azure_kb_adapter
after the compliance domain was removed from scope. This adapter
is used by the global agent for regulatory/constitution/service-provider
retrieval.
"""
from __future__ import annotations

import logging

from ai_engine.extraction.kb_schema import ComplianceChunk

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
        top: int = 20,
    ) -> list[ComplianceChunk]:
        """Full-text search against the fund-data-index for a compliance domain."""
        from app.services.azure.search_client import get_search_client

        index_name = FUND_DATA_CATEGORY_MAP.get(domain, "fund-data-index")
        try:
            client = get_search_client(index_name=index_name)
            results = client.search(
                search_text=query,
                top=top,
                filter=f"category eq '{domain}'" if domain else None,
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
            logger.error(
                "COMPLIANCE_KB search_live failed domain=%s: %s: %s",
                domain,
                type(exc).__name__,
                exc,
            )
            return []

    @staticmethod
    def fetch_live(
        domain: str,
        top: int = 50,
    ) -> list[ComplianceChunk]:
        """Fetch chunks for a domain using a broad wildcard query."""
        return AzureComplianceKBAdapter.search_live(
            query="*", domain=domain, top=top,
        )

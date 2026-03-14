"""
Azure AI Search adapter for the global-vector-chunks-v4 index.
Mirrors AzureComplianceKBAdapter but targets the pipeline deal chunks index.
"""
from __future__ import annotations

import logging
import re

from app.domains.credit.compliance.ingest.compliance_kb_schema import ComplianceChunk, DocType

logger = logging.getLogger(__name__)

PIPELINE_INDEX: str = "global-vector-chunks-v4"
PIPELINE_DOMAIN: str = "PIPELINE"

# Pre-compute the set of accepted DocType values for fast lookup
_VALID_DOC_TYPES: set[str] = set(DocType.__args__)  # type: ignore[attr-defined]

# Patterns that indicate the user wants a broad overview (all deals),
# not a specific deal search. In these cases we do a wildcard search
# grouped by deal_folder to get diverse coverage.
_OVERVIEW_PATTERNS = re.compile(
    r"(pipeline|todos os deals|all deals|overview|visão geral|carteira"
    r"|portf[oó]lio.*completo|quantos deals|how many deals"
    r"|resumo.*fundo|fund summary|pipeline.*atual|current.*pipeline)",
    re.IGNORECASE,
)


class PipelineKBAdapter:
    """
    Retrieves chunks from global-vector-chunks-v4 in Azure AI Search.
    Results are mapped to ComplianceChunk so the global agent can merge
    pipeline evidence with compliance evidence seamlessly.
    """

    @staticmethod
    def search_live(
        query: str,
        deal_folder: str | None = None,
        top: int = 20,
    ) -> list[ComplianceChunk]:
        """
        Full-text search against global-vector-chunks-v4.

        For overview questions (pipeline summary, all deals, etc.), performs
        a broad wildcard search and ensures diverse deal coverage by
        selecting top chunks from each unique deal_folder.

        Parameters
        ----------
        query : str
            Natural-language search query.
        deal_folder : str | None
            If provided, scopes retrieval to a specific deal via OData filter.
        top : int
            Maximum number of results.

        Returns
        -------
        list[ComplianceChunk]
            Sorted by search_score descending.
        """
        from app.services.azure.search_client import get_search_client

        is_overview = not deal_folder and bool(_OVERVIEW_PATTERNS.search(query))

        try:
            client = get_search_client(index_name=PIPELINE_INDEX)

            odata_filter: str | None = None
            if deal_folder:
                odata_filter = f"deal_folder eq '{deal_folder}'"

            if is_overview:
                # For overview queries: fetch more results with wildcard to
                # ensure we cover all deals, then diversify per deal_folder
                chunks = _overview_search(client, query, top)
            else:
                chunks = _standard_search(client, query, top, odata_filter)

            logger.info(
                "PIPELINE_KB query=%r deal_folder=%s is_overview=%s hits=%d",
                query[:80],
                deal_folder,
                is_overview,
                len(chunks),
            )
            return chunks

        except Exception as exc:
            logger.error(
                "PIPELINE_KB search_live failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            return []


def _standard_search(
    client, query: str, top: int, odata_filter: str | None
) -> list[ComplianceChunk]:
    """Normal targeted search."""
    results = client.search(
        search_text=query,
        top=top,
        filter=odata_filter,
    )
    return [_to_chunk(r) for r in results]


def _overview_search(client, query: str, top: int) -> list[ComplianceChunk]:
    """
    Broad search that ensures coverage of all deals in the index.

    Strategy: fetch a large result set with a generic query, then
    pick the best chunks from each unique deal_folder to ensure
    the LLM sees all deals — not just the top-scoring ones.
    """
    # Fetch more than needed so we can diversify
    fetch_size = max(top * 5, 100)

    # Use both the user query AND a broad wildcard to maximize coverage
    results_query = list(client.search(
        search_text=query,
        top=fetch_size,
        select=["id", "parent_id", "blob_name", "title", "content",
                "doc_type", "deal_folder", "deal_id", "last_modified"],
    ))

    # Also fetch wildcard results to find deals that don't match the query text
    results_wildcard = list(client.search(
        search_text="*",
        top=fetch_size,
        select=["id", "parent_id", "blob_name", "title", "content",
                "doc_type", "deal_folder", "deal_id", "last_modified"],
    ))

    # Merge and deduplicate by chunk id
    seen_ids: set[str] = set()
    all_results = []
    for r in results_query + results_wildcard:
        rid = r.get("id", "")
        if rid not in seen_ids:
            seen_ids.add(rid)
            all_results.append(r)

    # Group by deal_folder
    by_deal: dict[str, list] = {}
    for r in all_results:
        folder = r.get("deal_folder") or r.get("deal_id") or "unknown"
        by_deal.setdefault(folder, []).append(r)

    # Pick top chunks per deal, distributing evenly
    num_deals = len(by_deal)
    if num_deals == 0:
        return []

    chunks_per_deal = max(2, top // num_deals)
    selected: list[ComplianceChunk] = []

    for folder, results in sorted(by_deal.items()):
        # Sort each deal's chunks by score descending
        results.sort(key=lambda r: r.get("@search.score", 0), reverse=True)
        for r in results[:chunks_per_deal]:
            selected.append(_to_chunk(r))

    # Sort all selected by score, cap at top
    selected.sort(key=lambda c: c.search_score or 0.0, reverse=True)

    logger.info(
        "PIPELINE_KB overview_search deals_found=%d chunks_selected=%d",
        num_deals,
        len(selected),
    )
    return selected[:top]


def _to_chunk(r: dict) -> ComplianceChunk:
    """Convert a search result dict to a ComplianceChunk."""
    raw_doc_type = r.get("doc_type") or "OTHER"
    safe_doc_type = raw_doc_type if raw_doc_type in _VALID_DOC_TYPES else "OTHER"

    return ComplianceChunk(
        chunk_id=r.get("id", "UNKNOWN"),
        doc_id=r.get("parent_id") or r.get("id") or "UNKNOWN",
        domain=PIPELINE_DOMAIN,
        doc_type=safe_doc_type,
        source_blob=r.get("blob_name") or r.get("title", "unknown"),
        chunk_text=r.get("content", ""),
        obligation_candidate=False,
        extraction_confidence=r.get("@search.score", 0.5),
        search_score=r.get("@search.score"),
        last_modified=r.get("last_modified"),
    )

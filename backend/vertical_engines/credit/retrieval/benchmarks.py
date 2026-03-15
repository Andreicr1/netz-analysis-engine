"""Market benchmark retrieval from market-data-index.

Retrieves structured benchmark data from the market-data-index, which is
populated by the market-data pipeline. Used to ground ch08 (Return Modeling)
and ch12 (Peer Comparison) with authoritative third-party benchmark data
(PitchBook, Preqin, Bloomberg).

Error contract: never-raises. Returns empty list on failure.
"""
from __future__ import annotations

from typing import Any

import structlog

from vertical_engines.credit.retrieval.models import CHAPTER_MARKET_DATA_QUERIES

logger = structlog.get_logger()


def retrieve_market_benchmarks(
    chapter_id: str,
    *,
    search_endpoint: str,
    search_api_key: str = "",
    asset_class_filter: str | None = None,
    top_k: int = 15,
    source_type_filter: str = "BENCHMARK",
) -> list[dict[str, Any]]:
    """Retrieve market benchmark chunks from market-data-index for a given chapter.

    Parameters
    ----------
    chapter_id : str
        One of the keys in CHAPTER_MARKET_DATA_QUERIES (e.g. "ch08_returns").
    search_endpoint : str
        Full Azure AI Search endpoint URL.
    search_api_key : str
        Azure AI Search admin or query key.
    asset_class_filter : str | None
        Optional OData filter value for the ``asset_class`` field.
    top_k : int
        Total chunks to return across all queries for this chapter.
    source_type_filter : str
        OData filter value for the ``source_type`` field (default "BENCHMARK").

    Returns
    -------
    list[dict]
        List of raw search result dicts from market-data-index.
        Returns [] if chapter_id is unknown or search fails.

    """
    import httpx as _httpx

    queries = CHAPTER_MARKET_DATA_QUERIES.get(chapter_id, [])
    if not queries:
        logger.warning(
            "retrieve_market_benchmarks_no_queries",
            chapter=chapter_id,
        )
        return []

    index_name = "market-data-index"
    url = (
        f"{search_endpoint.rstrip('/')}/indexes/{index_name}"
        f"/docs/search?api-version=2024-05-01-preview"
    )

    # Build OData filter
    filter_parts = [f"source_type eq '{source_type_filter}'"]
    if asset_class_filter:
        filter_parts.append(f"asset_class eq '{asset_class_filter}'")
    odata_filter = " and ".join(filter_parts)

    per_query_top = max(3, top_k // len(queries))
    seen_ids: set[str] = set()
    results: list[dict[str, Any]] = []

    # Resolve auth headers once before the query loop
    if search_api_key:
        _auth_headers: dict[str, str] = {
            "Content-Type": "application/json",
            "api-key": search_api_key,
        }
    else:
        try:
            from azure.identity import DefaultAzureCredential as _DAC
            _token = _DAC().get_token("https://search.azure.com/.default")
            _auth_headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {_token.token}",
            }
        except Exception as _auth_exc:
            logger.warning(
                "retrieve_market_benchmarks_aad_auth_failed",
                chapter=chapter_id,
                error=str(_auth_exc),
            )
            return []

    for query in queries:
        if len(results) >= top_k:
            break
        body: dict[str, Any] = {
            "search": query,
            "queryType": "semantic",
            "semanticConfiguration": "market-semantic",
            "top": per_query_top,
            "filter": odata_filter,
            "select": (
                "chunk_id,content,blob_name,doc_type,"
                "source_type,publisher,reference_date,"
                "asset_class,sub_strategy,vintage_year,metric_type,geography"
            ),
        }
        try:
            resp = _httpx.post(
                url,
                headers=_auth_headers,
                json=body,
                timeout=15.0,
            )
            resp.raise_for_status()
            for hit in resp.json().get("value", []):
                cid = hit.get("chunk_id") or hit.get("id", "")
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    results.append(hit)
                    if len(results) >= top_k:
                        break
        except Exception as exc:
            logger.warning(
                "retrieve_market_benchmarks_query_failed",
                chapter=chapter_id,
                error=str(exc),
            )

    logger.info(
        "market_benchmarks_retrieved",
        chapter=chapter_id,
        chunks=len(results),
    )
    return results[:top_k]

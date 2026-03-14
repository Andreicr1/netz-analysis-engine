from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.core.security.auth import Actor
from app.core.security.clerk_auth import get_actor, require_roles
from app.domains.credit.compliance.kb.azure_kb_adapter import (
    AZURE_INDEX_MAP,
    AzureComplianceKBAdapter,
)
from app.domains.credit.compliance.kb.kb_query import ComplianceKBQueryEngine, _azure_available
from app.domains.credit.compliance.kb.kb_store import ComplianceKBStore
from app.shared.enums import Role


def _resolve_index(domain: str | None) -> str:
    """Return the Azure index name(s) for the given domain, or 'local_store' in offline mode."""
    if not _azure_available():
        return "local_store"
    if domain and domain in AZURE_INDEX_MAP:
        return AZURE_INDEX_MAP[domain]["index"]
    return ", ".join(cfg["index"] for cfg in AZURE_INDEX_MAP.values())

router = APIRouter(prefix="/compliance/kb", tags=["compliance-kb"])

_query_engine = ComplianceKBQueryEngine()
_store = ComplianceKBStore()


@router.get("/chunks", summary="List KB chunks with optional domain/type filters")
def list_chunks(
    domain: str | None = None,
    doc_type: str | None = None,
    only_candidates: bool = False,
    limit: int = 50,
):
    """
    Returns compliance KB chunks.

    **Data source**: Azure AI Search indexes (direct) when `AZURE_SEARCH_ENDPOINT` is
    configured; falls back to `data/compliance/kb_chunks.json` in offline/dev mode.

    Filters:
    - **domain**: REGULATORY | CONSTITUTION | SERVICE_PROVIDER
    - **doc_type**: CIMA_HANDBOOK | CIMA_REGULATION | LPA | IMA | ENGAGEMENT_LETTER | …
    - **only_candidates**: if true, returns only obligation-candidate chunks
    - **limit**: max number of results (default 50)
    """
    chunks = _query_engine.list_chunks(
        domain=domain,
        doc_type=doc_type,
        only_candidates=only_candidates,
        limit=limit,
    )
    return {
        "source": "azure_search" if _azure_available() else "local_store",
        "index_used": _resolve_index(domain),
        "domain": domain,
        "count": len(chunks),
        "filters": {
            "doc_type": doc_type,
            "only_candidates": only_candidates,
        },
        "chunks": [c.model_dump() for c in chunks],
    }


@router.get("/search", summary="Full-text search across Azure compliance indexes")
def search_chunks(
    q: str,
    domain: str | None = None,
    limit: int = 20,
):
    """
    Full-text search across compliance knowledge-base indexes.

    **Data source**: Azure AI Search when `AZURE_SEARCH_ENDPOINT` is configured
    (all 3 indexes by default; scoped to one when *domain* is supplied).
    Falls back to in-memory keyword match in offline/dev mode.

    - **q**: search text
    - **domain**: optional scope — REGULATORY | CONSTITUTION | SERVICE_PROVIDER
    - **limit**: max results (default 20)
    """
    chunks = _query_engine.search(q, limit=limit, domain=domain)
    return {
        "query": q,
        "source": "azure_search" if _azure_available() else "local_store",
        "index_used": _resolve_index(domain),
        "domain": domain,
        "count": len(chunks),
        "chunks": [c.model_dump() for c in chunks],
    }


@router.post("/refresh", summary="Report primary data source and local fallback count")
def refresh_from_seed_store():
    """
    Reports the active data-source configuration.
    - When `AZURE_SEARCH_ENDPOINT` is set, `/chunks` and `/search` query Azure directly.
    - Local `kb_chunks.json` is the offline/dev fallback.
    """
    chunks = _store.load_chunks()
    return {
        "status": "ok",
        "primary_source": "azure_search" if _azure_available() else "local_store",
        "local_fallback_chunks": len(chunks),
        "note": "GET /chunks and GET /search route to Azure AI Search when AZURE_SEARCH_ENDPOINT is configured.",
    }


@router.post("/ingest", summary="Trigger compliance KB ingest pipeline")
def trigger_compliance_ingest(
    fund_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    actor: Actor = Depends(get_actor),
    _role_guard: Actor = Depends(require_roles([Role.ADMIN, Role.COMPLIANCE])),
):
    """Trigger the compliance knowledge-base ingest pipeline.

    Dispatches to Service Bus when USE_SERVICE_BUS=True, otherwise runs
    in-process via BackgroundTasks.
    """
    from app.services.azure.pipeline_dispatch import dispatch_compliance_ingest

    return dispatch_compliance_ingest(
        background_tasks=background_tasks,
        fund_id=fund_id,
        actor_id=actor.actor_id,
    )


@router.get(
    "/chunks/live",
    summary="[Deprecated] Direct Azure query — use GET /chunks instead",
    deprecated=True,
)
def list_chunks_live(domain: str, top: int = 20):
    """
    **Deprecated.** `GET /chunks` now queries Azure AI Search directly.
    This endpoint is kept for backward compatibility and will be removed in a future release.

    **domain** must be one of: `REGULATORY` | `CONSTITUTION` | `SERVICE_PROVIDER`
    """
    if domain not in AZURE_INDEX_MAP:
        valid = list(AZURE_INDEX_MAP.keys())
        raise HTTPException(
            status_code=422,
            detail=f"Invalid domain '{domain}'. Must be one of: {valid}",
        )

    try:
        chunks = AzureComplianceKBAdapter.fetch_live(domain=domain, top=top)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Azure Search error: {type(exc).__name__}: {exc}",
        )

    return {
        "domain": domain,
        "index": AZURE_INDEX_MAP[domain]["index"],
        "count": len(chunks),
        "chunks": [c.model_dump() for c in chunks],
    }

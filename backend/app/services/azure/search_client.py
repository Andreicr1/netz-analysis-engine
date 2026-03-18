from __future__ import annotations

from dataclasses import dataclass

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

from app.core.config import settings


@dataclass(frozen=True)
class SearchHealth:
    ok: bool
    detail: str | None = None


@dataclass(frozen=True)
class ChunksIndexContract:
    configured_base_name: str
    resolved_name: str
    env_name: str


def _search_credential():
    """Return AzureKeyCredential if AZURE_SEARCH_KEY is set, else DefaultAzureCredential."""
    if settings.azure_search_key:
        from azure.core.credentials import AzureKeyCredential
        return AzureKeyCredential(settings.azure_search_key)
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def resolve_chunks_index_name() -> str:
    """Return the canonical env-scoped chunks index name."""
    return settings.canonical_search_chunks_index_name()


def describe_chunks_index_contract() -> ChunksIndexContract:
    """Expose the runtime chunks-index contract for diagnostics and tests."""
    configured_base = settings.SEARCH_CHUNKS_INDEX_NAME or "global-vector-chunks-v2"
    return ChunksIndexContract(
        configured_base_name=configured_base,
        resolved_name=resolve_chunks_index_name(),
        env_name=settings.NETZ_ENV,
    )


def get_search_client(*, index_name: str) -> SearchClient:
    if not settings.azure_search_endpoint:
        raise ValueError("AZURE_SEARCH_ENDPOINT not configured")
    cred = _search_credential()
    return SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=index_name,
        credential=cred,
    )


def get_metadata_index_client() -> SearchClient:
    metadata_index_name = getattr(settings, "SEARCH_INDEX_NAME", "")
    if not metadata_index_name:
        raise ValueError("SEARCH_INDEX_NAME not configured")
    return get_search_client(index_name=metadata_index_name)


def get_chunks_index_client() -> SearchClient:
    if not settings.SEARCH_CHUNKS_INDEX_NAME:
        raise ValueError("SEARCH_CHUNKS_INDEX_NAME not configured")
    return get_search_client(index_name=resolve_chunks_index_name())


def health_check_search() -> SearchHealth:
    try:
        c = get_chunks_index_client()
        # Lightweight query; may return 0 docs but proves auth & endpoint.
        _ = list(c.search(search_text="*", top=1))
        return SearchHealth(ok=True)
    except Exception as e:
        msg = str(e) or repr(e)
        return SearchHealth(ok=False, detail=f"{type(e).__name__}: {msg}")

from __future__ import annotations

from dataclasses import dataclass

from azure.identity import DefaultAzureCredential
from azure.search.documents import SearchClient

from app.core.config import settings


@dataclass(frozen=True)
class SearchHealth:
    ok: bool
    detail: str | None = None


def _search_credential():
    """Return AzureKeyCredential if AZURE_SEARCH_KEY is set, else DefaultAzureCredential."""
    if settings.AZURE_SEARCH_KEY:
        from azure.core.credentials import AzureKeyCredential
        return AzureKeyCredential(settings.AZURE_SEARCH_KEY)
    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def get_search_client(*, index_name: str) -> SearchClient:
    if not settings.AZURE_SEARCH_ENDPOINT:
        raise ValueError("AZURE_SEARCH_ENDPOINT not configured")
    cred = _search_credential()
    return SearchClient(endpoint=settings.AZURE_SEARCH_ENDPOINT, index_name=index_name, credential=cred)


def get_metadata_index_client() -> SearchClient:
    if not settings.SEARCH_INDEX_NAME:
        raise ValueError("SEARCH_INDEX_NAME not configured")
    return get_search_client(index_name=settings.SEARCH_INDEX_NAME)


def get_chunks_index_client() -> SearchClient:
    if not settings.SEARCH_CHUNKS_INDEX_NAME:
        raise ValueError("SEARCH_CHUNKS_INDEX_NAME not configured")
    return get_search_client(index_name=settings.SEARCH_CHUNKS_INDEX_NAME)


def health_check_search() -> SearchHealth:
    try:
        c = get_chunks_index_client()
        # Lightweight query; may return 0 docs but proves auth & endpoint.
        _ = list(c.search(search_text="*", top=1))
        return SearchHealth(ok=True)
    except Exception as e:
        msg = str(e) or repr(e)
        return SearchHealth(ok=False, detail=f"{type(e).__name__}: {msg}")


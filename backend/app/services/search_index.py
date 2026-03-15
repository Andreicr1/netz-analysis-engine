"""Azure AI Search service — stub for Sprint 2b.

Real implementation connects to Azure AI Search. Populated in Sprint 3.
"""

from __future__ import annotations

from typing import Any


class AzureSearchMetadataClient:
    def upsert_dataroom_metadata(self, **kwargs: Any) -> None:
        raise NotImplementedError("Search index not configured — Sprint 3")


class AzureSearchChunksClient:
    def __init__(self, **kwargs: Any) -> None:
        pass

    def upsert(self, **kwargs: Any) -> None:
        raise NotImplementedError("Search index not configured — Sprint 3")


class RetrievalEmbeddingError(Exception):
    pass


class RetrievalExecutionError(Exception):
    pass


class RetrievalScopeError(Exception):
    pass


class InstitutionalSearchEngine:
    def __init__(self, **kwargs: Any) -> None:
        pass

    def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        raise NotImplementedError("Search index not configured — Sprint 3")

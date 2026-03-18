"""Azure AI Search metadata helpers for retained production metadata paths."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.services.azure.search_client import (
    get_metadata_index_client,
    get_search_client,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetadataSearchHit:
    id: str
    fund_id: str
    document_id: str | None
    title: str
    content: str
    doc_type: str
    version: str | None
    root_folder: str | None
    folder_path: str | None
    version_blob_path: str | None
    uploaded_at: str | None
    score: float | None = None


def _backend_client_label() -> str:
    return "api_key" if settings.azure_search_key else "default_credential"


def _escape_odata_literal(value: str) -> str:
    return value.replace("'", "''")


def _validate_uuid(value: str | uuid.UUID, field_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid UUID for {field_name}: {value!r}") from exc


def _normalize_upload_item(item: dict[str, Any]) -> dict[str, Any]:
    document = dict(item)
    document.setdefault("@search.action", "mergeOrUpload")
    return document


class AzureSearchMetadataClient:
    def __init__(
        self,
        *,
        caller: str = "unknown",
        index_name: str | None = None,
    ) -> None:
        self.caller = caller
        self.index_name = index_name or settings.SEARCH_INDEX_NAME

    def _client(self):
        if self.index_name and self.index_name != settings.SEARCH_INDEX_NAME:
            return get_search_client(index_name=self.index_name)
        return get_metadata_index_client()

    def upsert_documents(self, *, items: list[dict[str, Any]]) -> int:
        if not items:
            return 0

        client = self._client()
        documents = [_normalize_upload_item(item) for item in items]

        logger.info(
            "metadata_search.upsert.attempt caller=%s backend=%s index=%s items=%d",
            self.caller,
            _backend_client_label(),
            self.index_name,
            len(documents),
        )
        result = client.upload_documents(documents=documents)
        succeeded = sum(1 for row in result if getattr(row, "succeeded", False))
        failed = len(documents) - succeeded

        logger.info(
            "metadata_search.upsert.result caller=%s index=%s succeeded=%d failed=%d",
            self.caller,
            self.index_name,
            succeeded,
            failed,
        )
        if failed:
            logger.warning(
                "metadata_search.upsert.partial caller=%s index=%s failed=%d",
                self.caller,
                self.index_name,
                failed,
            )
        return succeeded

    def upsert_dataroom_metadata(self, *, items: list[dict[str, Any]]) -> int:
        return self.upsert_documents(items=items)

    def search(
        self,
        *,
        q: str,
        fund_id: str | uuid.UUID,
        top: int = 5,
        root_folder: str | None = None,
        organization_id: str | uuid.UUID | None = None,
        allow_cross_tenant: bool = False,
    ) -> list[MetadataSearchHit]:
        client = self._client()
        safe_fund_id = _validate_uuid(fund_id, "fund_id")
        filter_parts = [f"fund_id eq '{safe_fund_id}'"]

        if organization_id is not None:
            safe_org_id = _validate_uuid(organization_id, "organization_id")
            filter_parts.append(f"organization_id eq '{safe_org_id}'")
        elif not allow_cross_tenant:
            raise ValueError(
                "organization_id is required for tenant-scoped search. "
                "Pass allow_cross_tenant=True for admin/global queries."
            )
        if root_folder:
            filter_parts.append(
                f"root_folder eq '{_escape_odata_literal(root_folder)}'",
            )

        filter_expr = " and ".join(filter_parts)
        logger.info(
            "metadata_search.query caller=%s backend=%s index=%s top=%d",
            self.caller,
            _backend_client_label(),
            self.index_name,
            top,
        )
        results = client.search(
            search_text=q or "*",
            top=top,
            filter=filter_expr,
            select=[
                "id",
                "fund_id",
                "document_id",
                "title",
                "content",
                "doc_type",
                "version",
                "root_folder",
                "folder_path",
                "version_blob_path",
                "uploaded_at",
            ],
        )

        hits = [
            MetadataSearchHit(
                id=row.get("id", ""),
                fund_id=row.get("fund_id", ""),
                document_id=row.get("document_id"),
                title=row.get("title", ""),
                content=row.get("content", ""),
                doc_type=row.get("doc_type", ""),
                version=row.get("version"),
                root_folder=row.get("root_folder"),
                folder_path=row.get("folder_path"),
                version_blob_path=row.get("version_blob_path"),
                uploaded_at=row.get("uploaded_at"),
                score=row.get("@search.score"),
            )
            for row in results
        ]

        logger.info(
            "metadata_search.result caller=%s index=%s hits=%d",
            self.caller,
            self.index_name,
            len(hits),
        )
        return hits


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

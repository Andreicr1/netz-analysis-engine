# DEPRECATED 2026-03-18: Azure Blob Storage replaced by LocalStorageClient + StorageClient abstraction (Milestone 2).
# Retained for rollback capability only. Use StorageClient for all new storage operations.
from __future__ import annotations

import warnings
from dataclasses import dataclass

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from app.core.config import settings


@dataclass(frozen=True)
class StorageHealth:
    ok: bool
    detail: str | None = None


def get_blob_service_client() -> BlobServiceClient:
    warnings.warn(
        "blob_client.get_blob_service_client is deprecated — use StorageClient abstraction",
        DeprecationWarning,
        stacklevel=2,
    )
    if not settings.STORAGE_ACCOUNT_URL:
        raise ValueError("STORAGE_ACCOUNT_URL not configured")
    if settings.AZURE_STORAGE_ACCOUNT_KEY:
        cred = settings.AZURE_STORAGE_ACCOUNT_KEY
    else:
        cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return BlobServiceClient(account_url=settings.STORAGE_ACCOUNT_URL, credential=cred)


def health_check_storage() -> StorageHealth:
    warnings.warn(
        "blob_client.health_check_storage is deprecated — use StorageClient abstraction",
        DeprecationWarning,
        stacklevel=2,
    )
    try:
        svc = get_blob_service_client()
        # Validate containers are reachable (existence/permissions)
        for c in [
            settings.AZURE_STORAGE_DATAROOM_CONTAINER,
            settings.AZURE_STORAGE_EVIDENCE_CONTAINER,
            settings.AZURE_STORAGE_MONTHLY_REPORTS_CONTAINER,
        ]:
            svc.get_container_client(c).get_container_properties()
        return StorageHealth(ok=True)
    except Exception as e:
        return StorageHealth(ok=False, detail=str(e))

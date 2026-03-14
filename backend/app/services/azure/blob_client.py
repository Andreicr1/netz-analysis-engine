from __future__ import annotations

from dataclasses import dataclass

from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

from app.core.config import settings


@dataclass(frozen=True)
class StorageHealth:
    ok: bool
    detail: str | None = None


def get_blob_service_client() -> BlobServiceClient:
    if not settings.STORAGE_ACCOUNT_URL:
        raise ValueError("STORAGE_ACCOUNT_URL not configured")
    if settings.AZURE_STORAGE_ACCOUNT_KEY:
        cred = settings.AZURE_STORAGE_ACCOUNT_KEY
    else:
        cred = DefaultAzureCredential(exclude_interactive_browser_credential=True)
    return BlobServiceClient(account_url=settings.STORAGE_ACCOUNT_URL, credential=cred)


def health_check_storage() -> StorageHealth:
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


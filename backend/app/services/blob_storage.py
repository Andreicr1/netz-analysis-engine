"""Blob storage service — stub for Sprint 2b.

Real implementation uses Azure Blob Storage SDK. Populated in Sprint 3
when upload architecture is built. All functions raise NotImplementedError
until then.
"""

from __future__ import annotations

from typing import Any


class BlobEntry:
    """Stub for blob listing entries."""
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def upload_bytes_append_only(**kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def upload_bytes(**kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def upload_bytes_idempotent(**kwargs: Any) -> dict[str, Any]:
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def download_bytes(**kwargs: Any) -> bytes:
    """Download blob bytes via StorageClient (R2/Local/ADLS).

    Accepts ``blob_uri`` kwarg — the storage path to read.
    Bridges the legacy blob_storage API to the unified StorageClient.
    """
    import asyncio

    from app.services.storage_client import get_storage_client

    blob_uri_val: str = kwargs.get("blob_uri", "")
    if not blob_uri_val:
        raise ValueError("blob_uri is required")

    storage = get_storage_client()

    # Run async read in a new event loop if called from sync context
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, storage.read(blob_uri_val)).result()
    return asyncio.run(storage.read(blob_uri_val))


def generate_read_link(**kwargs: Any) -> str:
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def list_blobs(**kwargs: Any) -> list[dict[str, Any]]:
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def blob_uri(**kwargs: Any) -> str:
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def exists(**kwargs: Any) -> bool:
    raise NotImplementedError("Blob storage not configured — Sprint 3")

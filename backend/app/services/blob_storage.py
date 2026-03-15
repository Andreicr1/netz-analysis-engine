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
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def generate_read_link(**kwargs: Any) -> str:
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def list_blobs(**kwargs: Any) -> list[dict[str, Any]]:
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def blob_uri(**kwargs: Any) -> str:
    raise NotImplementedError("Blob storage not configured — Sprint 3")


def exists(**kwargs: Any) -> bool:
    raise NotImplementedError("Blob storage not configured — Sprint 3")

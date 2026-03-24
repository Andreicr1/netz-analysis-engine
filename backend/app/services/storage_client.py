"""StorageClient — unified abstraction over Cloudflare R2 and local filesystem.

All code that needs to read/write files in the data lake must use this
client.  Never call storage SDKs directly.

Backends (priority: R2 > Local):
  - **Cloudflare R2** (``FEATURE_R2_ENABLED=true``):
    S3-compatible object storage via boto3. Production default.
  - **Local filesystem** (default, flag false):
    Writes to ``{local_storage_root}/`` with the same path hierarchy.
    Default root: ``{project_root}/.data/lake/``.

Path convention (all backends):
  - ``{tier}/{organization_id}/{...}`` for tenant data (bronze, silver)
  - ``{tier}/_global/{...}`` for global data (gold/_global/fred_indicators/)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.core.config.settings import settings

logger = logging.getLogger(__name__)

# Matches safe path segments: alphanumeric start, then alphanumeric/dot/dash/underscore/space.
_SAFE_PATH_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._\- ]*$")


class StorageClient(ABC):
    """Abstract storage client interface."""

    @staticmethod
    def _validate_path(path: str) -> None:
        """Reject paths that could escape the storage root.

        Raises ``ValueError`` for:
        - paths containing ``..`` (directory traversal)
        - absolute paths (start with ``/`` or a Windows drive letter)
        - empty paths
        - null bytes
        """
        if not path:
            raise ValueError("Storage path must not be empty")
        if "\x00" in path:
            raise ValueError("Storage path must not contain null bytes")
        if ".." in path.split("/"):
            raise ValueError(f"Path traversal detected: {path}")
        if path.startswith("/") or path.startswith("\\"):
            raise ValueError(f"Absolute paths are not allowed: {path}")
        # Windows drive letter detection (e.g. C:\)
        if len(path) >= 2 and path[1] == ":":
            raise ValueError(f"Absolute paths are not allowed: {path}")

    @abstractmethod
    async def write(self, path: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        """Write bytes to storage.  Returns the full path written."""

    @abstractmethod
    async def read(self, path: str) -> bytes:
        """Read bytes from storage.  Raises FileNotFoundError if missing."""

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if a path exists in storage."""

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete a file from storage.  No-op if missing."""

    @abstractmethod
    async def list_files(self, prefix: str) -> list[str]:
        """List file paths under a prefix."""

    @abstractmethod
    async def generate_read_url(self, path: str, *, expires_in: int = 3600) -> str:
        """Generate a time-limited read URL (presigned for R2, file:// for local)."""

    @abstractmethod
    async def generate_upload_url(self, path: str, *, expires_in: int = 3600) -> str:
        """Generate a time-limited upload URL (presigned for R2, file:// for local)."""

    def get_duckdb_path(
        self,
        tier: Literal["bronze", "silver", "gold"],
        org_id: UUID,
        vertical: str,
    ) -> str:
        """Return a path readable by DuckDB for a tenant's data tier.

        Concrete method with NotImplementedError default — avoids breaking
        existing mocks and test doubles. Subclasses override.

        LocalStorageClient  → filesystem path (.data/lake/{tier}/{org_id}/{vertical}/)
        R2StorageClient     → s3://{bucket}/{tier}/{org_id}/{vertical}/
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support DuckDB path resolution"
        )


class LocalStorageClient(StorageClient):
    """Local filesystem backend for development.

    Mirrors R2 path hierarchy on disk so code under test uses
    the same path conventions as production.

    .. note::
        Methods use sync ``pathlib.Path`` operations inside ``async def``.
        This is tolerable for local dev where I/O is fast and there is no
        concurrent load.  If this backend is ever used in production,
        wrap calls with ``asyncio.to_thread`` as done in ``R2StorageClient``.
    """

    def __init__(self, root: str | Path | None = None) -> None:
        if root:
            self._root = Path(root).resolve()
        elif settings.local_storage_root:
            self._root = Path(settings.local_storage_root).resolve()
        else:
            # Default: {project_root}/.data/lake/
            self._root = Path(__file__).resolve().parents[3] / ".data" / "lake"
        self._root.mkdir(parents=True, exist_ok=True)
        logger.info("LocalStorageClient initialized", extra={"root": str(self._root)})

    def _resolve(self, path: str) -> Path:
        """Resolve a storage path to an absolute filesystem path."""
        resolved = (self._root / path).resolve()
        # Prevent path traversal
        if not str(resolved).startswith(str(self._root)):
            raise ValueError(f"Path traversal detected: {path}")
        return resolved

    async def write(self, path: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return path

    async def read(self, path: str) -> bytes:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"Storage path not found: {path}")
        return target.read_bytes()

    async def exists(self, path: str) -> bool:
        return self._resolve(path).exists()

    async def delete(self, path: str) -> None:
        target = self._resolve(path)
        if target.exists():
            target.unlink()

    async def list_files(self, prefix: str) -> list[str]:
        base = self._resolve(prefix)
        if not base.exists():
            return []
        files: list[str] = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                files.append(str(p.relative_to(self._root)).replace(os.sep, "/"))
        return files

    async def generate_read_url(self, path: str, *, expires_in: int = 3600) -> str:
        target = self._resolve(path)
        return target.as_uri()

    async def generate_upload_url(self, path: str, *, expires_in: int = 3600) -> str:
        # For local dev, just return the file path — upload writes directly.
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target.as_uri()

    def get_duckdb_path(self, tier: Literal["bronze", "silver", "gold"], org_id: UUID, vertical: str) -> str:
        from ai_engine.pipeline.storage_routing import _validate_segment, _validate_vertical

        _validate_segment(str(org_id), "org_id")
        _validate_vertical(vertical)
        _validate_segment(tier, "tier")
        resolved = self._resolve(f"{tier}/{org_id}/{vertical}")
        return str(resolved).replace("\\", "/") + "/"


class R2StorageClient(StorageClient):
    """Cloudflare R2 backend (S3-compatible).

    Uses ``boto3`` with custom endpoint URL pointing to R2.
    Presigned URLs use the same S3 signing mechanism.
    """

    def __init__(self) -> None:
        if not settings.r2_account_id:
            raise RuntimeError("R2_ACCOUNT_ID must be set when FEATURE_R2_ENABLED=true")
        if not settings.r2_access_key_id or not settings.r2_secret_access_key:
            raise RuntimeError("R2 credentials must be set when FEATURE_R2_ENABLED=true")

        import boto3

        endpoint = settings.r2_endpoint_url or f"https://{settings.r2_account_id}.r2.cloudflarestorage.com"
        self._bucket_name = settings.r2_bucket_name
        self._s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
        )
        logger.info(
            "R2StorageClient initialized",
            extra={"bucket": self._bucket_name, "endpoint": endpoint},
        )

    async def write(self, path: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        self._validate_path(path)
        await asyncio.to_thread(
            self._s3.put_object,
            Bucket=self._bucket_name,
            Key=path,
            Body=data,
            ContentType=content_type,
        )
        return path

    async def read(self, path: str) -> bytes:
        self._validate_path(path)
        try:
            resp = await asyncio.to_thread(
                self._s3.get_object, Bucket=self._bucket_name, Key=path,
            )
            return await asyncio.to_thread(resp["Body"].read)
        except self._s3.exceptions.NoSuchKey:
            raise FileNotFoundError(f"Storage path not found: {path}")

    async def exists(self, path: str) -> bool:
        self._validate_path(path)
        try:
            await asyncio.to_thread(
                self._s3.head_object, Bucket=self._bucket_name, Key=path,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            from botocore.exceptions import ClientError
            if isinstance(exc, ClientError) and exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            logger.warning("storage_exists_error", extra={"path": path, "error": str(exc)})
            return False

    async def delete(self, path: str) -> None:
        self._validate_path(path)
        try:
            await asyncio.to_thread(
                self._s3.delete_object, Bucket=self._bucket_name, Key=path,
            )
        except Exception as exc:  # noqa: BLE001
            from botocore.exceptions import ClientError
            if isinstance(exc, ClientError) and exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return
            logger.warning("storage_delete_error", extra={"path": path, "error": str(exc)})

    async def list_files(self, prefix: str) -> list[str]:
        self._validate_path(prefix)
        paginator = self._s3.get_paginator("list_objects_v2")
        files: list[str] = []
        for page in paginator.paginate(Bucket=self._bucket_name, Prefix=prefix):
            for obj in page.get("Contents", []):
                files.append(obj["Key"])
        return sorted(files)

    async def generate_read_url(self, path: str, *, expires_in: int = 3600) -> str:
        self._validate_path(path)
        url: str = await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "get_object",
            Params={"Bucket": self._bucket_name, "Key": path},
            ExpiresIn=expires_in,
        )
        return url

    async def generate_upload_url(self, path: str, *, expires_in: int = 3600) -> str:
        self._validate_path(path)
        url: str = await asyncio.to_thread(
            self._s3.generate_presigned_url,
            "put_object",
            Params={"Bucket": self._bucket_name, "Key": path},
            ExpiresIn=expires_in,
        )
        return url

    def get_duckdb_path(self, tier: Literal["bronze", "silver", "gold"], org_id: UUID, vertical: str) -> str:
        from ai_engine.pipeline.storage_routing import _validate_segment, _validate_vertical

        _validate_segment(str(org_id), "org_id")
        _validate_vertical(vertical)
        _validate_segment(tier, "tier")
        return f"s3://{self._bucket_name}/{tier}/{org_id}/{vertical}/"


def create_storage_client() -> StorageClient:
    """Factory — returns the correct backend based on feature flags.

    Priority: R2 > LocalStorage.
    """
    if settings.feature_r2_enabled:
        return R2StorageClient()
    return LocalStorageClient()


# Singleton instance — created lazily on first access.
_client: StorageClient | None = None


def get_storage_client() -> StorageClient:
    """FastAPI dependency and general accessor for the storage client.

    Usage in routes::

        @router.post("/upload")
        async def upload(storage: StorageClient = Depends(get_storage_client)):
            await storage.write("bronze/org123/file.pdf", data)

    Usage in workers::

        from app.services.storage_client import get_storage_client
        storage = get_storage_client()
        await storage.write(...)
    """
    global _client  # noqa: PLW0603
    if _client is None:
        _client = create_storage_client()
    return _client

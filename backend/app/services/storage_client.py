"""StorageClient — unified abstraction over ADLS Gen2 and local filesystem.

All code that needs to read/write files in the data lake must use this
client.  Never call ADLS SDK directly.

Backends:
  - **Local filesystem** (default, ``FEATURE_ADLS_ENABLED=false``):
    Writes to ``{local_storage_root}/`` with the same path hierarchy as ADLS.
    Default root: ``{project_root}/.data/lake/``.
  - **ADLS Gen2** (``FEATURE_ADLS_ENABLED=true``):
    Writes to Azure Data Lake Storage Gen2 container.

Path convention (both backends):
  - ``{tier}/{organization_id}/{...}`` for tenant data (bronze, silver)
  - ``{tier}/_global/{...}`` for global data (gold/_global/fred_indicators/)
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path

from app.core.config.settings import settings

logger = logging.getLogger(__name__)


class StorageClient(ABC):
    """Abstract storage client interface."""

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
        """Generate a time-limited read URL (SAS for ADLS, file:// for local)."""

    @abstractmethod
    async def generate_upload_url(self, path: str, *, expires_in: int = 3600) -> str:
        """Generate a time-limited upload URL (SAS for ADLS, file:// for local)."""


class LocalStorageClient(StorageClient):
    """Local filesystem backend for development.

    Mirrors ADLS path hierarchy on disk so code under test uses
    the same path conventions as production.
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


class ADLSStorageClient(StorageClient):
    """Azure Data Lake Storage Gen2 backend.

    Uses ``azure-storage-file-datalake`` SDK.  Imported lazily to avoid
    pulling Azure SDK in development environments.
    """

    def __init__(self) -> None:
        if not settings.adls_account_name:
            raise RuntimeError("ADLS_ACCOUNT_NAME must be set when FEATURE_ADLS_ENABLED=true")

        # Lazy import — Azure SDK not required in dev
        from azure.storage.filedatalake import DataLakeServiceClient

        if settings.adls_connection_string:
            self._service = DataLakeServiceClient.from_connection_string(settings.adls_connection_string)
        else:
            self._service = DataLakeServiceClient(
                account_url=f"https://{settings.adls_account_name}.dfs.core.windows.net",
                credential=settings.adls_account_key or None,
            )
        self._fs = self._service.get_file_system_client(settings.adls_container_name)
        logger.info(
            "ADLSStorageClient initialized",
            extra={"account": settings.adls_account_name, "container": settings.adls_container_name},
        )

    async def write(self, path: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        file_client = self._fs.get_file_client(path)
        file_client.upload_data(data, overwrite=True, content_settings={"content_type": content_type})
        return path

    async def read(self, path: str) -> bytes:
        file_client = self._fs.get_file_client(path)
        download = file_client.download_file()
        return download.readall()

    async def exists(self, path: str) -> bool:
        file_client = self._fs.get_file_client(path)
        try:
            file_client.get_file_properties()
            return True
        except Exception:  # noqa: BLE001
            return False

    async def delete(self, path: str) -> None:
        file_client = self._fs.get_file_client(path)
        try:
            file_client.delete_file()
        except Exception:  # noqa: BLE001
            pass

    async def list_files(self, prefix: str) -> list[str]:
        paths = self._fs.get_paths(path=prefix)
        return [p.name for p in paths if not p.is_directory]

    async def generate_read_url(self, path: str, *, expires_in: int = 3600) -> str:
        from datetime import datetime, timedelta, timezone

        from azure.storage.filedatalake import generate_file_sas
        from azure.storage.filedatalake._models import FileSasPermissions

        sas = generate_file_sas(
            account_name=settings.adls_account_name,
            file_system_name=settings.adls_container_name,
            file_path=path,
            credential=settings.adls_account_key,
            permission=FileSasPermissions(read=True),
            expiry=datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in),
        )
        return f"https://{settings.adls_account_name}.dfs.core.windows.net/{settings.adls_container_name}/{path}?{sas}"

    async def generate_upload_url(self, path: str, *, expires_in: int = 3600) -> str:
        from datetime import datetime, timedelta, timezone

        from azure.storage.filedatalake import generate_file_sas
        from azure.storage.filedatalake._models import FileSasPermissions

        sas = generate_file_sas(
            account_name=settings.adls_account_name,
            file_system_name=settings.adls_container_name,
            file_path=path,
            credential=settings.adls_account_key,
            permission=FileSasPermissions(write=True, create=True),
            expiry=datetime.now(tz=timezone.utc) + timedelta(seconds=expires_in),
        )
        return f"https://{settings.adls_account_name}.dfs.core.windows.net/{settings.adls_container_name}/{path}?{sas}"


def create_storage_client() -> StorageClient:
    """Factory — returns the correct backend based on feature flag."""
    if settings.feature_adls_enabled:
        return ADLSStorageClient()
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

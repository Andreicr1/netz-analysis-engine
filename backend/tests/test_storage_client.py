"""Tests for StorageClient — local filesystem backend + path validation."""

from __future__ import annotations

import pytest

from app.services.storage_client import LocalStorageClient, StorageClient, create_storage_client


@pytest.fixture
def storage(tmp_path):
    """Create a LocalStorageClient with a temp directory."""
    return LocalStorageClient(root=tmp_path)


class TestLocalStorageClient:
    @pytest.mark.asyncio
    async def test_write_and_read(self, storage):
        data = b"hello world"
        path = await storage.write("bronze/org1/test.txt", data)
        assert path == "bronze/org1/test.txt"

        result = await storage.read("bronze/org1/test.txt")
        assert result == data

    @pytest.mark.asyncio
    async def test_read_missing_raises(self, storage):
        with pytest.raises(FileNotFoundError):
            await storage.read("nonexistent/file.txt")

    @pytest.mark.asyncio
    async def test_exists(self, storage):
        assert not await storage.exists("bronze/org1/test.txt")
        await storage.write("bronze/org1/test.txt", b"data")
        assert await storage.exists("bronze/org1/test.txt")

    @pytest.mark.asyncio
    async def test_delete(self, storage):
        await storage.write("bronze/org1/test.txt", b"data")
        assert await storage.exists("bronze/org1/test.txt")
        await storage.delete("bronze/org1/test.txt")
        assert not await storage.exists("bronze/org1/test.txt")

    @pytest.mark.asyncio
    async def test_delete_missing_is_noop(self, storage):
        # Should not raise
        await storage.delete("nonexistent/file.txt")

    @pytest.mark.asyncio
    async def test_list_files(self, storage):
        await storage.write("bronze/org1/a.txt", b"a")
        await storage.write("bronze/org1/b.txt", b"b")
        await storage.write("bronze/org2/c.txt", b"c")

        files = await storage.list_files("bronze/org1")
        assert sorted(files) == ["bronze/org1/a.txt", "bronze/org1/b.txt"]

    @pytest.mark.asyncio
    async def test_list_files_empty_prefix(self, storage):
        files = await storage.list_files("nonexistent")
        assert files == []

    @pytest.mark.asyncio
    async def test_overwrite(self, storage):
        await storage.write("bronze/org1/test.txt", b"v1")
        await storage.write("bronze/org1/test.txt", b"v2")
        result = await storage.read("bronze/org1/test.txt")
        assert result == b"v2"

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, storage):
        with pytest.raises(ValueError, match="Path traversal"):
            await storage.read("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_generate_read_url(self, storage):
        await storage.write("bronze/org1/test.txt", b"data")
        url = await storage.generate_read_url("bronze/org1/test.txt")
        assert url.startswith("file:///")

    @pytest.mark.asyncio
    async def test_generate_upload_url(self, storage):
        url = await storage.generate_upload_url("bronze/org1/new.txt")
        assert url.startswith("file:///")


class TestPathValidation:
    """Tests for StorageClient._validate_path — rejects traversal and absolute paths."""

    def test_rejects_empty_path(self):
        with pytest.raises(ValueError, match="must not be empty"):
            StorageClient._validate_path("")

    def test_rejects_null_bytes(self):
        with pytest.raises(ValueError, match="null bytes"):
            StorageClient._validate_path("bronze/org1/file\x00.txt")

    def test_rejects_dot_dot_traversal(self):
        with pytest.raises(ValueError, match="Path traversal"):
            StorageClient._validate_path("bronze/../etc/passwd")

    def test_rejects_leading_dot_dot(self):
        with pytest.raises(ValueError, match="Path traversal"):
            StorageClient._validate_path("../secret")

    def test_rejects_absolute_unix_path(self):
        with pytest.raises(ValueError, match="Absolute paths"):
            StorageClient._validate_path("/etc/passwd")

    def test_rejects_absolute_windows_path(self):
        with pytest.raises(ValueError, match="Absolute paths"):
            StorageClient._validate_path("C:\\Windows\\System32\\config")

    def test_rejects_backslash_absolute(self):
        with pytest.raises(ValueError, match="Absolute paths"):
            StorageClient._validate_path("\\\\server\\share")

    def test_accepts_valid_path(self):
        # Should not raise
        StorageClient._validate_path("bronze/org-123/fund-456/documents/v1/report.pdf")

    def test_accepts_dotfile(self):
        # Single dots inside segment names are fine (e.g. "file.txt")
        StorageClient._validate_path("bronze/org1/.gitkeep")

    def test_dot_dot_inside_segment_is_rejected(self):
        # ".." as a standalone path segment is traversal
        with pytest.raises(ValueError, match="Path traversal"):
            StorageClient._validate_path("bronze/org1/../../etc/passwd")

    @pytest.mark.asyncio
    async def test_local_client_write_rejects_traversal(self, storage):
        """Ensure LocalStorageClient also catches traversal via _resolve."""
        with pytest.raises(ValueError):
            await storage.write("../../etc/passwd", b"malicious")

    @pytest.mark.asyncio
    async def test_local_client_read_rejects_traversal(self, storage):
        with pytest.raises(ValueError):
            await storage.read("../../../etc/shadow")


class TestStorageClientFactory:
    def test_default_creates_local_client(self):
        client = create_storage_client()
        assert isinstance(client, LocalStorageClient)

    def test_is_storage_client_subclass(self):
        client = create_storage_client()
        assert isinstance(client, StorageClient)

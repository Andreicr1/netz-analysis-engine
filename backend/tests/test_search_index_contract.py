from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.services.azure.search_client import (
    describe_chunks_index_contract,
    get_chunks_index_client,
    resolve_chunks_index_name,
)


def _set_chunks_contract(monkeypatch: pytest.MonkeyPatch, *, env: str, base_name: str) -> str:
    monkeypatch.setattr(settings, "NETZ_ENV", env)
    monkeypatch.setattr(settings, "SEARCH_CHUNKS_INDEX_NAME", base_name)
    return settings.prefixed_index(base_name)


def test_chunks_index_contract_is_env_prefixed(monkeypatch: pytest.MonkeyPatch):
    resolved_name = _set_chunks_contract(
        monkeypatch,
        env="staging",
        base_name="canonical-chunks",
    )

    contract = describe_chunks_index_contract()

    assert resolve_chunks_index_name() == resolved_name
    assert contract.configured_base_name == "canonical-chunks"
    assert contract.resolved_name == resolved_name
    assert contract.env_name == "staging"


def test_get_chunks_index_client_uses_resolved_name(monkeypatch: pytest.MonkeyPatch):
    resolved_name = _set_chunks_contract(
        monkeypatch,
        env="qa",
        base_name="shared-index",
    )

    with patch("app.services.azure.search_client.get_search_client") as mock_get_client:
        get_chunks_index_client()

    mock_get_client.assert_called_once_with(index_name=resolved_name)


def test_upsert_chunks_uses_resolved_name(monkeypatch: pytest.MonkeyPatch):
    from ai_engine.extraction.search_upsert_service import upsert_chunks

    resolved_name = _set_chunks_contract(
        monkeypatch,
        env="staging",
        base_name="canonical-chunks",
    )

    mock_client = MagicMock()
    mock_client.upload_documents.return_value = [SimpleNamespace(succeeded=True)]

    with patch(
        "app.services.azure.search_client.get_search_client",
        return_value=mock_client,
    ) as mock_get_client:
        result = upsert_chunks([{"id": "chunk-1"}])

    assert result.successful_chunk_count == 1
    assert result.failed_chunk_count == 0
    assert result.is_full_success
    mock_get_client.assert_called_once_with(index_name=resolved_name)


def test_pipeline_kb_adapter_uses_resolved_name(monkeypatch: pytest.MonkeyPatch):
    from app.domains.credit.global_agent.pipeline_kb_adapter import PipelineKBAdapter

    resolved_name = _set_chunks_contract(
        monkeypatch,
        env="staging",
        base_name="canonical-chunks",
    )

    mock_client = MagicMock()
    mock_client.search.return_value = []

    with patch(
        "app.services.azure.search_client.get_search_client",
        return_value=mock_client,
    ) as mock_get_client:
        chunks = PipelineKBAdapter.search_live(
            query="pipeline overview",
            organization_id=uuid.uuid4(),
            top=5,
        )

    assert chunks == []
    mock_get_client.assert_called_once_with(index_name=resolved_name)


@pytest.mark.asyncio
async def test_rebuild_search_index_exposes_resolved_name(monkeypatch: pytest.MonkeyPatch):
    from ai_engine.pipeline.search_rebuild import rebuild_search_index

    resolved_name = _set_chunks_contract(
        monkeypatch,
        env="staging",
        base_name="canonical-chunks",
    )

    class _FakeStorage:
        async def list_files(self, prefix: str) -> list[str]:
            return []

    with patch(
        "app.services.storage_client.get_storage_client",
        return_value=_FakeStorage(),
    ):
        result = await rebuild_search_index(
            org_id=uuid.uuid4(),
            vertical="credit",
        )

    assert result.documents_processed == 0
    assert result.chunks_upserted == 0
    # After pgvector migration, resolved_index_name is the pgvector table name
    assert result.resolved_index_name == "vector_chunks (pgvector)"


def test_active_backend_paths_do_not_hardcode_v4_chunks_index():
    backend_root = Path(__file__).resolve().parents[1]
    excluded: set[Path] = set()
    offenders: list[str] = []

    for path in backend_root.rglob("*.py"):
        if path in excluded or "tests" in path.parts:
            continue
        if "global-vector-chunks-v4" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(backend_root).as_posix())

    assert offenders == []

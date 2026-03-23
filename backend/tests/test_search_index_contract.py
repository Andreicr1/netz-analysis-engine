from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest


def test_pipeline_kb_adapter_returns_empty_on_failure(monkeypatch: pytest.MonkeyPatch):
    """PipelineKBAdapter uses pgvector (not Azure Search). On failure it returns []."""
    from app.domains.credit.global_agent.pipeline_kb_adapter import PipelineKBAdapter

    # Mock embedding service to raise — adapter should catch and return []
    with patch(
        "ai_engine.extraction.embedding_service.generate_embeddings",
        side_effect=RuntimeError("embedding service unavailable"),
    ):
        chunks = PipelineKBAdapter.search_live(
            query="pipeline overview",
            organization_id=uuid.uuid4(),
            top=5,
        )

    assert chunks == []


@pytest.mark.asyncio
async def test_rebuild_search_index_exposes_resolved_name(monkeypatch: pytest.MonkeyPatch):
    from ai_engine.pipeline.search_rebuild import rebuild_search_index

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
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "global-vector-chunks-v4" in content:
            offenders.append(path.relative_to(backend_root).as_posix())

    assert offenders == []

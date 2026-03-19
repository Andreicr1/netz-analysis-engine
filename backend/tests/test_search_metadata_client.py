from __future__ import annotations

import inspect
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.core.config import settings
from app.core.security.clerk_auth import Actor
from app.services.search_index import AzureSearchMetadataClient
from app.shared.enums import Role


def test_metadata_upsert_uses_supported_search_client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "SEARCH_INDEX_NAME", "metadata-index")

    mock_client = MagicMock()
    mock_client.upload_documents.return_value = [
        MagicMock(succeeded=True),
        MagicMock(succeeded=True),
    ]

    with patch(
        "app.services.azure.search_client.get_metadata_index_client",
        return_value=mock_client,
    ):
        uploaded = AzureSearchMetadataClient(
            caller="test",
        ).upsert_dataroom_metadata(
            items=[
                {"id": "doc-1", "fund_id": str(uuid.uuid4())},
                {"id": "doc-2", "fund_id": str(uuid.uuid4())},
            ],
        )

    assert uploaded == 2
    documents = mock_client.upload_documents.call_args.kwargs["documents"]
    assert documents[0]["@search.action"] == "mergeOrUpload"
    assert documents[1]["@search.action"] == "mergeOrUpload"


def test_metadata_search_filters_fund_and_org(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "SEARCH_INDEX_NAME", "metadata-index")

    fund_id = uuid.uuid4()
    org_id = uuid.uuid4()
    mock_client = MagicMock()
    mock_client.search.return_value = [
        {
            "id": "hit-1",
            "fund_id": str(fund_id),
            "document_id": "doc-1",
            "title": "LPA",
            "content": "Fund terms",
            "doc_type": "DATAROOM",
            "version": "v1",
            "root_folder": "Legal",
            "folder_path": "Legal/LPA",
            "version_blob_path": "Legal/LPA/doc.pdf",
            "uploaded_at": "2026-03-17T00:00:00+00:00",
            "@search.score": 1.5,
        },
    ]

    with patch(
        "app.services.azure.search_client.get_metadata_index_client",
        return_value=mock_client,
    ):
        hits = AzureSearchMetadataClient(
            caller="test",
        ).search(
            q="lpa",
            fund_id=fund_id,
            organization_id=org_id,
            root_folder="Legal",
            top=7,
        )

    call_kwargs = mock_client.search.call_args.kwargs
    assert f"fund_id eq '{fund_id}'" in call_kwargs["filter"]
    assert f"organization_id eq '{org_id}'" in call_kwargs["filter"]
    assert "root_folder eq 'Legal'" in call_kwargs["filter"]
    assert call_kwargs["top"] == 7
    assert len(hits) == 1
    assert hits[0].title == "LPA"
    assert hits[0].score == 1.5


@pytest.mark.asyncio
async def test_dataroom_search_route_uses_supported_metadata_client(
    monkeypatch: pytest.MonkeyPatch,
):
    from app.domains.credit.dataroom.routes import routes as dataroom_routes

    monkeypatch.setattr(settings, "SEARCH_INDEX_NAME", "metadata-index")
    fund_id = uuid.uuid4()
    org_id = uuid.uuid4()
    actor = Actor(
        actor_id="user-1",
        name="Test User",
        email="test@example.com",
        roles=[Role.ADMIN],
        organization_id=org_id,
        fund_ids=[],
    )

    mock_client = MagicMock()
    mock_client.search.return_value = [
        {
            "id": "hit-1",
            "fund_id": str(fund_id),
            "document_id": "doc-1",
            "title": "Manager Letter",
            "content": "pipeline update",
            "doc_type": "DATAROOM",
            "version": "v1",
            "root_folder": "Pipeline",
            "folder_path": "Pipeline/Manager Letter",
            "version_blob_path": "Pipeline/doc.pdf",
            "uploaded_at": "2026-03-17T00:00:00+00:00",
        },
    ]

    with patch(
        "app.services.azure.search_client.get_metadata_index_client",
        return_value=mock_client,
    ):
        response = await dataroom_routes.search(
            fund_id=fund_id,
            q="pipeline",
            top=4,
            actor=actor,
            _role_guard=actor,
        )

    assert response["count"] == 1
    assert response["hits"][0]["title"] == "Manager Letter"
    call_kwargs = mock_client.search.call_args.kwargs
    assert f"fund_id eq '{fund_id}'" in call_kwargs["filter"]
    assert f"organization_id eq '{org_id}'" in call_kwargs["filter"]


def test_static_guard_blocks_stub_metadata_client_behavior():
    source = inspect.getsource(AzureSearchMetadataClient)
    assert "NotImplementedError" not in source
    assert "Sprint 3" not in source

    backend_root = Path(__file__).resolve().parents[1]
    guarded_files = [
        backend_root / "ai_engine" / "ingestion" / "document_scanner.py",
        backend_root / "ai_engine" / "extraction" / "obligation_extractor.py",
        backend_root / "ai_engine" / "knowledge" / "knowledge_builder.py",
        backend_root / "app" / "domains" / "credit" / "dataroom" / "routes" / "routes.py",
        backend_root / "app" / "domains" / "credit" / "documents" / "service.py",
    ]

    for path in guarded_files:
        contents = path.read_text(encoding="utf-8")
        assert "Search index not configured" not in contents

    documents_service = (
        backend_root / "app" / "domains" / "credit" / "documents" / "service.py"
    ).read_text(encoding="utf-8")
    assert "settings.AZURE_SEARCH_ENDPOINT" not in documents_service

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

from ai_engine.pipeline import unified_pipeline
from app.services.azure import pipeline_dispatch


class DummyBackgroundTasks:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def add_task(self, func, *args, **kwargs) -> None:
        self.calls.append((func, args, kwargs))


def _import_extraction_routes():
    sys.modules.pop("app.domains.credit.modules.ai.extraction", None)
    stub_pipeline_module = ModuleType("vertical_engines.credit.pipeline")
    stub_pipeline_module.run_pipeline_ingest = lambda *args, **kwargs: {}
    sys.modules["vertical_engines.credit.pipeline"] = stub_pipeline_module
    return importlib.import_module("app.domains.credit.modules.ai.extraction")


def test_dispatch_extraction_background_tasks_uses_unified_pipeline(monkeypatch):
    background_tasks = DummyBackgroundTasks()
    invoked: list[dict[str, object]] = []

    def fake_run_extraction_pipeline(**kwargs):
        invoked.append(kwargs)
        return kwargs["job_id"]

    monkeypatch.setattr(unified_pipeline, "run_extraction_pipeline", fake_run_extraction_pipeline)

    response = pipeline_dispatch.dispatch_extraction(
        background_tasks=background_tasks,
        source="deals",
        deals_filter="blue",
        dry_run=False,
        skip_bootstrap=False,
        skip_prepare=False,
        skip_embed=False,
        skip_enrich=False,
        no_index=False,
        job_id="job-123",
        actor_id="actor-1",
    )

    assert response["dispatch"] == "background_tasks"
    assert response["pipeline_name"] == "unified_pipeline"
    assert len(background_tasks.calls) == 1

    func, args, kwargs = background_tasks.calls[0]
    assert args == ()
    assert kwargs == {}
    asyncio.run(func())

    assert invoked == [{
        "source": "deals",
        "deals_filter": "blue",
        "dry_run": False,
        "skip_bootstrap": False,
        "skip_prepare": False,
        "skip_embed": False,
        "skip_enrich": False,
        "no_index": False,
        "job_id": "job-123",
    }]


def test_trigger_extraction_pipeline_allocates_canonical_job(monkeypatch):
    extraction_routes = _import_extraction_routes()
    allocated_jobs: list[tuple[str, str]] = []

    def fake_new_job(source: str, deals_filter: str, *, pipeline_name: str = "unified_pipeline"):
        allocated_jobs.append((source, deals_filter))
        return "job-789"

    def fake_dispatch(**kwargs):
        return kwargs

    monkeypatch.setattr(unified_pipeline, "new_extraction_job", fake_new_job)
    monkeypatch.setattr("app.services.azure.pipeline_dispatch.dispatch_extraction", fake_dispatch)

    actor = SimpleNamespace(actor_id="actor-3")
    result = extraction_routes.trigger_extraction_pipeline(
        background_tasks=DummyBackgroundTasks(),
        source="deals",
        deals_filter="atlas",
        dry_run=False,
        skip_bootstrap=False,
        skip_prepare=False,
        skip_embed=False,
        skip_enrich=False,
        no_index=False,
        actor=actor,
        _write_guard=actor,
        _role_guard=actor,
    )

    assert allocated_jobs == [("deals", "atlas")]
    assert result["job_id"] == "job-789"


def test_extraction_status_and_jobs_routes_use_canonical_tracker(monkeypatch):
    extraction_routes = _import_extraction_routes()
    monkeypatch.setattr(
        unified_pipeline,
        "get_extraction_job_status",
        lambda job_id: {"job_id": job_id, "status": "completed"},
    )
    monkeypatch.setattr(
        unified_pipeline,
        "list_extraction_jobs",
        lambda: [{"job_id": "job-a"}, {"job_id": "job-b"}],
    )

    actor = SimpleNamespace(actor_id="actor-4")

    assert extraction_routes.get_extraction_status("job-a", _role_guard=actor) == {
        "job_id": "job-a",
        "status": "completed",
    }
    assert extraction_routes.list_extraction_jobs(_role_guard=actor) == {
        "jobs": [{"job_id": "job-a"}, {"job_id": "job-b"}],
    }


def test_extraction_sources_route_uses_canonical_source_registry(monkeypatch):
    extraction_routes = _import_extraction_routes()

    async def fake_list(source):
        return ["Alpha", "Beta"]

    monkeypatch.setattr(unified_pipeline, "list_extraction_source_items", fake_list)

    actor = SimpleNamespace(actor_id="actor-5")
    result = asyncio.run(extraction_routes.list_extraction_sources(
        source="deals",
        _role_guard=actor,
    ))

    assert result == {
        "source": "deals",
        "storage_prefix": "bronze/batch/deals",
        "items": ["Alpha", "Beta"],
        "count": 2,
    }


def test_run_extraction_pipeline_invokes_unified_pipeline_process(monkeypatch):
    processed_requests: list[object] = []

    class FakeStorage:
        async def list_files(self, prefix):
            return [
                f"{prefix}/Blue Owl/deck.pdf",
                f"{prefix}/Blue Owl/notes.txt",
                f"{prefix}/Ares/summary.pdf",
            ]

    async def fake_process(request, *, db=None, actor_id="unified-pipeline", skip_index=False):
        processed_requests.append((request, actor_id, skip_index))
        return unified_pipeline.PipelineStageResult(
            stage="complete",
            success=True,
            data={},
            metrics={"chunk_count": 2, "duration_ms": 12},
        )

    monkeypatch.setattr(
        "app.services.storage_client.get_storage_client",
        lambda: FakeStorage(),
    )
    monkeypatch.setattr(unified_pipeline, "process", fake_process)

    job_id = unified_pipeline.run_extraction_pipeline(
        source="deals",
        deals_filter="blue",
        no_index=True,
    )

    job = unified_pipeline.get_extraction_job_status(job_id)
    assert job["status"] == "completed"
    assert job["summary"]["ok"] == 1
    assert len(processed_requests) == 1
    request, actor_id, skip_index = processed_requests[0]
    assert request.filename == "deck.pdf"
    assert request.blob_uri == "bronze/batch/deals/Blue Owl/deck.pdf"
    assert actor_id == "unified_pipeline"
    assert skip_index is True


def test_legacy_orchestrator_is_deleted():
    """extraction_orchestrator.py was removed in the legacy cleanup.

    This test ensures it stays deleted — no accidental resurrection.
    """
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / "backend" / "ai_engine" / "extraction" / "extraction_orchestrator.py"
    assert not path.exists(), "extraction_orchestrator.py must not exist — it was deleted in the legacy cleanup"

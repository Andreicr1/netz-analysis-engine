from __future__ import annotations

import ast
import importlib
from pathlib import Path
from types import SimpleNamespace
from types import ModuleType
import sys

from app.services.azure import pipeline_dispatch
from ai_engine.pipeline import unified_pipeline


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

    monkeypatch.setattr(pipeline_dispatch, "_use_service_bus", lambda: False)

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
    func()

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


def test_dispatch_extraction_service_bus_marks_unified_pipeline(monkeypatch):
    captured: dict[str, object] = {}

    monkeypatch.setattr(pipeline_dispatch, "_use_service_bus", lambda: True)

    def fake_send_to_topic(topic: str, payload: dict[str, object], *, stage: str):
        captured["topic"] = topic
        captured["payload"] = payload
        captured["stage"] = stage
        return "sb-job-1"

    monkeypatch.setattr("app.services.azure.servicebus_client.send_to_topic", fake_send_to_topic)

    response = pipeline_dispatch.dispatch_extraction(
        background_tasks=DummyBackgroundTasks(),
        source="market-data",
        deals_filter="",
        dry_run=True,
        skip_bootstrap=False,
        skip_prepare=False,
        skip_embed=True,
        skip_enrich=True,
        no_index=True,
        job_id="job-456",
        actor_id="actor-2",
    )

    assert response["dispatch"] == "service_bus"
    assert response["pipeline_name"] == "unified_pipeline"
    assert captured["topic"] == "document-pipeline"
    assert captured["stage"] == "extraction"
    assert captured["payload"]["pipeline_name"] == "unified_pipeline"
    assert captured["payload"]["legacy_path_invoked"] is False


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
    monkeypatch.setattr(unified_pipeline, "list_extraction_source_items", lambda source: ["Alpha", "Beta"])

    actor = SimpleNamespace(actor_id="actor-5")
    result = extraction_routes.list_extraction_sources(
        source="deals",
        _role_guard=actor,
    )

    assert result == {
        "source": "deals",
        "container": "investment-pipeline-intelligence",
        "items": ["Alpha", "Beta"],
        "count": 2,
    }


def test_run_extraction_pipeline_invokes_unified_pipeline_process(monkeypatch):
    processed_requests: list[object] = []

    class FakeBlobEntry:
        def __init__(self, name: str, is_folder: bool = False) -> None:
            self.name = name
            self.is_folder = is_folder

    async def fake_process(request, *, db=None, actor_id="unified-pipeline", skip_index=False):
        processed_requests.append((request, actor_id, skip_index))
        return unified_pipeline.PipelineStageResult(
            stage="complete",
            success=True,
            data={},
            metrics={"chunk_count": 2, "duration_ms": 12},
        )

    monkeypatch.setattr(
        "app.services.blob_storage.list_blobs",
        lambda **kwargs: [
            FakeBlobEntry("Blue Owl/deck.pdf"),
            FakeBlobEntry("Blue Owl/notes.txt"),
            FakeBlobEntry("Ares/summary.pdf"),
        ],
    )
    monkeypatch.setattr("app.services.blob_storage.blob_uri", lambda container, blob_path: f"{container}/{blob_path}")
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
    assert request.blob_uri == "investment-pipeline-intelligence/Blue Owl/deck.pdf"
    assert actor_id == "unified_pipeline"
    assert skip_index is True


def test_static_import_guard_blocks_legacy_orchestrator_reachability():
    repo_root = Path(__file__).resolve().parents[2]
    production_roots = [
        repo_root / "backend" / "app",
        repo_root / "backend" / "ai_engine",
    ]
    allowed_paths = {
        repo_root / "backend" / "ai_engine" / "extraction" / "extraction_orchestrator.py",
    }
    violations: list[str] = []

    for root in production_roots:
        for file_path in root.rglob("*.py"):
            if file_path in allowed_paths:
                continue
            tree = ast.parse(file_path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "ai_engine.extraction.extraction_orchestrator":
                    violations.append(str(file_path.relative_to(repo_root)))
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "ai_engine.extraction.extraction_orchestrator":
                            violations.append(str(file_path.relative_to(repo_root)))

    assert violations == []

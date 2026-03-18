"""CI guard: route and worker manifests must match the live FastAPI app.

If this test fails, run from backend/:
    python scripts/generate_manifests.py

Then commit the updated manifests/*.json files.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app

MANIFEST_DIR = Path(__file__).resolve().parent.parent / "manifests"
ROUTES_FILE = MANIFEST_DIR / "routes.json"
WORKERS_FILE = MANIFEST_DIR / "workers.json"


def _live_routes() -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        name = getattr(route, "name", None)
        if methods and path:
            for method in sorted(methods):
                entries.append({"method": method, "path": path, "name": name or ""})
    entries.sort(key=lambda e: (e["method"], e["path"], e["name"]))
    return entries


def _live_workers() -> list[dict[str, str]]:
    workers: list[dict[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        name = getattr(route, "name", None)
        tags = getattr(route, "tags", [])
        if not path or not methods:
            continue
        is_worker = "/workers/" in path or "workers" in (tags or [])
        if is_worker and "POST" in (methods or set()):
            workers.append({"method": "POST", "path": path, "name": name or ""})
    workers.sort(key=lambda w: w["path"])
    return workers


def _read_manifest(path: Path) -> list[dict[str, str]]:
    assert path.exists(), f"Manifest not found: {path}. Run: python scripts/generate_manifests.py"
    return json.loads(path.read_text(encoding="utf-8"))


class TestRouteManifest:
    def test_routes_manifest_exists(self) -> None:
        assert ROUTES_FILE.exists(), (
            f"{ROUTES_FILE} not found. Run: python scripts/generate_manifests.py"
        )

    def test_routes_manifest_byte_equal(self) -> None:
        """CI-generated route inventory must be byte-for-byte equal to checked-in manifest."""
        checked_in = _read_manifest(ROUTES_FILE)
        live = _live_routes()
        assert json.dumps(checked_in, indent=2) == json.dumps(live, indent=2), (
            "Route manifest is stale. Run: python scripts/generate_manifests.py"
        )

    def test_no_undocumented_routes(self) -> None:
        """Every mounted handler must appear in the manifest."""
        checked_in = {(e["method"], e["path"]) for e in _read_manifest(ROUTES_FILE)}
        live = {(e["method"], e["path"]) for e in _live_routes()}
        missing = live - checked_in
        assert not missing, f"Routes mounted but not in manifest: {sorted(missing)}"

    def test_no_phantom_routes(self) -> None:
        """Every manifest entry must have a mounted handler."""
        checked_in = {(e["method"], e["path"]) for e in _read_manifest(ROUTES_FILE)}
        live = {(e["method"], e["path"]) for e in _live_routes()}
        phantom = checked_in - live
        assert not phantom, f"Routes in manifest but not mounted: {sorted(phantom)}"


class TestWorkerManifest:
    def test_workers_manifest_exists(self) -> None:
        assert WORKERS_FILE.exists(), (
            f"{WORKERS_FILE} not found. Run: python scripts/generate_manifests.py"
        )

    def test_workers_manifest_byte_equal(self) -> None:
        """CI-generated worker inventory must be byte-for-byte equal to checked-in manifest."""
        checked_in = _read_manifest(WORKERS_FILE)
        live = _live_workers()
        assert json.dumps(checked_in, indent=2) == json.dumps(live, indent=2), (
            "Worker manifest is stale. Run: python scripts/generate_manifests.py"
        )

    def test_no_undocumented_workers(self) -> None:
        checked_in = {e["path"] for e in _read_manifest(WORKERS_FILE)}
        live = {e["path"] for e in _live_workers()}
        missing = live - checked_in
        assert not missing, f"Workers mounted but not in manifest: {sorted(missing)}"

    def test_no_phantom_workers(self) -> None:
        checked_in = {e["path"] for e in _read_manifest(WORKERS_FILE)}
        live = {e["path"] for e in _live_workers()}
        phantom = checked_in - live
        assert not phantom, f"Workers in manifest but not mounted: {sorted(phantom)}"

    def test_run_cvar_absent(self) -> None:
        """AC-4: /run-cvar must not appear in the worker manifest."""
        worker_paths = {e["path"] for e in _read_manifest(WORKERS_FILE)}
        cvar_paths = {p for p in worker_paths if "cvar" in p.lower()}
        assert not cvar_paths, f"/run-cvar found in worker manifest: {cvar_paths}"

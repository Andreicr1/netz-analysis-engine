"""Generate canonical route and worker manifests from the live FastAPI app.

Usage (from backend/):
    python scripts/generate_manifests.py          # write to backend/manifests/
    python scripts/generate_manifests.py --check   # compare & exit non-zero on diff

The manifests are deterministic JSON files introspected from ``app.main.app``
at import time (no running server needed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure backend/ is on sys.path so ``from app.main import app`` works
# regardless of how this script is invoked.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.main import app  # noqa: E402

MANIFEST_DIR = _BACKEND_DIR / "manifests"
ROUTES_FILE = MANIFEST_DIR / "routes.json"
WORKERS_FILE = MANIFEST_DIR / "workers.json"


def _collect_routes() -> list[dict[str, str]]:
    """Return a sorted list of all mounted routes (method, path, name)."""
    entries: list[dict[str, str]] = []
    for route in app.routes:
        # Only APIRoute instances have methods; skip Mount / default routes
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        name = getattr(route, "name", None)
        if methods and path:
            for method in sorted(methods):
                entries.append({
                    "method": method,
                    "path": path,
                    "name": name or "",
                })
    # Deterministic order: method, path, name
    entries.sort(key=lambda e: (e["method"], e["path"], e["name"]))
    return entries


def _collect_workers() -> list[dict[str, str]]:
    """Return a sorted list of worker trigger endpoints."""
    workers: list[dict[str, str]] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        name = getattr(route, "name", None)
        tags = getattr(route, "tags", [])
        if not path or not methods:
            continue
        # Worker endpoints live under /workers/ or tagged "workers"
        is_worker = "/workers/" in path or "workers" in (tags or [])
        if is_worker and "POST" in (methods or set()):
            workers.append({
                "method": "POST",
                "path": path,
                "name": name or "",
            })
    workers.sort(key=lambda w: w["path"])
    return workers


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_json(path: Path) -> object:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or check route/worker manifests")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare generated manifests against checked-in files; exit 1 on mismatch",
    )
    args = parser.parse_args()

    routes = _collect_routes()
    workers = _collect_workers()

    if args.check:
        ok = True
        for label, generated, path in [
            ("routes", routes, ROUTES_FILE),
            ("workers", workers, WORKERS_FILE),
        ]:
            existing = _read_json(path)
            if existing is None:
                print(f"FAIL: {path} does not exist. Run: python scripts/generate_manifests.py")
                ok = False
            elif json.dumps(existing, indent=2, ensure_ascii=False) != json.dumps(
                generated, indent=2, ensure_ascii=False
            ):
                print(f"FAIL: {label} manifest is stale. Run: python scripts/generate_manifests.py")
                # Show diff summary
                existing_set = {(e["method"], e["path"]) for e in existing}
                generated_set = {(e["method"], e["path"]) for e in generated}
                added = generated_set - existing_set
                removed = existing_set - generated_set
                if added:
                    print(f"  Added:   {sorted(added)}")
                if removed:
                    print(f"  Removed: {sorted(removed)}")
                ok = False
            else:
                print(f"OK: {label} manifest is up-to-date")
        return 0 if ok else 1

    # Write mode
    _write_json(ROUTES_FILE, routes)
    _write_json(WORKERS_FILE, workers)
    print(f"Wrote {len(routes)} routes to {ROUTES_FILE}")
    print(f"Wrote {len(workers)} workers to {WORKERS_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

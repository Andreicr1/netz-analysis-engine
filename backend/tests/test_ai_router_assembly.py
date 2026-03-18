from __future__ import annotations

import importlib
import sys

import pytest


MODULE_NAME = "app.domains.credit.modules.ai"
EXPECTED_SUBROUTERS = (
    "copilot",
    "documents",
    "compliance",
    "pipeline_deals",
    "deep_review",
    "memo_chapters",
    "artifacts",
)
EXPECTED_OPTIONAL_SUBROUTERS = (
    "extraction",
    "portfolio",
)


def _load_ai_router_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    failing_module: str | None = None,
):
    original_import_module = importlib.import_module

    def _patched_import_module(name: str, package: str | None = None):
        if name == failing_module:
            raise ImportError("synthetic import failure")
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", _patched_import_module)
    sys.modules.pop(MODULE_NAME, None)
    return original_import_module(MODULE_NAME)


def test_ai_router_diagnostics_expose_exact_loaded_subrouter_set(
    monkeypatch: pytest.MonkeyPatch,
):
    module = _load_ai_router_module(monkeypatch)

    diagnostics = module.get_ai_router_diagnostics()

    assert diagnostics.status == "degraded"
    assert diagnostics.loaded_modules == EXPECTED_SUBROUTERS
    assert diagnostics.required_modules == EXPECTED_SUBROUTERS
    assert diagnostics.degraded_modules == EXPECTED_OPTIONAL_SUBROUTERS
    assert diagnostics.failure_details == ()
    assert diagnostics.route_count == len(module.router.routes)


def test_required_ai_subrouter_import_failure_raises_on_module_import(
    monkeypatch: pytest.MonkeyPatch,
):
    failing_module = "app.domains.credit.modules.ai.copilot"

    with pytest.raises(RuntimeError, match="copilot"):
        _load_ai_router_module(
            monkeypatch,
            failing_module=failing_module,
        )

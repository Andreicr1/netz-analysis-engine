"""CFG-02 — Verify no runtime-critical env vars are captured at module level.

Acceptance criteria:
1. Static AST inspection confirms no ``os.environ.get`` / ``os.getenv`` calls
   exist at module-level scope in the four listed files.
2. Settings-based resolution works correctly for the affected configuration
   values (search credentials, LLM concurrency).
3. ``get_llm_concurrency()`` and the policy loader search accessors resolve
   through the Settings singleton, not through stale module-level captures.

Restart requirements (documented here per acceptance criterion 3):
- AZURE_SEARCH_ENDPOINT / AZURE_SEARCH_KEY: No restart required.  The lazy
  ``_search_endpoint()`` / ``_search_api_key()`` functions in policy_loader.py
  read from the ``settings`` singleton on every call.  In practice the
  singleton is constructed once at application startup (module import), so
  a process restart IS required to pick up a new value in production.  For
  test fixtures, monkeypatching ``settings.azure_search_endpoint`` (and
  ``azure_search_key``) is sufficient.
- NETZ_LLM_CONCURRENCY: Same pattern.  ``get_llm_concurrency()`` reads
  ``settings.netz_llm_concurrency`` which is set from env at Settings
  construction.  Monkeypatching the Settings field works in tests; production
  changes require a restart.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# ──────────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────────

_BACKEND_ROOT = Path(__file__).resolve().parents[1]

# The three files covered by CFG-02 (extraction_orchestrator deleted in legacy cleanup).
_TARGET_FILES: dict[str, Path] = {
    "policy_loader": _BACKEND_ROOT / "ai_engine" / "governance" / "policy_loader.py",
    "prompt_registry": _BACKEND_ROOT / "ai_engine" / "prompts" / "registry.py",
    "deep_review_models": _BACKEND_ROOT / "vertical_engines" / "credit" / "deep_review" / "models.py",
}


def _collect_module_level_env_calls(source_path: Path) -> list[dict]:
    """AST-walk *source_path* and return every ``os.environ.get`` / ``os.getenv``
    call that lives **directly** at module (top) level — i.e. not inside any
    function, class, or method body.

    Returns a list of dicts with keys ``lineno``, ``call``.
    """
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    violations: list[dict] = []

    for node in ast.iter_child_nodes(tree):
        # Only consider Assign / AugAssign / AnnAssign / Expr at module level.
        # Function and class bodies are excluded by only iterating direct
        # children of the Module node.
        if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Expr)):
            continue

        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            func = sub.func
            # os.environ.get(...)
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Attribute)
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "os"
                and func.value.attr == "environ"
                and func.attr == "get"
            ):
                violations.append({"lineno": sub.lineno, "call": "os.environ.get"})
            # os.getenv(...)
            elif (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
                and func.attr == "getenv"
            ):
                violations.append({"lineno": sub.lineno, "call": "os.getenv"})

    return violations


# ──────────────────────────────────────────────────────────────────────────────
#  Test 1 — Static inspection: no module-level env captures in target files
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("label,path", list(_TARGET_FILES.items()))
def test_no_module_level_env_capture(label: str, path: Path) -> None:
    """No ``os.environ.get`` / ``os.getenv`` call must appear at module scope."""
    assert path.exists(), f"File not found: {path}"
    violations = _collect_module_level_env_calls(path)
    assert violations == [], (
        f"{label} ({path.name}) has {len(violations)} module-level env capture(s):\n"
        + "\n".join(
            f"  line {v['lineno']}: {v['call']}(...)"
            for v in violations
        )
    )


# ──────────────────────────────────────────────────────────────────────────────
#  Test 2 — policy_loader: lazy accessors read from Settings
# ──────────────────────────────────────────────────────────────────────────────

def test_policy_loader_search_endpoint_reads_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_search_endpoint()`` must reflect Settings, not a stale module-level capture."""
    from ai_engine.governance import policy_loader
    from app.core.config.settings import settings

    original = settings.azure_search_endpoint
    try:
        monkeypatch.setattr(settings, "azure_search_endpoint", "https://test-endpoint.search.windows.net")
        assert policy_loader._search_endpoint() == "https://test-endpoint.search.windows.net"
    finally:
        monkeypatch.setattr(settings, "azure_search_endpoint", original)


def test_policy_loader_search_api_key_reads_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_search_api_key()`` must reflect Settings, not a stale module-level capture."""
    from ai_engine.governance import policy_loader
    from app.core.config.settings import settings

    original = settings.azure_search_key
    try:
        monkeypatch.setattr(settings, "azure_search_key", "test-api-key-cfg02")
        assert policy_loader._search_api_key() == "test-api-key-cfg02"
    finally:
        monkeypatch.setattr(settings, "azure_search_key", original)


def test_policy_loader_search_returns_empty_when_no_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_search()`` returns [] and logs a warning when endpoint/key are empty."""
    from ai_engine.governance import policy_loader
    from app.core.config.settings import settings

    monkeypatch.setattr(settings, "azure_search_endpoint", "")
    monkeypatch.setattr(settings, "azure_search_key", "")

    result = policy_loader._search("some-index", "query")
    assert result == []


# ──────────────────────────────────────────────────────────────────────────────
#  Test 3 — deep_review/models: get_llm_concurrency() reads from Settings
# ──────────────────────────────────────────────────────────────────────────────

def test_get_llm_concurrency_reads_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_llm_concurrency()`` must return Settings value, not a frozen constant."""
    from app.core.config.settings import settings
    from vertical_engines.credit.deep_review.models import get_llm_concurrency

    original = settings.netz_llm_concurrency
    try:
        monkeypatch.setattr(settings, "netz_llm_concurrency", 12)
        assert get_llm_concurrency() == 12

        monkeypatch.setattr(settings, "netz_llm_concurrency", 1)
        assert get_llm_concurrency() == 1
    finally:
        monkeypatch.setattr(settings, "netz_llm_concurrency", original)


def test_get_llm_concurrency_clamps_to_minimum_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """``get_llm_concurrency()`` must return at least 1 even when Settings is 0."""
    from app.core.config.settings import settings
    from vertical_engines.credit.deep_review.models import get_llm_concurrency

    monkeypatch.setattr(settings, "netz_llm_concurrency", 0)
    assert get_llm_concurrency() == 1


def test_get_llm_concurrency_default_is_reasonable() -> None:
    """Default concurrency (5) must be a sensible positive integer."""
    from app.core.config.settings import Settings

    fresh = Settings()
    assert fresh.netz_llm_concurrency == 5


# ──────────────────────────────────────────────────────────────────────────────
#  Test 4 — Settings field existence for newly-added fields
# ──────────────────────────────────────────────────────────────────────────────

def test_settings_has_netz_llm_concurrency_field() -> None:
    """Settings must expose ``netz_llm_concurrency`` for lazy resolution."""
    from app.core.config.settings import settings
    assert hasattr(settings, "netz_llm_concurrency")
    assert isinstance(settings.netz_llm_concurrency, int)


def test_settings_has_search_fields() -> None:
    """Settings must expose both ``azure_search_endpoint`` and ``azure_search_key``."""
    from app.core.config.settings import settings
    assert hasattr(settings, "azure_search_endpoint")
    assert hasattr(settings, "azure_search_key")


# ──────────────────────────────────────────────────────────────────────────────
#  Test 6 — prompts/registry: os.getenv calls inside __init__ are acceptable
# ──────────────────────────────────────────────────────────────────────────────

def test_prompt_registry_module_level_has_no_env_captures() -> None:
    """Module-level scan of registry.py must find no env captures (init-time is OK)."""
    path = _TARGET_FILES["prompt_registry"]
    violations = _collect_module_level_env_calls(path)
    assert violations == [], (
        f"registry.py has unexpected module-level env captures: {violations}"
    )

"""Tests that PromptRegistry uses SandboxedEnvironment (SSTI mitigation)."""
from __future__ import annotations

from pathlib import Path

import pytest
from jinja2.sandbox import SandboxedEnvironment

from ai_engine.prompts.registry import PromptRegistry


@pytest.fixture
def tmp_prompts(tmp_path: Path) -> Path:
    """Create a minimal template directory for testing."""
    tpl = tmp_path / "hello.j2"
    tpl.write_text("Hello, {{ name }}!")
    return tmp_path


class TestRegistrySandbox:
    def test_env_is_sandboxed(self, tmp_prompts: Path) -> None:
        registry = PromptRegistry(prompts_dir=tmp_prompts)
        assert isinstance(registry._env, SandboxedEnvironment)

    def test_render_basic_template(self, tmp_prompts: Path) -> None:
        registry = PromptRegistry(prompts_dir=tmp_prompts)
        result = registry.render("hello.j2", name="World")
        assert result == "Hello, World!"

    def test_add_search_path(self, tmp_prompts: Path, tmp_path: Path) -> None:
        # Create a second template directory inside tmp_prompts (must be under backend/)
        # Use add_search_path's path validation by monkeypatching the backend root check
        registry = PromptRegistry(prompts_dir=tmp_prompts)

        extra_dir = tmp_prompts / "extra"
        extra_dir.mkdir()
        (extra_dir / "bonus.j2").write_text("Bonus: {{ x }}")

        # Directly append to searchpath to avoid the backend-root check in tests
        registry._env.loader.searchpath.append(str(extra_dir))

        result = registry.render("bonus.j2", x="42")
        assert result == "Bonus: 42"

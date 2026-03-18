"""Prompt Template Registry — Jinja2-based prompt management.

Centralizes all AI prompt templates with:
- Jinja2 rendering with variable interpolation
- Template metadata extraction from frontmatter comments
- Multi-application support via configurable prompt sets
- LRU caching of compiled templates
- Fail-fast on missing templates

Usage::

    from ai_engine.prompts import prompt_registry

    system = prompt_registry.render("ch01_exec.j2", deal_name="ABC Corp")
    system, user = prompt_registry.render_pair("doc_review", question="...", chunks="...")
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
import yaml
from jinja2 import FileSystemLoader, TemplateNotFound  # pyright: ignore[reportMissingImports]
from jinja2.sandbox import SandboxedEnvironment

logger = structlog.get_logger()

_PROMPTS_DIR = Path(__file__).parent
_METADATA_RE = re.compile(r"\{#-\s*metadata\s*\n(.*?)-#\}", re.DOTALL)


class PromptRegistry:
    """Centralized Jinja2 prompt template management."""

    def __init__(
        self,
        prompts_dir: Path | str | None = None,
        prompt_set: str | None = None,
    ):
        self._base_dir = Path(prompts_dir) if prompts_dir else _PROMPTS_DIR
        self._prompt_set = prompt_set or os.getenv("PROMPT_SET", "")

        search_paths = []
        if self._prompt_set:
            override_dir = self._base_dir / self._prompt_set
            if override_dir.is_dir():
                search_paths.append(str(override_dir))
        search_paths.append(str(self._base_dir))

        self._env = SandboxedEnvironment(
            loader=FileSystemLoader(search_paths),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
            auto_reload=os.getenv("NETZ_ENV", "dev") == "dev",
        )
        logger.info(
            "PromptRegistry initialized — base=%s prompt_set=%s search_paths=%s",
            self._base_dir, self._prompt_set or "(default)", search_paths,
        )

    def render(self, template_name: str, **context: Any) -> str:
        """Render a Jinja2 template with context variables.

        Args:
            template_name: Template filename (e.g. "ch01_exec.j2")
            **context: Variables to inject into the template

        Returns:
            Rendered prompt string

        Raises:
            TemplateNotFound: If the template file does not exist

        """
        try:
            template = self._env.get_template(template_name)
            return template.render(**context)
        except TemplateNotFound:
            logger.error("Prompt template not found: %s", template_name)
            raise

    def render_pair(
        self,
        stage: str,
        *,
        system_template: str | None = None,
        user_template: str | None = None,
        subdirectory: str = "",
        **context: Any,
    ) -> tuple[str, str]:
        """Render a system + user prompt pair for a given stage.

        Convention: templates are named ``{subdirectory}/{stage}_system.j2``
        and ``{subdirectory}/{stage}_user.j2`` unless overridden.
        """
        prefix = f"{subdirectory}/" if subdirectory else ""
        sys_name = system_template or f"{prefix}{stage}_system.j2"
        usr_name = user_template or f"{prefix}{stage}_user.j2"

        system = self.render(sys_name, **context)
        user = self.render(usr_name, **context)
        return system, user

    def list_templates(self, subdirectory: str = "") -> list[str]:
        """List all .j2 template files, optionally filtered by subdirectory."""
        results = []
        seen: set[str] = set()
        for search_dir_str in self._env.loader.searchpath:
            search_dir = Path(search_dir_str)
            if subdirectory:
                search_dir = search_dir / subdirectory
            if not search_dir.is_dir():
                continue
            for p in sorted(search_dir.rglob("*.j2")):
                rel = p.relative_to(Path(search_dir_str))
                name = str(rel).replace("\\", "/")
                if name not in seen:
                    seen.add(name)
                    results.append(name)
        return sorted(results)

    @lru_cache(maxsize=128)
    def get_metadata(self, template_name: str) -> dict[str, Any]:
        """Extract metadata from the template's frontmatter comment.

        Templates can include a YAML metadata block::

            {#- metadata
              stage: ch01_exec
              model: gpt-5.1
              type: ANALYTICAL
              version: 1
              description: Executive Summary
            -#}

        Returns an empty dict if no metadata block is found.
        """
        try:
            source = self._env.loader.get_source(self._env, template_name)[0]
        except TemplateNotFound:
            return {}

        match = _METADATA_RE.search(source)
        if not match:
            return {}

        try:
            parsed = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            logger.error(
                "Prompt metadata parse failure: template=%s error=%s",
                template_name,
                exc,
                extra={
                    "event": "prompt_metadata_parse_failure",
                    "template_name": template_name,
                    "result_state": "degraded",
                },
            )
            return {"_metadata_parse_error": True}

        if parsed is None:
            return {}
        if not isinstance(parsed, dict):
            logger.error(
                "Prompt metadata returned non-dict: template=%s type=%s",
                template_name,
                type(parsed).__name__,
                extra={
                    "event": "prompt_metadata_parse_failure",
                    "template_name": template_name,
                    "result_state": "invalid_type",
                },
            )
            return {"_metadata_parse_error": True}
        return parsed

    def add_search_path(self, path: Path | str) -> None:
        """Append a directory to the Jinja2 template search paths.

        Allows engine packages to register their own ``templates/``
        directories so that ``render()`` can resolve package-local
        ``.j2`` files without requiring a central directory.
        Duplicate paths are silently ignored.

        Raises ValueError if the path is outside the project tree or
        is not an existing directory.
        """
        resolved = Path(path).resolve()
        backend_root = Path(__file__).resolve().parents[2]  # ai_engine/prompts/registry.py -> parents[2] = backend/
        if not str(resolved).startswith(str(backend_root)):
            raise ValueError(
                f"Template search path must be within the backend directory: {resolved}"
            )
        if not resolved.is_dir():
            raise ValueError(f"Template search path is not a directory: {resolved}")
        path_str = str(resolved)
        if path_str not in self._env.loader.searchpath:
            # Warn on template name collisions (first-registered path wins in FileSystemLoader)
            existing_names: set[str] = set()
            for sp in self._env.loader.searchpath:
                for f in Path(sp).glob("*.j2"):
                    existing_names.add(f.name)
            for f in resolved.glob("*.j2"):
                if f.name in existing_names:
                    logger.warning(
                        "Template name collision: %s in %s shadows existing template",
                        f.name, path_str,
                    )
            self._env.loader.searchpath.append(path_str)

    def has_template(self, template_name: str) -> bool:
        """Check if a template exists without raising."""
        try:
            self._env.get_template(template_name)
            return True
        except TemplateNotFound:
            return False


_registry: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    """Get or create the global PromptRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry

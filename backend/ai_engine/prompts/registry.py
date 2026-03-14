"""Prompt Template Registry — Jinja2-based prompt management.

Centralizes all AI prompt templates with:
- Jinja2 rendering with variable interpolation
- Template metadata extraction from frontmatter comments
- Multi-application support via configurable prompt sets
- LRU caching of compiled templates
- Fail-fast on missing templates

Usage::

    from ai_engine.prompts import prompt_registry

    system = prompt_registry.render("intelligence/ch01_exec.j2", deal_name="ABC Corp")
    system, user = prompt_registry.render_pair("doc_review", question="...", chunks="...")
"""
from __future__ import annotations

import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import (  # pyright: ignore[reportMissingImports]
    Environment,
    FileSystemLoader,
    TemplateNotFound,
)

logger = logging.getLogger(__name__)

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

        self._env = Environment(
            loader=FileSystemLoader(search_paths),
            keep_trailing_newline=True,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        logger.info(
            "PromptRegistry initialized — base=%s prompt_set=%s search_paths=%s",
            self._base_dir, self._prompt_set or "(default)", search_paths,
        )

    def render(self, template_name: str, **context: Any) -> str:
        """Render a Jinja2 template with context variables.

        Args:
            template_name: Path relative to prompts dir (e.g. "intelligence/ch01_exec.j2")
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
        search_dir = self._base_dir / subdirectory if subdirectory else self._base_dir
        if not search_dir.is_dir():
            return results
        for p in sorted(search_dir.rglob("*.j2")):
            rel = p.relative_to(self._base_dir)
            results.append(str(rel).replace("\\", "/"))
        return results

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
            return yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            logger.warning("Invalid YAML metadata in template %s", template_name)
            return {}

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

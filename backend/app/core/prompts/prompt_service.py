"""
PromptService — Cascade Resolution + Admin Write for Prompt Templates (Phase E)
================================================================================

Resolution cascade:
  1. prompt_overrides WHERE organization_id = org_id (org-specific)
  2. prompt_overrides WHERE organization_id IS NULL (global override)
  3. Filesystem .j2 via PromptRegistry (fallback)

Write operations auto-version and create history rows.
Preview uses AdminSandboxedEnvironment with dunder blocking.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from jinja2 import TemplateSyntaxError
from jinja2.nodes import EvalContext
from jinja2.runtime import Context
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ai_engine.prompts.registry import get_prompt_registry
from app.core.prompts.schemas import (
    PromptContent,
    PromptInfo,
    PromptPreviewResponse,
    PromptValidateResponse,
    PromptVersionInfo,
)
from app.domains.admin.models import PromptOverride, PromptOverrideVersion

logger = logging.getLogger(__name__)

# Patterns that indicate SSTI attempts — block before rendering
_DANGEROUS_PATTERNS = re.compile(
    r"(__class__|__mro__|__subclasses__|__globals__|__builtins__|"
    r"__import__|__getattr__|__setattr__|__delattr__)",
    re.IGNORECASE,
)

# Safe filter whitelist for admin-edited prompts
_SAFE_FILTERS = frozenset({
    "upper", "lower", "title", "capitalize", "strip",
    "truncate", "default", "join", "replace", "round",
    "int", "float", "string", "list", "length",
    "first", "last", "sort", "reverse", "unique",
    "map", "select", "reject", "batch", "groupby",
    "trim", "wordcount", "e", "escape",
})

class AdminSandboxedEnvironment(SandboxedEnvironment):
    """Hardened sandbox for admin-edited prompts.

    Blocks dunder attribute access and restricts filters to whitelist.
    """

    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        if attr.startswith("__") or attr.endswith("__"):
            return False
        return super().is_safe_attribute(obj, attr, value)

    def call_filter(
        self,
        name: str,
        value: Any,
        args: Sequence[Any] | None = None,
        kwargs: Mapping[str, Any] | None = None,
        context: Context | None = None,
        eval_ctx: EvalContext | None = None,
    ) -> Any:
        if name not in _SAFE_FILTERS:
            from jinja2.exceptions import SecurityError

            raise SecurityError(f"Filter '{name}' is not allowed")
        return super().call_filter(name, value, args, kwargs, context, eval_ctx)


def _create_sandbox() -> AdminSandboxedEnvironment:
    """Create a one-shot sandbox for rendering admin prompts."""
    env = AdminSandboxedEnvironment(
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
    )
    # Strip non-whitelisted filters from the environment so compiled
    # templates (which access env.filters directly) cannot use them.
    env.filters = {k: v for k, v in env.filters.items() if k in _SAFE_FILTERS}
    return env


class PromptService:
    """Prompt management with cascade resolution and admin write."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(
        self,
        vertical: str,
        template_name: str,
        org_id: UUID | None = None,
    ) -> PromptContent:
        """Resolve prompt content using cascade: org > global > filesystem."""
        # Level 1: org-specific override
        if org_id is not None:
            row = await self._db.execute(
                select(PromptOverride).where(
                    PromptOverride.vertical == vertical,
                    PromptOverride.template_name == template_name,
                    PromptOverride.organization_id == org_id,
                )
            )
            override = row.scalar_one_or_none()
            if override is not None:
                return PromptContent(
                    vertical=vertical,
                    template_name=template_name,
                    content=override.content,
                    source_level="org",
                    version=override.version,
                )

        # Level 2: global override (org_id IS NULL)
        row = await self._db.execute(
            select(PromptOverride).where(
                PromptOverride.vertical == vertical,
                PromptOverride.template_name == template_name,
                PromptOverride.organization_id.is_(None),
            )
        )
        global_override = row.scalar_one_or_none()
        if global_override is not None:
            return PromptContent(
                vertical=vertical,
                template_name=template_name,
                content=global_override.content,
                source_level="global",
                version=global_override.version,
            )

        # Level 3: filesystem .j2
        registry = get_prompt_registry()
        if registry.has_template(template_name):
            content = registry.render(template_name)
            return PromptContent(
                vertical=vertical,
                template_name=template_name,
                content=content,
                source_level="filesystem",
                version=None,
            )

        # Not found anywhere
        return PromptContent(
            vertical=vertical,
            template_name=template_name,
            content="",
            source_level="filesystem",
            version=None,
        )

    async def put(
        self,
        vertical: str,
        template_name: str,
        content: str,
        updated_by: str,
        org_id: UUID | None = None,
    ) -> int:
        """Write prompt override. Auto-bumps version, writes history row.

        Returns new version number.
        """
        # Validate content first
        validation = self.validate(content)
        if not validation.valid:
            raise ValueError(f"Invalid template: {'; '.join(validation.errors)}")

        # Find existing override
        existing = await self._db.execute(
            select(PromptOverride).where(
                PromptOverride.vertical == vertical,
                PromptOverride.template_name == template_name,
                PromptOverride.organization_id == org_id
                if org_id is not None
                else PromptOverride.organization_id.is_(None),
            )
        )
        row = existing.scalar_one_or_none()

        if row is not None:
            # Update existing — bump version
            new_version = row.version + 1
            row.content = content
            row.version = new_version
            row.updated_by = updated_by
        else:
            # Create new override
            new_version = 1
            row = PromptOverride(
                organization_id=org_id,
                vertical=vertical,
                template_name=template_name,
                content=content,
                version=new_version,
                updated_by=updated_by,
            )
            self._db.add(row)

        # Flush to get the row ID for the version history FK
        await self._db.flush()

        # Write version history
        version_row = PromptOverrideVersion(
            prompt_override_id=row.id,
            version=new_version,
            content=content,
            updated_by=updated_by,
        )
        self._db.add(version_row)

        return new_version

    async def list_templates(
        self,
        vertical: str,
        org_id: UUID | None = None,
    ) -> list[PromptInfo]:
        """List all templates with override status.

        Combines filesystem templates with DB overrides.
        """
        # Get filesystem templates
        registry = get_prompt_registry()
        fs_templates = registry.list_templates()

        # Get all org overrides
        org_override_names: set[str] = set()
        if org_id is not None:
            result = await self._db.execute(
                select(PromptOverride.template_name).where(
                    PromptOverride.vertical == vertical,
                    PromptOverride.organization_id == org_id,
                )
            )
            org_override_names = {r[0] for r in result.all()}

        # Get all global overrides
        result = await self._db.execute(
            select(PromptOverride.template_name).where(
                PromptOverride.vertical == vertical,
                PromptOverride.organization_id.is_(None),
            )
        )
        global_override_names = {r[0] for r in result.all()}

        # Combine: filesystem + any DB-only overrides
        all_names = set(fs_templates) | org_override_names | global_override_names
        infos: list[PromptInfo] = []

        for name in sorted(all_names):
            has_org = name in org_override_names
            has_global = name in global_override_names

            # Determine source level
            if has_org:
                source = "org"
            elif has_global:
                source = "global"
            else:
                source = "filesystem"

            # Get metadata from filesystem if available
            metadata = registry.get_metadata(name) if name in fs_templates else {}

            infos.append(
                PromptInfo(
                    vertical=vertical,
                    template_name=name,
                    description=metadata.get("description"),
                    has_org_override=has_org,
                    has_global_override=has_global,
                    source_level=source,
                )
            )

        return infos

    @staticmethod
    def preview(
        content: str,
        sample_data: dict[str, Any],
    ) -> PromptPreviewResponse:
        """Render template content with sample data using hardened sandbox.

        Returns rendered output or error messages.
        """
        # Check for dangerous patterns
        if _DANGEROUS_PATTERNS.search(content):
            return PromptPreviewResponse(
                rendered="",
                errors=["Template contains forbidden patterns (dunder access)"],
            )

        try:
            env = _create_sandbox()
            template = env.from_string(content)
            rendered = template.render(**sample_data)
            return PromptPreviewResponse(rendered=rendered)
        except TemplateSyntaxError as e:
            return PromptPreviewResponse(
                rendered="",
                errors=[f"Syntax error at line {e.lineno}: {e.message}"],
            )
        except Exception as e:
            return PromptPreviewResponse(
                rendered="",
                errors=[f"Render error: {e!s}"],
            )

    @staticmethod
    def validate(content: str) -> PromptValidateResponse:
        """Validate Jinja2 template syntax.

        Returns validation result with any syntax errors.
        """
        errors: list[str] = []

        # Check dangerous patterns
        if _DANGEROUS_PATTERNS.search(content):
            errors.append("Template contains forbidden patterns (dunder access)")

        # Parse template
        try:
            env = _create_sandbox()
            env.parse(content)
        except TemplateSyntaxError as e:
            errors.append(f"Syntax error at line {e.lineno}: {e.message}")

        return PromptValidateResponse(valid=len(errors) == 0, errors=errors)

    async def get_versions(
        self,
        vertical: str,
        template_name: str,
        org_id: UUID | None = None,
    ) -> list[PromptVersionInfo]:
        """Get version history for a prompt override."""
        result = await self._db.execute(
            select(PromptOverride)
            .options(selectinload(PromptOverride.versions))
            .where(
                PromptOverride.vertical == vertical,
                PromptOverride.template_name == template_name,
                PromptOverride.organization_id == org_id
                if org_id is not None
                else PromptOverride.organization_id.is_(None),
            )
        )
        override = result.scalar_one_or_none()
        if override is None:
            return []

        return [
            PromptVersionInfo.model_validate(v)
            for v in sorted(override.versions, key=lambda v: v.version, reverse=True)
        ]

    async def delete_override(
        self,
        vertical: str,
        template_name: str,
        org_id: UUID | None = None,
    ) -> bool:
        """Delete a prompt override (revert to next cascade level).

        Returns True if an override was deleted.
        """
        result = await self._db.execute(
            select(PromptOverride).where(
                PromptOverride.vertical == vertical,
                PromptOverride.template_name == template_name,
                PromptOverride.organization_id == org_id
                if org_id is not None
                else PromptOverride.organization_id.is_(None),
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False

        await self._db.delete(row)
        return True

    @staticmethod
    def snapshot_prompts(
        prompts: list[PromptContent],
    ) -> dict[str, str]:
        """Create frozen prompt dict for job-start snapshot.

        Prevents mid-generation inconsistency when prompts are updated
        while a job is running.
        """
        return {p.template_name: p.content for p in prompts}

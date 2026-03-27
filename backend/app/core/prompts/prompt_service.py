"""PromptService — Admin prompt management with cascade resolution.

Resolution cascade:
  1. prompt_overrides WHERE organization_id = org_id (org-specific)
  2. prompt_overrides WHERE organization_id IS NULL (global override)
  3. Filesystem .j2 via PromptRegistry (fallback)

Security: HardenedPromptEnvironment for preview rendering.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any
from uuid import UUID

from jinja2 import Environment, TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.admin.models import AdminAuditLog, PromptOverride, PromptOverrideVersion

logger = logging.getLogger(__name__)

# ── Template directories ─────────────────────────────────────────
# ai_engine/prompts/ contains extraction/ templates
# vertical_engines/{vertical}/prompts/ contains vertical-specific templates

_BACKEND_DIR = Path(__file__).resolve().parents[3]  # backend/
_AI_ENGINE_PROMPTS_DIR = _BACKEND_DIR / "ai_engine" / "prompts"
_VERTICAL_ENGINES_DIR = _BACKEND_DIR / "vertical_engines"

# ── Dangerous pattern detection ──────────────────────────────────

_DANGEROUS_PATTERNS = re.compile(
    r"(__)|"
    r"(import\s)|"
    r"(os\.)|"
    r"(subprocess)|"
    r"(\beval\b)|"
    r"(\bexec\b)|"
    r"(\bgetattr\b)|"
    r"(\blipsum\b)",
    re.IGNORECASE,
)

# ── HardenedPromptEnvironment ────────────────────────────────────

_BLOCKED_ATTRS: frozenset[str] = frozenset({
    "__subclasses__", "__bases__", "__mro__", "__base__",
    "__globals__", "__builtins__", "__import__", "__loader__",
    "__spec__", "__code__", "__func__", "gi_frame", "gi_code",
    "f_globals", "f_builtins", "co_consts", "co_names",
})

_ALLOWED_FILTERS: frozenset[str] = frozenset({
    "default", "upper", "lower", "title", "trim", "round",
    "int", "float", "length", "join", "sort", "reverse",
    "e", "escape", "string", "list",
})


class HardenedPromptEnvironment(SandboxedEnvironment):
    """Jinja2 sandbox hardened against SSTI bypass vectors."""

    def is_safe_attribute(self, obj: Any, attr: str, value: Any) -> bool:
        if attr in _BLOCKED_ATTRS:
            return False
        return super().is_safe_attribute(obj, attr, value)

    def is_safe_callable(self, obj: Any) -> bool:
        # Block all callables in templates
        return False

    def call_binop(self, context: Any, operator: str, left: Any, right: Any) -> Any:
        # Block string % operator (format string exploitation)
        if operator == "%" and isinstance(left, str):
            raise SecurityError("String format operator blocked")
        return super().call_binop(context, operator, left, right)


class SecurityError(Exception):
    """Raised when a template contains blocked patterns."""



def _create_hardened_env() -> HardenedPromptEnvironment:
    """Create a hardened Jinja2 environment for preview rendering."""
    env = HardenedPromptEnvironment(
        autoescape=True,
        extensions=[],
    )
    # Remove all filters except allowed
    for name in list(env.filters.keys()):
        if name not in _ALLOWED_FILTERS:
            del env.filters[name]
    return env


# ── Sample data validation ───────────────────────────────────────

_MAX_SAMPLE_DEPTH = 5
_MAX_SAMPLE_SIZE = 65536  # 64KB


def _validate_sample_data(data: Any, depth: int = 0) -> list[str]:
    """Recursively validate that sample data contains only JSON-primitive types."""
    errors: list[str] = []
    if depth > _MAX_SAMPLE_DEPTH:
        errors.append(f"Sample data exceeds max depth ({_MAX_SAMPLE_DEPTH})")
        return errors

    if isinstance(data, dict):
        for key, value in data.items():
            if not isinstance(key, str):
                errors.append(f"Dict key must be string, got {type(key).__name__}")
            errors.extend(_validate_sample_data(value, depth + 1))
    elif isinstance(data, list):
        for item in data:
            errors.extend(_validate_sample_data(item, depth + 1))
    elif not isinstance(data, (str, int, float, bool, type(None))):
        errors.append(f"Invalid type in sample data: {type(data).__name__}")

    return errors


def _hash_content(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()[:16]


def _find_filesystem_template(vertical: str, template_name: str) -> Path | None:
    """Locate a .j2 template on the filesystem.

    Search order:
      1. vertical_engines/{vertical}/prompts/{template_name}.j2
      2. vertical_engines/{vertical}/prompts/**/{template_name}.j2 (subdirectories)
      3. ai_engine/prompts/{template_name}.j2
      4. ai_engine/prompts/**/{template_name}.j2 (subdirectories like extraction/)
    """
    # Vertical-specific prompts
    vertical_prompts = _VERTICAL_ENGINES_DIR / vertical / "prompts"
    if vertical_prompts.is_dir():
        direct = vertical_prompts / f"{template_name}.j2"
        if direct.exists():
            return direct
        # Check subdirectories
        for path in vertical_prompts.rglob(f"{template_name}.j2"):
            return path

    # AI engine shared prompts
    direct = _AI_ENGINE_PROMPTS_DIR / f"{template_name}.j2"
    if direct.exists():
        return direct
    for path in _AI_ENGINE_PROMPTS_DIR.rglob(f"{template_name}.j2"):
        return path

    return None


def _list_filesystem_templates(vertical: str) -> dict[str, dict]:
    """Scan filesystem for all .j2 templates belonging to a vertical.

    Returns dict keyed by template stem name.
    """
    templates: dict[str, dict] = {}

    # Vertical-specific prompts
    vertical_prompts = _VERTICAL_ENGINES_DIR / vertical / "prompts"
    if vertical_prompts.is_dir():
        for path in sorted(vertical_prompts.rglob("*.j2")):
            rel = path.relative_to(vertical_prompts)
            # Use stem for flat files, parent/stem for nested
            if len(rel.parts) == 1:
                name = path.stem
            else:
                name = str(rel.with_suffix("")).replace("\\", "/")
            templates[name] = {
                "template_name": name,
                "description": f"{vertical}/{name} template",
                "source_level": "filesystem",
                "version": None,
                "has_override": False,
            }

    # Also include ai_engine shared prompts (extraction/ etc.)
    if _AI_ENGINE_PROMPTS_DIR.is_dir():
        for path in sorted(_AI_ENGINE_PROMPTS_DIR.rglob("*.j2")):
            rel = path.relative_to(_AI_ENGINE_PROMPTS_DIR)
            if len(rel.parts) == 1:
                name = path.stem
            else:
                name = str(rel.with_suffix("")).replace("\\", "/")
            if name not in templates:
                templates[name] = {
                    "template_name": name,
                    "description": f"shared/{name} template",
                    "source_level": "filesystem",
                    "version": None,
                    "has_override": False,
                }

    return templates


# ── PromptService ────────────────────────────────────────────────


class PromptService:
    """Admin prompt management with cascade resolution and hardened preview."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(
        self,
        vertical: str,
        template_name: str,
        org_id: UUID | None = None,
    ) -> dict:
        """Resolve prompt content via cascade.

        Returns {content, source_level, version}.
        """
        # Level 1: org-specific override
        if org_id is not None:
            row = await self._db.execute(
                select(PromptOverride).where(
                    PromptOverride.vertical == vertical,
                    PromptOverride.template_name == template_name,
                    PromptOverride.organization_id == org_id,
                ),
            )
            override = row.scalar_one_or_none()
            if override:
                return {
                    "content": override.content,
                    "source_level": "org",
                    "version": override.version,
                }

        # Level 2: global override (org_id IS NULL)
        row = await self._db.execute(
            select(PromptOverride).where(
                PromptOverride.vertical == vertical,
                PromptOverride.template_name == template_name,
                PromptOverride.organization_id.is_(None),
            ),
        )
        global_override = row.scalar_one_or_none()
        if global_override:
            return {
                "content": global_override.content,
                "source_level": "global",
                "version": global_override.version,
            }

        # Level 3: filesystem .j2 fallback
        template_path = _find_filesystem_template(vertical, template_name)
        if template_path is not None:
            return {
                "content": template_path.read_text(encoding="utf-8"),
                "source_level": "filesystem",
                "version": None,
            }

        return {
            "content": "",
            "source_level": "missing",
            "version": None,
        }

    async def put(
        self,
        vertical: str,
        template_name: str,
        org_id: UUID | None,
        content: str,
        actor_id: str,
        change_summary: str | None = None,
    ) -> dict:
        """Write prompt override, bump version, write history row."""
        # Pre-save validation
        errors = self.validate_content(content)
        if errors:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Template validation failed: {'; '.join(errors)}",
            )

        # Find existing override
        row = await self._db.execute(
            select(PromptOverride)
            .options(selectinload(PromptOverride.versions))
            .where(
                PromptOverride.vertical == vertical,
                PromptOverride.template_name == template_name,
                PromptOverride.organization_id == org_id
                if org_id
                else PromptOverride.organization_id.is_(None),
            ),
        )
        existing = row.scalar_one_or_none()

        before_hash = _hash_content(existing.content) if existing else None
        after_hash = _hash_content(content)

        if existing:
            new_version = existing.version + 1
            existing.content = content
            existing.version = new_version
            existing.updated_by = actor_id
            # Write version history
            existing.versions.append(
                PromptOverrideVersion(
                    version=new_version,
                    content=content,
                    updated_by=actor_id,
                    change_summary=change_summary,
                ),
            )
        else:
            new_version = 1
            override = PromptOverride(
                vertical=vertical,
                template_name=template_name,
                organization_id=org_id,
                content=content,
                version=new_version,
                updated_by=actor_id,
            )
            override.versions = [
                PromptOverrideVersion(
                    version=new_version,
                    content=content,
                    updated_by=actor_id,
                    change_summary=change_summary,
                ),
            ]
            self._db.add(override)

        # Audit log
        self._db.add(
            AdminAuditLog(
                actor_id=actor_id,
                action="prompt.update",
                resource_type="prompt",
                resource_id=f"{vertical}/{template_name}",
                target_org_id=org_id,
                before_hash=before_hash,
                after_hash=after_hash,
            ),
        )

        return {"template_name": template_name, "version": new_version}

    async def list_templates(
        self,
        vertical: str,
        org_id: UUID | None = None,
    ) -> list[dict]:
        """List all templates with override status."""
        templates = _list_filesystem_templates(vertical)

        # Scan global overrides
        row = await self._db.execute(
            select(PromptOverride).where(
                PromptOverride.vertical == vertical,
                PromptOverride.organization_id.is_(None),
            ),
        )
        for override in row.scalars().all():
            key = override.template_name
            if key in templates:
                templates[key]["source_level"] = "global"
                templates[key]["version"] = override.version
                templates[key]["has_override"] = True
            else:
                templates[key] = {
                    "template_name": key,
                    "description": f"{vertical}/{key} template (global override)",
                    "source_level": "global",
                    "version": override.version,
                    "has_override": True,
                }

        # Scan org overrides
        if org_id:
            row = await self._db.execute(
                select(PromptOverride).where(
                    PromptOverride.vertical == vertical,
                    PromptOverride.organization_id == org_id,
                ),
            )
            for override in row.scalars().all():
                key = override.template_name
                if key in templates:
                    templates[key]["source_level"] = "org"
                    templates[key]["version"] = override.version
                    templates[key]["has_override"] = True
                else:
                    templates[key] = {
                        "template_name": key,
                        "description": f"{vertical}/{key} template (org override)",
                        "source_level": "org",
                        "version": override.version,
                        "has_override": True,
                    }

        return list(templates.values())

    def preview(
        self,
        content: str,
        sample_data: dict,
    ) -> dict:
        """Render template with HardenedPromptEnvironment. Returns {rendered, errors}."""
        # Validate content length
        if len(content) > 51200:
            return {"rendered": "", "errors": ["Template exceeds 50KB limit"]}

        # Validate sample data
        sample_errors = _validate_sample_data(sample_data)
        if sample_errors:
            return {"rendered": "", "errors": sample_errors}

        # Check total size
        sample_json = json.dumps(sample_data)
        if len(sample_json) > _MAX_SAMPLE_SIZE:
            return {
                "rendered": "",
                "errors": [f"Sample data exceeds {_MAX_SAMPLE_SIZE} bytes"],
            }

        env = _create_hardened_env()

        try:
            template = env.from_string(content)
        except TemplateSyntaxError as e:
            return {"rendered": "", "errors": [f"Syntax error: {e.message}"]}

        # Render with timeout (5s via ThreadPoolExecutor — Windows compat)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(template.render, **sample_data)
                rendered = future.result(timeout=5.0)
            return {"rendered": rendered, "errors": []}
        except concurrent.futures.TimeoutError:
            return {
                "rendered": "",
                "errors": ["Template rendering timed out (5s limit)"],
            }
        except (SecurityError, UndefinedError) as e:
            return {"rendered": "", "errors": [f"Security violation: {e}"]}
        except Exception as e:
            return {"rendered": "", "errors": [f"Render error: {e}"]}

    @staticmethod
    def validate_content(content: str) -> list[str]:
        """Validate template content for dangerous patterns and syntax."""
        errors: list[str] = []

        if len(content) > 51200:
            errors.append("Template exceeds 50KB limit")
            return errors

        # Pre-save regex check for dangerous patterns
        if _DANGEROUS_PATTERNS.search(content):
            matches = _DANGEROUS_PATTERNS.findall(content)
            flat = [m for group in matches for m in group if m]
            errors.append(f"Dangerous patterns detected: {', '.join(set(flat))}")

        # Jinja2 syntax check
        try:
            env = Environment()
            env.parse(content)
        except TemplateSyntaxError as e:
            errors.append(f"Jinja2 syntax error: {e.message}")

        return errors

    async def get_versions(
        self,
        vertical: str,
        template_name: str,
        org_id: UUID | None = None,
        limit: int = 50,
    ) -> dict:
        """Get version history for a prompt override. Paginated (last 50)."""
        query = select(PromptOverride).where(
            PromptOverride.vertical == vertical,
            PromptOverride.template_name == template_name,
        )
        if org_id:
            query = query.where(PromptOverride.organization_id == org_id)
        else:
            query = query.where(PromptOverride.organization_id.is_(None))

        row = await self._db.execute(query)
        override = row.scalar_one_or_none()
        if override is None:
            return {"versions": [], "has_more": False}

        # Get versions ordered by version desc
        versions_query = (
            select(PromptOverrideVersion)
            .where(PromptOverrideVersion.prompt_override_id == override.id)
            .order_by(PromptOverrideVersion.version.desc())
            .limit(limit + 1)
        )
        versions_row = await self._db.execute(versions_query)
        versions = list(versions_row.scalars().all())

        has_more = len(versions) > limit
        versions = versions[:limit]

        return {
            "versions": [
                {
                    "id": v.id,
                    "version": v.version,
                    "content": v.content,
                    "updated_by": v.updated_by,
                    "actor_id": v.updated_by,
                    "change_summary": v.change_summary,
                    "created_at": v.created_at.isoformat() if v.created_at else None,
                }
                for v in versions
            ],
            "has_more": has_more,
        }

    async def revert_to_version(
        self,
        vertical: str,
        template_name: str,
        target_version: int,
        org_id: UUID | None,
        actor_id: str,
    ) -> dict:
        """Revert prompt to a specific version."""
        # Get the override
        query = (
            select(PromptOverride)
            .options(selectinload(PromptOverride.versions))
            .where(
                PromptOverride.vertical == vertical,
                PromptOverride.template_name == template_name,
            )
        )
        if org_id:
            query = query.where(PromptOverride.organization_id == org_id)
        else:
            query = query.where(PromptOverride.organization_id.is_(None))

        row = await self._db.execute(query)
        override = row.scalar_one_or_none()
        if override is None:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Prompt override not found",
            )

        # Find target version
        version_row = await self._db.execute(
            select(PromptOverrideVersion).where(
                PromptOverrideVersion.prompt_override_id == override.id,
                PromptOverrideVersion.version == target_version,
            ),
        )
        target = version_row.scalar_one_or_none()
        if target is None:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {target_version} not found",
            )

        # Create new version with reverted content
        return await self.put(vertical, template_name, org_id, target.content, actor_id)

    async def delete_override(
        self,
        vertical: str,
        template_name: str,
        org_id: UUID | None,
        actor_id: str,
    ) -> None:
        """Delete prompt override — falls back to next cascade level."""
        query = select(PromptOverride).where(
            PromptOverride.vertical == vertical,
            PromptOverride.template_name == template_name,
        )
        if org_id:
            query = query.where(PromptOverride.organization_id == org_id)
        else:
            query = query.where(PromptOverride.organization_id.is_(None))

        row = await self._db.execute(query)
        existing = row.scalar_one_or_none()
        if existing is None:
            from fastapi import HTTPException, status

            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No override to delete",
            )

        before_hash = _hash_content(existing.content)

        # Delete (cascade deletes versions)
        await self._db.delete(existing)

        # Audit
        self._db.add(
            AdminAuditLog(
                actor_id=actor_id,
                action="prompt.delete",
                resource_type="prompt",
                resource_id=f"{vertical}/{template_name}",
                target_org_id=org_id,
                before_hash=before_hash,
                after_hash=None,
            ),
        )

    @staticmethod
    def snapshot_prompts(
        resolved_prompts: dict[str, dict],
    ) -> dict[str, str]:
        """Freeze resolved prompts at job start. Returns {template_name: content}."""
        return {name: data["content"] for name, data in resolved_prompts.items()}

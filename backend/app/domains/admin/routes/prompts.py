"""Admin prompt management routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.prompts.prompt_service import PromptService
from app.core.prompts.schemas import PromptPreviewRequest
from app.core.security.admin_auth import require_super_admin
from app.core.security.clerk_auth import Actor
from app.core.tenancy.admin_middleware import get_db_admin_read

router = APIRouter(
    prefix="/admin/prompts",
    tags=["admin-prompts"],
    dependencies=[Depends(require_super_admin)],
)


@router.get("/{vertical}")
async def list_prompts(
    vertical: str,
    org_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db_admin_read),
    actor: Actor = Depends(require_super_admin),
):
    """List all templates with override status."""
    svc = PromptService(db)
    return await svc.list_templates(vertical, org_id)


@router.get("/{vertical}/{name}")
async def get_prompt(
    vertical: str,
    name: str,
    org_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db_admin_read),
    actor: Actor = Depends(require_super_admin),
):
    """Get resolved prompt content + source level."""
    svc = PromptService(db)
    return await svc.get(vertical, name, org_id)


@router.put("/{vertical}/{name}")
async def update_prompt(
    vertical: str,
    name: str,
    body: dict,
    org_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db_admin_read),
    actor: Actor = Depends(require_super_admin),
):
    """Update prompt override (auto-version, history)."""
    content = body.get("content", "")
    svc = PromptService(db)
    return await svc.put(vertical, name, org_id, content, actor.actor_id)


@router.delete("/{vertical}/{name}")
async def delete_prompt(
    vertical: str,
    name: str,
    org_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db_admin_read),
    actor: Actor = Depends(require_super_admin),
):
    """Delete prompt override -- falls back to next cascade level."""
    svc = PromptService(db)
    await svc.delete_override(vertical, name, org_id, actor.actor_id)
    return {"status": "deleted"}


@router.post("/{vertical}/{name}/preview")
async def preview_prompt(
    vertical: str,
    name: str,
    body: PromptPreviewRequest,
    actor: Actor = Depends(require_super_admin),
):
    """Render with sample data (sandboxed HardenedPromptEnvironment)."""
    svc = PromptService.__new__(PromptService)  # No DB needed for preview
    return svc.preview(body.content, body.sample_data)


@router.post("/{vertical}/{name}/validate")
async def validate_prompt(
    vertical: str,
    name: str,
    body: dict,
    actor: Actor = Depends(require_super_admin),
):
    """Jinja2 syntax check + dangerous pattern detection."""
    content = body.get("content", "")
    errors = PromptService.validate_content(content)
    return {"valid": len(errors) == 0, "errors": errors}


@router.get("/{vertical}/{name}/versions")
async def get_versions(
    vertical: str,
    name: str,
    org_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db_admin_read),
    actor: Actor = Depends(require_super_admin),
):
    """Version history (last 50, paginated)."""
    svc = PromptService(db)
    return await svc.get_versions(vertical, name, org_id)


@router.post("/{vertical}/{name}/revert/{version}")
async def revert_prompt(
    vertical: str,
    name: str,
    version: int,
    org_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db_admin_read),
    actor: Actor = Depends(require_super_admin),
):
    """Revert to a specific version."""
    svc = PromptService(db)
    return await svc.revert_to_version(vertical, name, version, org_id, actor.actor_id)

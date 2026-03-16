"""Admin prompt routes — Prompt management with cascade resolution.

All routes require ADMIN role.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.prompts.dependencies import get_prompt_service
from app.core.prompts.prompt_service import PromptService
from app.core.prompts.schemas import (
    PromptContent,
    PromptInfo,
    PromptPreviewRequest,
    PromptPreviewResponse,
    PromptUpdate,
    PromptValidateResponse,
    PromptVersionInfo,
    PromptWriteResponse,
)
from app.core.security.clerk_auth import Actor, require_role
from app.shared.enums import Role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/prompts", tags=["admin-prompts"])


@router.get(
    "/{vertical}",
    response_model=list[PromptInfo],
    summary="List all prompt templates for a vertical",
    description="Returns all templates with override status per org.",
)
async def list_prompts(
    vertical: str,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    prompt_service: PromptService = Depends(get_prompt_service),
) -> list[PromptInfo]:
    return await prompt_service.list_templates(
        vertical=vertical,
        org_id=actor.organization_id,
    )


@router.get(
    "/{vertical}/{name:path}",
    response_model=PromptContent,
    summary="Get resolved prompt content",
    description="Returns content + source level (org/global/filesystem).",
)
async def get_prompt(
    vertical: str,
    name: str,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    prompt_service: PromptService = Depends(get_prompt_service),
) -> PromptContent:
    return await prompt_service.get(
        vertical=vertical,
        template_name=name,
        org_id=actor.organization_id,
    )


@router.put(
    "/{vertical}/{name:path}",
    response_model=PromptWriteResponse,
    summary="Update prompt override",
    description="Auto-versions and writes history row.",
)
async def update_prompt(
    vertical: str,
    name: str,
    payload: PromptUpdate,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    prompt_service: PromptService = Depends(get_prompt_service),
) -> PromptWriteResponse:
    try:
        version = await prompt_service.put(
            vertical=vertical,
            template_name=name,
            content=payload.content,
            updated_by=actor.actor_id,
            org_id=actor.organization_id,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    return PromptWriteResponse(version=version, message="Prompt override updated")


@router.delete(
    "/{vertical}/{name:path}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete prompt override (revert to next cascade level)",
)
async def delete_prompt(
    vertical: str,
    name: str,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    prompt_service: PromptService = Depends(get_prompt_service),
) -> None:
    deleted = await prompt_service.delete_override(
        vertical=vertical,
        template_name=name,
        org_id=actor.organization_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No override found",
        )


@router.post(
    "/{vertical}/{name:path}/preview",
    response_model=PromptPreviewResponse,
    summary="Preview prompt with sample data",
    description="Renders template content against sample data using hardened sandbox.",
)
async def preview_prompt(
    vertical: str,
    name: str,
    payload: PromptPreviewRequest,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    prompt_service: PromptService = Depends(get_prompt_service),
) -> PromptPreviewResponse:
    return prompt_service.preview(
        content=payload.content,
        sample_data=payload.sample_data,
    )


@router.post(
    "/{vertical}/{name:path}/validate",
    response_model=PromptValidateResponse,
    summary="Validate Jinja2 template syntax",
)
async def validate_prompt(
    vertical: str,
    name: str,
    payload: PromptUpdate,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    prompt_service: PromptService = Depends(get_prompt_service),
) -> PromptValidateResponse:
    return prompt_service.validate(content=payload.content)


@router.get(
    "/{vertical}/{name:path}/versions",
    response_model=list[PromptVersionInfo],
    summary="Get prompt version history",
)
async def get_prompt_versions(
    vertical: str,
    name: str,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    prompt_service: PromptService = Depends(get_prompt_service),
) -> list[PromptVersionInfo]:
    return await prompt_service.get_versions(
        vertical=vertical,
        template_name=name,
        org_id=actor.organization_id,
    )

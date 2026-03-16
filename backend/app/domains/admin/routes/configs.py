"""Admin config routes — CRUD for config overrides.

All routes require ADMIN role.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config.config_service import ConfigService
from app.core.config.config_writer import ConfigWriter, GuardrailViolation, StaleVersionError
from app.core.config.config_writer_deps import get_config_writer
from app.core.config.dependencies import get_config_service
from app.core.config.schemas import ConfigEntry
from app.core.security.clerk_auth import Actor, require_role
from app.domains.admin.schemas import (
    ConfigDefaultWriteRequest,
    ConfigDiffResponse,
    ConfigWriteRequest,
    ConfigWriteResponse,
)
from app.shared.enums import Role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/configs", tags=["admin-configs"])


@router.get(
    "",
    response_model=list[ConfigEntry],
    summary="List all config types",
    description="List all config types for a vertical with override status.",
)
async def list_configs(
    vertical: str,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    config_service: ConfigService = Depends(get_config_service),
) -> list[ConfigEntry]:
    return await config_service.list_configs(
        vertical=vertical,
        org_id=actor.organization_id,
        is_admin=True,
    )


@router.post(
    "",
    response_model=ConfigWriteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create config override",
)
async def create_config_override(
    payload: ConfigWriteRequest,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    writer: ConfigWriter = Depends(get_config_writer),
) -> ConfigWriteResponse:
    if actor.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organization",
        )
    try:
        version = await writer.put(
            vertical=payload.vertical,
            config_type=payload.config_type,
            org_id=actor.organization_id,
            config=payload.config,
            expected_version=payload.expected_version,
        )
    except GuardrailViolation as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Guardrail validation failed", "errors": e.errors},
        ) from e
    except StaleVersionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Config was modified by another user. Current version: {e.current_version}",
        ) from e

    return ConfigWriteResponse(
        vertical=payload.vertical,
        config_type=payload.config_type,
        version=version,
        message="Config override created/updated",
    )


@router.put(
    "/{vertical}/{config_type}",
    response_model=ConfigWriteResponse,
    summary="Update config override",
)
async def update_config_override(
    vertical: str,
    config_type: str,
    payload: ConfigWriteRequest,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    writer: ConfigWriter = Depends(get_config_writer),
) -> ConfigWriteResponse:
    if actor.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organization",
        )
    try:
        version = await writer.put(
            vertical=vertical,
            config_type=config_type,
            org_id=actor.organization_id,
            config=payload.config,
            expected_version=payload.expected_version,
        )
    except GuardrailViolation as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"message": "Guardrail validation failed", "errors": e.errors},
        ) from e
    except StaleVersionError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Config was modified by another user. Current version: {e.current_version}",
        ) from e

    return ConfigWriteResponse(
        vertical=vertical,
        config_type=config_type,
        version=version,
        message="Config override updated",
    )


@router.delete(
    "/{vertical}/{config_type}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove config override",
)
async def delete_config_override(
    vertical: str,
    config_type: str,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    writer: ConfigWriter = Depends(get_config_writer),
) -> None:
    if actor.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organization",
        )
    deleted = await writer.delete(
        vertical=vertical,
        config_type=config_type,
        org_id=actor.organization_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No override found",
        )


@router.get(
    "/{vertical}/{config_type}/diff",
    response_model=ConfigDiffResponse,
    summary="Show config diff (default vs override vs merged)",
)
async def get_config_diff(
    vertical: str,
    config_type: str,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    writer: ConfigWriter = Depends(get_config_writer),
) -> ConfigDiffResponse:
    if actor.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organization",
        )
    diff = await writer.diff(
        vertical=vertical,
        config_type=config_type,
        org_id=actor.organization_id,
    )
    return ConfigDiffResponse.model_validate(diff)


@router.post(
    "/defaults/{vertical}/{config_type}",
    response_model=ConfigWriteResponse,
    summary="Update global config default (super-admin only)",
)
async def update_config_default(
    vertical: str,
    config_type: str,
    payload: ConfigDefaultWriteRequest,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    writer: ConfigWriter = Depends(get_config_writer),
) -> ConfigWriteResponse:
    try:
        version = await writer.put_default(
            vertical=vertical,
            config_type=config_type,
            config=payload.config,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

    return ConfigWriteResponse(
        vertical=vertical,
        config_type=config_type,
        version=version,
        message="Global default config updated",
    )

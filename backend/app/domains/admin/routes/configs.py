"""Admin config management routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.config.registry import ConfigRegistry
from app.core.security.admin_auth import require_super_admin
from app.core.security.clerk_auth import Actor
from app.core.tenancy.admin_middleware import get_db_admin
from app.domains.admin.services.config_writer import ConfigWriter

router = APIRouter(
    prefix="/admin/configs",
    tags=["admin-configs"],
    dependencies=[Depends(require_super_admin)],
)


@router.get("/")
async def list_configs(
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """List all config types across verticals with override status."""
    svc = ConfigService(db)
    entries = []
    for vertical in ("liquid_funds", "private_credit"):
        items = await svc.list_configs(vertical, is_admin=True)
        entries.extend([
            {
                "vertical": item.vertical,
                "config_type": item.config_type,
                "has_override": item.has_override,
                "description": item.description,
            }
            for item in items
        ])
    return entries


@router.get("/invalid")
async def list_invalid_configs(
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """List overrides that fail current guardrails (drift detection)."""
    svc = ConfigService(db)
    return await svc.get_invalid_overrides()


@router.get("/{vertical}/{config_type}")
async def get_config(
    vertical: str,
    config_type: str,
    org_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Get merged config (default + override)."""
    if not ConfigRegistry.is_registered(vertical, config_type):
        raise HTTPException(
            status_code=400,
            detail=f"Unregistered config domain: ({vertical}, {config_type})",
        )
    svc = ConfigService(db)
    config = await svc.get(vertical, config_type, org_id)
    return {"config": config, "vertical": vertical, "config_type": config_type}


@router.put("/{vertical}/{config_type}")
async def update_config(
    vertical: str,
    config_type: str,
    body: dict,
    org_id: uuid.UUID | None = None,
    if_match: str | None = Header(None, alias="If-Match"),
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Update config override with optimistic locking."""
    if not ConfigRegistry.is_registered(vertical, config_type):
        raise HTTPException(
            status_code=400,
            detail=f"Unregistered config domain: ({vertical}, {config_type})",
        )
    if org_id is None:
        raise HTTPException(status_code=400, detail="org_id query parameter required for override writes")

    if if_match is None:
        raise HTTPException(
            status_code=428,
            detail="If-Match header required. Reload to get current version.",
        )
    try:
        version = int(if_match)
    except ValueError:
        raise HTTPException(status_code=400, detail="If-Match must be a valid integer version")
    writer = ConfigWriter(db)
    return await writer.put(vertical, config_type, org_id, body, version, actor.actor_id)


@router.delete("/{vertical}/{config_type}")
async def delete_config(
    vertical: str,
    config_type: str,
    org_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Remove override -- tenant falls back to default."""
    if not ConfigRegistry.is_registered(vertical, config_type):
        raise HTTPException(
            status_code=400,
            detail=f"Unregistered config domain: ({vertical}, {config_type})",
        )
    if org_id is None:
        raise HTTPException(status_code=400, detail="org_id required")
    writer = ConfigWriter(db)
    await writer.delete_override(vertical, config_type, org_id, actor.actor_id)
    return {"status": "deleted"}


@router.get("/{vertical}/{config_type}/diff")
async def get_config_diff(
    vertical: str,
    config_type: str,
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Show override vs default with changed keys."""
    if not ConfigRegistry.is_registered(vertical, config_type):
        raise HTTPException(
            status_code=400,
            detail=f"Unregistered config domain: ({vertical}, {config_type})",
        )
    writer = ConfigWriter(db)
    return await writer.diff(vertical, config_type, org_id)


@router.put("/defaults/{vertical}/{config_type}")
async def update_default(
    vertical: str,
    config_type: str,
    body: dict,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Update global default config (super-admin only)."""
    if not ConfigRegistry.is_registered(vertical, config_type):
        raise HTTPException(
            status_code=400,
            detail=f"Unregistered config domain: ({vertical}, {config_type})",
        )
    writer = ConfigWriter(db)
    return await writer.put_default(vertical, config_type, body, actor.actor_id)


@router.post("/validate")
async def validate_config(
    body: dict,
    vertical: str,
    config_type: str,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Dry-run guardrail validation without persisting."""
    writer = ConfigWriter(db)
    errors = await writer.validate_override(vertical, config_type, body)
    return {"valid": len(errors) == 0, "errors": errors}

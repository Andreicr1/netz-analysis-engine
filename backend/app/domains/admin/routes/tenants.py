"""Admin tenant management routes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.models import VerticalConfigOverride
from app.core.security.admin_auth import require_super_admin
from app.core.security.clerk_auth import Actor
from app.core.tenancy.admin_middleware import get_db_admin
from app.domains.admin.models import AdminAuditLog, TenantAsset
from app.domains.admin.validators import strip_exif, validate_image_magic_bytes

router = APIRouter(
    prefix="/admin/tenants",
    tags=["admin-tenants"],
    dependencies=[Depends(require_super_admin)],
)

# -- Schemas ---------------------------------------------------------------


class TenantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_name: str
    org_slug: str
    vertical: str


class TenantUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    org_name: str | None = None


# -- Routes ----------------------------------------------------------------
# IMPORTANT: Literal routes BEFORE parameterized routes (FastAPI route shadowing prevention)


@router.get("/")
async def list_tenants(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """List all tenants (cross-tenant read) with pagination."""
    # Get unique org_ids from config overrides (tenants with configs)
    result = await db.execute(
        select(
            VerticalConfigOverride.organization_id,
            func.count(VerticalConfigOverride.id).label("config_count"),
        )
        .group_by(VerticalConfigOverride.organization_id),
    )
    tenant_configs = {row[0]: row[1] for row in result.all()}

    # Get asset counts per org
    asset_result = await db.execute(
        select(
            TenantAsset.organization_id,
            func.count(TenantAsset.id).label("asset_count"),
        )
        .group_by(TenantAsset.organization_id),
    )
    tenant_assets = {row[0]: row[1] for row in asset_result.all()}

    # Combine unique org_ids
    all_org_ids = sorted(set(tenant_configs.keys()) | set(tenant_assets.keys()), key=str)
    total = len(all_org_ids)

    # Apply pagination
    paginated_ids = all_org_ids[offset : offset + limit]

    tenants = []
    for org_id in paginated_ids:
        tenants.append({
            "organization_id": str(org_id),
            "org_name": str(org_id),  # Would come from Clerk in production
            "org_slug": str(org_id)[:8],
            "vertical": "unknown",
            "config_count": tenant_configs.get(org_id, 0),
            "asset_count": tenant_assets.get(org_id, 0),
        })

    return {"tenants": tenants, "total": total, "limit": limit, "offset": offset}


@router.post("/")
async def create_tenant(
    body: TenantCreateRequest,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Create tenant -- seed default configs in DB."""
    # In production, this would also create a Clerk organization
    # For now, just seed configs for the org
    org_id = uuid.uuid4()  # In production: from Clerk org creation response

    # Audit log
    db.add(AdminAuditLog(
        actor_id=actor.actor_id,
        action="tenant.create",
        resource_type="tenant",
        resource_id=str(org_id),
        target_org_id=org_id,
    ))

    return {
        "organization_id": str(org_id),
        "org_name": body.org_name,
        "org_slug": body.org_slug,
        "vertical": body.vertical,
        "message": "Tenant created. Use /seed to initialize configs.",
    }


@router.get("/{org_id}")
async def get_tenant(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Get tenant detail -- configs, assets, usage."""
    # Configs
    configs_result = await db.execute(
        select(VerticalConfigOverride)
        .where(VerticalConfigOverride.organization_id == org_id),
    )
    configs = configs_result.scalars().all()

    # Assets
    assets_result = await db.execute(
        select(TenantAsset)
        .where(TenantAsset.organization_id == org_id),
    )
    assets = assets_result.scalars().all()

    return {
        "organization_id": str(org_id),
        "org_name": str(org_id),
        "org_slug": str(org_id)[:8],
        "configs": [
            {
                "vertical": c.vertical,
                "config_type": c.config_type,
                "has_override": True,
                "version": c.version,
            }
            for c in configs
        ],
        "assets": [
            {
                "id": str(a.id),
                "organization_id": str(a.organization_id),
                "asset_type": a.asset_type,
                "content_type": a.content_type,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in assets
        ],
    }


@router.patch("/{org_id}")
async def update_tenant(
    org_id: uuid.UUID,
    body: TenantUpdateRequest,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Update tenant metadata."""
    # In production: update Clerk organization
    db.add(AdminAuditLog(
        actor_id=actor.actor_id,
        action="tenant.update",
        resource_type="tenant",
        resource_id=str(org_id),
        target_org_id=org_id,
    ))
    return {"organization_id": str(org_id), "updated": True}


@router.post("/{org_id}/seed")
async def seed_tenant(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Re-seed default configs for tenant (idempotent)."""
    # Seed default configs using ON CONFLICT DO NOTHING pattern
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.core.config.models import VerticalConfigDefault

    defaults_result = await db.execute(select(VerticalConfigDefault))
    defaults = defaults_result.scalars().all()

    seeded = 0
    for d in defaults:
        stmt = pg_insert(VerticalConfigOverride).values(
            organization_id=org_id,
            vertical=d.vertical,
            config_type=d.config_type,
            config=d.config,
            version=1,
        ).on_conflict_do_nothing(
            constraint="uq_overrides_org_vertical_type",
        )
        result = await db.execute(stmt)
        if result.rowcount > 0:
            seeded += 1

    return {"organization_id": str(org_id), "seeded_configs": seeded}


@router.post("/{org_id}/assets")
async def upload_asset(
    org_id: uuid.UUID,
    asset_type: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Upload logo/favicon for tenant (multipart, 512KB max, PNG/JPEG/ICO only)."""
    # Validate asset_type
    valid_types = {"logo_light", "logo_dark", "favicon"}
    if asset_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"asset_type must be one of {valid_types}")

    # Read file data
    data = await file.read()

    # Size limit: 512KB
    if len(data) > 512 * 1024:
        raise HTTPException(status_code=400, detail="File size must be 512KB or less")

    # Detect content type from magic bytes (not Content-Type header)
    if data.startswith(b"\x89PNG"):
        detected_type = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        detected_type = "image/jpeg"
    elif data.startswith(b"\x00\x00\x01\x00") or data.startswith(b"\x00\x00\x02\x00"):
        detected_type = "image/x-icon"
    else:
        raise HTTPException(status_code=400, detail="Invalid file type. Only PNG, JPEG, and ICO are accepted.")

    if not validate_image_magic_bytes(data, detected_type):
        raise HTTPException(status_code=400, detail="File content does not match detected type")

    # Strip EXIF from JPEG
    data = strip_exif(data)

    # Upsert asset
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    stmt = pg_insert(TenantAsset).values(
        organization_id=org_id,
        asset_type=asset_type,
        content_type=detected_type,
        data=data,
    ).on_conflict_do_update(
        constraint="uq_tenant_assets_org_type",
        set_=dict(content_type=detected_type, data=data),
    ).returning(TenantAsset.id)

    result = await db.execute(stmt)
    asset_id = result.scalar_one()

    # Audit log
    db.add(AdminAuditLog(
        actor_id=actor.actor_id,
        action="asset.upload",
        resource_type="asset",
        resource_id=f"{asset_type}",
        target_org_id=org_id,
    ))

    return {
        "id": str(asset_id),
        "asset_type": asset_type,
        "content_type": detected_type,
        "message": f"{asset_type} uploaded successfully",
    }


@router.delete("/{org_id}/assets/{asset_type}")
async def delete_asset(
    org_id: uuid.UUID,
    asset_type: str,
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
):
    """Delete a tenant asset."""
    from sqlalchemy import delete as sa_delete

    result = await db.execute(
        sa_delete(TenantAsset).where(
            TenantAsset.organization_id == org_id,
            TenantAsset.asset_type == asset_type,
        ),
    )

    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Asset not found")

    db.add(AdminAuditLog(
        actor_id=actor.actor_id,
        action="asset.delete",
        resource_type="asset",
        resource_id=asset_type,
        target_org_id=org_id,
    ))

    return {"status": "deleted"}

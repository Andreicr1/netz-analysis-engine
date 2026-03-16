"""Admin tenant routes — Tenant CRUD and config seeding.

All routes require ADMIN role.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.models import VerticalConfigDefault, VerticalConfigOverride
from app.core.security.clerk_auth import Actor, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.admin.models import TenantAsset
from app.domains.admin.schemas import (
    TenantAssetResponse,
    TenantCreateRequest,
    TenantDetail,
    TenantSeedResponse,
    TenantSummary,
)
from app.shared.enums import Role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/tenants", tags=["admin-tenants"])


@router.post(
    "",
    response_model=TenantSeedResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create tenant and seed config defaults",
    description="Seeds default config overrides for the given org+verticals. "
    "Clerk org should be created first externally.",
)
async def create_tenant(
    payload: TenantCreateRequest,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db_with_rls),
) -> TenantSeedResponse:
    """Seed default configs for a new tenant.

    Clerk org creation is external (Clerk API). This endpoint seeds
    the DB with default config entries for the specified verticals.
    Wrapped in a transaction — all-or-nothing.
    """
    configs_seeded = await _seed_configs(db, payload.organization_id, payload.verticals)

    return TenantSeedResponse(
        organization_id=payload.organization_id,
        configs_seeded=configs_seeded,
        message=f"Tenant seeded with {configs_seeded} config entries",
    )


@router.get(
    "",
    response_model=list[TenantSummary],
    summary="List all tenants",
    description="Lists all known tenants from config overrides and assets.",
)
async def list_tenants(
    actor: Actor = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db_with_rls),
) -> list[TenantSummary]:
    """List tenants — derived from distinct org_ids in config overrides and assets.

    No dedicated organizations table exists — we derive the list from
    existing data. In production, this would be supplemented by Clerk API.
    """
    # Get distinct org_ids from overrides
    override_result = await db.execute(
        select(
            VerticalConfigOverride.organization_id,
            func.count().label("config_count"),
        ).group_by(VerticalConfigOverride.organization_id)
    )
    config_counts = {row[0]: row[1] for row in override_result.all()}

    # Get distinct org_ids from assets
    asset_result = await db.execute(
        select(
            TenantAsset.organization_id,
            func.count().label("asset_count"),
        ).group_by(TenantAsset.organization_id)
    )
    asset_counts = {row[0]: row[1] for row in asset_result.all()}

    # Merge org_ids
    all_org_ids = set(config_counts.keys()) | set(asset_counts.keys())

    return [
        TenantSummary(
            organization_id=org_id,
            name=str(org_id)[:8],  # Placeholder — real name from Clerk API
            slug=str(org_id)[:8],
            config_count=config_counts.get(org_id, 0),
            asset_count=asset_counts.get(org_id, 0),
        )
        for org_id in sorted(all_org_ids, key=str)
    ]


@router.get(
    "/{org_id}",
    response_model=TenantDetail,
    summary="Get tenant detail",
)
async def get_tenant(
    org_id: uuid.UUID,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db_with_rls),
) -> TenantDetail:
    # Get config overrides
    configs_result = await db.execute(
        select(
            VerticalConfigOverride.vertical,
            VerticalConfigOverride.config_type,
            VerticalConfigOverride.version,
        ).where(VerticalConfigOverride.organization_id == org_id)
    )
    configs = [
        {"vertical": r[0], "config_type": r[1], "version": r[2]}
        for r in configs_result.all()
    ]

    # Get assets
    assets_result = await db.execute(
        select(TenantAsset).where(TenantAsset.organization_id == org_id)
    )
    assets = [
        TenantAssetResponse.model_validate(a)
        for a in assets_result.scalars().all()
    ]

    return TenantDetail(
        organization_id=org_id,
        name=str(org_id)[:8],
        slug=str(org_id)[:8],
        configs=configs,
        assets=assets,
    )


@router.post(
    "/{org_id}/seed",
    response_model=TenantSeedResponse,
    summary="Re-seed default configs for a tenant",
    description="Re-seeds default configs. Does not overwrite existing overrides.",
)
async def reseed_tenant(
    org_id: uuid.UUID,
    verticals: list[str] | None = None,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db_with_rls),
) -> TenantSeedResponse:
    """Re-seed default configs. Safe to call multiple times (idempotent)."""
    verts = verticals or ["private_credit", "liquid_funds"]
    configs_seeded = await _seed_configs(db, org_id, verts)

    return TenantSeedResponse(
        organization_id=org_id,
        configs_seeded=configs_seeded,
        message=f"Re-seeded {configs_seeded} config entries",
    )


async def _seed_configs(
    db: AsyncSession,
    org_id: uuid.UUID,
    verticals: list[str],
) -> int:
    """Seed config overrides from defaults for specified verticals.

    Skips entries that already exist (idempotent).
    """
    # Pre-fetch all existing overrides for this org in one query (avoid N+1)
    existing_result = await db.execute(
        select(
            VerticalConfigOverride.vertical,
            VerticalConfigOverride.config_type,
        ).where(VerticalConfigOverride.organization_id == org_id)
    )
    existing_keys = {(r[0], r[1]) for r in existing_result.all()}

    count = 0
    for vertical in verticals:
        defaults_result = await db.execute(
            select(VerticalConfigDefault).where(
                VerticalConfigDefault.vertical == vertical,
            )
        )
        defaults = defaults_result.scalars().all()

        for default in defaults:
            if (vertical, default.config_type) in existing_keys:
                continue

            # Create override with default config as starting point
            override = VerticalConfigOverride(
                organization_id=org_id,
                vertical=vertical,
                config_type=default.config_type,
                config=default.config,
                version=1,
            )
            db.add(override)
            count += 1

    await db.flush()
    return count

"""Branding route — returns merged branding config for current org.

GET /api/v1/branding — authenticated, returns BrandingResponse.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService
from app.core.config.dependencies import get_config_service
from app.core.security.admin_auth import require_super_admin
from app.core.security.clerk_auth import Actor
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.admin.models import TenantAsset
from app.domains.admin.schemas import BrandingResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"], dependencies=[Depends(require_super_admin)])


@router.get(
    "/branding",
    response_model=BrandingResponse,
    summary="Get branding config",
    description="Returns merged branding configuration for the current organization.",
)
async def get_branding(
    vertical: str = Query("liquid_funds", description="Vertical to get branding for"),
    actor: Actor = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db_with_rls),
    config_service: ConfigService = Depends(get_config_service),
) -> BrandingResponse:
    """Return merged branding config (default + org override)."""
    branding = await config_service.get(
        vertical=vertical,
        config_type="branding",
        org_id=actor.organization_id,
    )

    # Resolve logo URLs with cache-busting query param
    org_slug = actor.organization_slug or "default"

    # Check for tenant assets to compute cache-bust hash
    asset_hashes: dict[str, str] = {}
    if actor.organization_id is not None:
        result = await db.execute(
            select(TenantAsset.asset_type, TenantAsset.updated_at).where(
                TenantAsset.organization_id == actor.organization_id
            )
        )
        for asset_type, updated_at in result.all():
            ts = updated_at.isoformat() if updated_at else ""
            asset_hashes[asset_type] = hashlib.md5(  # noqa: S324
                ts.encode()
            ).hexdigest()[:8]

    # Template the org_slug into URL patterns and add cache-bust
    url_fields = {
        "logo_light_url": "logo_light",
        "logo_dark_url": "logo_dark",
        "favicon_url": "favicon",
    }
    for field, asset_type in url_fields.items():
        url = branding.get(field, f"/api/v1/assets/tenant/{org_slug}/{asset_type}")
        url = url.replace("{org_slug}", org_slug)
        if asset_type in asset_hashes:
            url = f"{url}?v={asset_hashes[asset_type]}"
        branding[field] = url

    return BrandingResponse.model_validate(branding)

"""Asset route — serves tenant binary assets (logos, favicons).

GET /api/v1/assets/tenant/{org_slug}/{asset_type} — UNAUTHENTICATED.
Returns binary asset with correct Content-Type, ETag, and cache headers.
Never returns 404 for unknown slugs — prevents tenant enumeration.
"""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.core.db.engine import async_session_factory
from app.domains.admin.models import TenantAsset

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])

_VALID_ASSET_TYPES = frozenset({"logo_light", "logo_dark", "favicon"})

# Default Netz logo (1x1 transparent PNG) — returned for unknown slugs
_DEFAULT_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
    b"\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

_DEFAULT_ETAG = hashlib.md5(_DEFAULT_PNG).hexdigest()[:16]  # noqa: S324


def _asset_response(data: bytes, content_type: str) -> Response:
    etag = hashlib.md5(data).hexdigest()[:16]  # noqa: S324
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "ETag": f'"{etag}"',
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/assets/tenant/{org_slug}/{asset_type}",
    summary="Serve tenant asset",
    description="Public endpoint serving tenant logos and favicons. Never returns 404 for unknown slugs.",
    responses={
        200: {"content": {"image/png": {}, "image/jpeg": {}, "image/x-icon": {}}},
        404: {"description": "Invalid asset type"},
    },
)
async def get_tenant_asset(org_slug: str, asset_type: str) -> Response:
    """Serve tenant asset by org slug. Unauthenticated — public endpoint."""
    if asset_type not in _VALID_ASSET_TYPES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invalid asset type",
        )

    # Public endpoint — no RLS. Filter by org_slug to isolate tenants.
    async with async_session_factory() as session:
        result = await session.execute(
            select(TenantAsset.data, TenantAsset.content_type).where(
                TenantAsset.org_slug == org_slug,
                TenantAsset.asset_type == asset_type,
            )
        )
        row = result.first()

    if row is not None:
        return _asset_response(row[0], row[1])

    # Unknown slug or no asset — return default Netz logo (never 404)
    return _asset_response(_DEFAULT_PNG, "image/png")

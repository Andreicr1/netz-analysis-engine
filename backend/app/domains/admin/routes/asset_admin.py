"""Admin asset routes — Upload and delete tenant assets (logos, favicons).

Upload requires ADMIN role. Validates file size (512KB), content type,
and magic bytes (reject SVG entirely).
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security.clerk_auth import Actor, require_role
from app.core.tenancy.middleware import get_db_with_rls
from app.domains.admin.models import TenantAsset
from app.domains.admin.schemas import AssetUploadResponse, TenantAssetResponse
from app.shared.enums import Role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/tenants", tags=["admin-assets"])

_MAX_ASSET_SIZE = 512 * 1024  # 512KB

_VALID_ASSET_TYPES = frozenset({"logo_light", "logo_dark", "favicon"})

# Content types we accept (no SVG — XSS risk)
_ALLOWED_CONTENT_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/x-icon",
    "image/vnd.microsoft.icon",
})

# Magic bytes for content type validation
_MAGIC_BYTES: dict[bytes, str] = {
    b"\x89PNG": "image/png",
    b"\xff\xd8\xff": "image/jpeg",
    b"\x00\x00\x01\x00": "image/x-icon",
    b"\x00\x00\x02\x00": "image/vnd.microsoft.icon",
}


def _detect_content_type(data: bytes) -> str | None:
    """Detect content type from magic bytes (not Content-Type header)."""
    for magic, content_type in _MAGIC_BYTES.items():
        if data[:len(magic)] == magic:
            return content_type
    return None


@router.post(
    "/{org_id}/assets",
    response_model=AssetUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload tenant asset (logo/favicon)",
    description="Multipart upload. 512KB max. PNG/JPEG/ICO only (SVG rejected).",
)
async def upload_asset(
    org_id: uuid.UUID,
    asset_type: str,
    file: UploadFile = File(...),
    actor: Actor = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db_with_rls),
) -> AssetUploadResponse:
    if asset_type not in _VALID_ASSET_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid asset_type. Must be one of: {', '.join(sorted(_VALID_ASSET_TYPES))}",
        )

    # Read file data
    data = await file.read()

    # Size check
    if len(data) > _MAX_ASSET_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {_MAX_ASSET_SIZE // 1024}KB",
        )

    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )

    # Validate via magic bytes (not Content-Type header which can be spoofed)
    detected_type = _detect_content_type(data)
    if detected_type is None or detected_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Invalid file type. Only PNG, JPEG, and ICO are accepted. SVG is not allowed.",
        )

    # Upsert asset
    existing = await db.execute(
        select(TenantAsset).where(
            TenantAsset.organization_id == org_id,
            TenantAsset.asset_type == asset_type,
        )
    )
    asset = existing.scalar_one_or_none()

    if asset is not None:
        asset.data = data
        asset.content_type = detected_type
    else:
        asset = TenantAsset(
            organization_id=org_id,
            asset_type=asset_type,
            content_type=detected_type,
            data=data,
        )
        db.add(asset)

    await db.flush()

    return AssetUploadResponse(
        id=asset.id,
        asset_type=asset_type,
        content_type=detected_type,
        message=f"Asset '{asset_type}' uploaded successfully",
    )


@router.delete(
    "/{org_id}/assets/{asset_type}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete tenant asset",
)
async def delete_asset(
    org_id: uuid.UUID,
    asset_type: str,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db_with_rls),
) -> None:
    if asset_type not in _VALID_ASSET_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid asset_type. Must be one of: {', '.join(sorted(_VALID_ASSET_TYPES))}",
        )

    result = await db.execute(
        select(TenantAsset).where(
            TenantAsset.organization_id == org_id,
            TenantAsset.asset_type == asset_type,
        )
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )

    await db.delete(asset)


@router.get(
    "/{org_id}/assets",
    response_model=list[TenantAssetResponse],
    summary="List tenant assets",
)
async def list_assets(
    org_id: uuid.UUID,
    actor: Actor = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db_with_rls),
) -> list[TenantAssetResponse]:
    result = await db.execute(
        select(TenantAsset).where(TenantAsset.organization_id == org_id)
    )
    return [TenantAssetResponse.model_validate(a) for a in result.scalars().all()]

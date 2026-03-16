"""Pydantic v2 schemas for admin domain (branding, assets)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BrandingResponse(BaseModel):
    """Branding config returned to frontends. Merged default + override."""

    model_config = ConfigDict(extra="forbid")

    company_name: str
    tagline: str
    logo_light_url: str
    logo_dark_url: str
    favicon_url: str
    primary_color: str
    accent_color: str
    font_family: str
    report_header: str
    report_footer: str
    email_from_name: str


class AssetUploadResponse(BaseModel):
    """Response after uploading a tenant asset."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    asset_type: str
    content_type: str
    message: str


class TenantAssetResponse(BaseModel):
    """Asset metadata (without binary data)."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    organization_id: uuid.UUID
    asset_type: str
    content_type: str
    created_at: datetime
    updated_at: datetime

"""Pydantic v2 schemas for admin domain (branding, assets)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BrandingResponse(BaseModel):
    """Branding config returned to frontends. Merged default + override.

    Uses extra="allow" so additional config fields (CSS tokens, future
    extensions) pass through from ConfigService to the frontend. The
    frontend BrandingConfig interface maps these to CSS custom properties.
    """

    model_config = ConfigDict(extra="allow")

    # Identity
    company_name: str = "Netz Capital"
    tagline: str = "Institutional Investment Intelligence"
    org_name: str = "Netz"
    org_slug: str = "netz"

    # Logo URLs (templated with {org_slug}, resolved by branding route)
    logo_light_url: str = "/api/v1/assets/tenant/{org_slug}/logo_light"
    logo_dark_url: str = "/api/v1/assets/tenant/{org_slug}/logo_dark"
    favicon_url: str = "/api/v1/assets/tenant/{org_slug}/favicon"

    # CSS color tokens — must match frontend BrandingConfig field names
    primary_color: str = "#1B365D"
    secondary_color: str = "#3A7BD5"
    accent_color: str = "#8B9DAF"
    light_color: str = "#D4E4F7"
    highlight_color: str = "#FF975A"
    surface_color: str = "#FFFFFF"
    surface_alt_color: str = "#F8FAFC"
    border_color: str = "#E2E8F0"
    text_primary: str = "#0F172A"
    text_secondary: str = "#475569"
    text_muted: str = "#94A3B8"

    # Font tokens
    font_sans: str = "'Inter Variable', Inter, system-ui, sans-serif"
    font_mono: str = "'JetBrains Mono', monospace"
    font_family: str = "Inter, system-ui, sans-serif"

    # Report/email
    report_header: str = "Netz Capital"
    report_footer: str = "Confidential — For Authorized Recipients Only"
    email_from_name: str = "Netz Capital"


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

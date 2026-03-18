"""Pydantic v2 schemas for admin domain (branding, assets)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PromptVersionOut(BaseModel):
    """Single version entry from prompt override history."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    version: int
    content: str
    updated_by: str
    actor_id: str | None = None  # alias of updated_by for frontend consistency
    change_summary: str | None = None
    created_at: datetime


class PromptVersionsResponse(BaseModel):
    """Paginated response for prompt version history."""

    versions: list[PromptVersionOut]
    has_more: bool


class BrandingResponse(BaseModel):
    """Branding config returned to frontends. Merged default + override.

    Uses extra="forbid" to prevent CSS injection via unexpected fields.
    All branding fields must be explicitly declared here.
    """

    model_config = ConfigDict(extra="forbid")

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


# ---------------------------------------------------------------------------
# Health monitoring schemas
# ---------------------------------------------------------------------------


class ServiceHealthOut(BaseModel):
    """Health status for an infrastructure service (DB, Redis, ADLS, etc.)."""

    name: str
    status: str  # "ok" | "down" | "degraded" | "disabled" | "disconnected"
    latency_ms: float | None = None
    error: str | None = None
    checked_at: datetime


class WorkerStatusOut(BaseModel):
    """Status snapshot for a background worker."""

    name: str
    status: str
    last_run: datetime | None = None
    duration_ms: float | None = None
    error_count: int = 0
    checked_at: datetime


class PipelineStatsOut(BaseModel):
    """Aggregate pipeline processing statistics."""

    docs_processed: int
    queue_depth: int
    error_rate: float
    checked_at: datetime

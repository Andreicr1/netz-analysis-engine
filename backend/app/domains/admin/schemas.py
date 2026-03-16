"""Pydantic v2 schemas for admin domain (branding, assets, configs, tenants, health)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

# ── Branding ──────────────────────────────────────────────────

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


# ── Assets ────────────────────────────────────────────────────

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


# ── Config ────────────────────────────────────────────────────

class ConfigWriteRequest(BaseModel):
    """Request body for creating/updating a config override."""

    model_config = ConfigDict(extra="forbid")

    vertical: str
    config_type: str
    config: dict[str, Any]
    expected_version: int | None = None


class ConfigWriteResponse(BaseModel):
    """Response after writing a config override."""

    model_config = ConfigDict(extra="forbid")

    vertical: str
    config_type: str
    version: int
    message: str


class ConfigDiffResponse(BaseModel):
    """Side-by-side default vs override comparison."""

    model_config = ConfigDict(extra="forbid")

    default: dict[str, Any]
    override: dict[str, Any]
    merged: dict[str, Any]
    override_version: int | None = None


class ConfigDefaultWriteRequest(BaseModel):
    """Request body for updating a global config default."""

    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any]


# ── Tenants ───────────────────────────────────────────────────

class TenantCreateRequest(BaseModel):
    """Request body for creating a new tenant."""

    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID
    organization_slug: str
    name: str
    verticals: list[str]


class TenantSummary(BaseModel):
    """Tenant summary for list view."""

    model_config = ConfigDict(extra="ignore")

    organization_id: uuid.UUID
    name: str
    slug: str
    config_count: int = 0
    asset_count: int = 0


class TenantDetail(BaseModel):
    """Detailed tenant info."""

    model_config = ConfigDict(extra="ignore")

    organization_id: uuid.UUID
    name: str
    slug: str
    configs: list[dict[str, Any]] = []
    assets: list[TenantAssetResponse] = []


class TenantSeedResponse(BaseModel):
    """Response after seeding tenant config defaults."""

    model_config = ConfigDict(extra="forbid")

    organization_id: uuid.UUID
    configs_seeded: int
    message: str


# ── Health ────────────────────────────────────────────────────

class WorkerStatus(BaseModel):
    """Status of a background worker."""

    model_config = ConfigDict(extra="ignore")

    name: str
    last_run: datetime | None = None
    duration_seconds: float | None = None
    status: Literal["healthy", "degraded", "error", "unknown"]
    error_count: int = 0


class PipelineStats(BaseModel):
    """Pipeline processing statistics."""

    model_config = ConfigDict(extra="ignore")

    documents_processed: int = 0
    queue_depth: int = 0
    error_rate: float = 0.0


class TenantUsage(BaseModel):
    """Per-tenant usage statistics."""

    model_config = ConfigDict(extra="ignore")

    organization_id: uuid.UUID
    organization_name: str | None = None
    api_calls: int = 0
    storage_bytes: int = 0
    memos_generated: int = 0

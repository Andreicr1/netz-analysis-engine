"""Admin domain schemas — package re-exporting from legacy single-file module."""

from __future__ import annotations

from app.domains.admin._schemas import (
    AssetUploadResponse,
    BrandingResponse,
    ConfigDiffOut,
    PipelineStatsOut,
    PromptVersionOut,
    PromptVersionsResponse,
    ServiceHealthOut,
    TenantAssetResponse,
    WorkerStatusOut,
)

__all__ = [
    "AssetUploadResponse",
    "BrandingResponse",
    "ConfigDiffOut",
    "PipelineStatsOut",
    "PromptVersionOut",
    "PromptVersionsResponse",
    "ServiceHealthOut",
    "TenantAssetResponse",
    "WorkerStatusOut",
]

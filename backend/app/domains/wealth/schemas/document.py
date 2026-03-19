"""Wealth document schemas — request/response models for document upload & listing."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ── Response schemas ─────────────────────────────────────────


class WealthDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    organization_id: uuid.UUID
    portfolio_id: uuid.UUID | None = None
    instrument_id: uuid.UUID | None = None
    title: str
    filename: str
    content_type: str | None = None
    root_folder: str
    subfolder_path: str | None = None
    domain: str | None = None
    current_version: int
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None


class WealthDocumentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    document_id: uuid.UUID
    portfolio_id: uuid.UUID | None = None
    version_number: int
    blob_uri: str | None = None
    blob_path: str | None = None
    content_type: str | None = None
    ingestion_status: str
    indexed_at: datetime | None = None
    uploaded_by: str | None = None
    uploaded_at: datetime | None = None
    created_at: datetime | None = None


# ── Upload URL flow (two-step) ───────────────────────────────


class WealthUploadUrlRequest(BaseModel):
    portfolio_id: uuid.UUID | None = None
    instrument_id: uuid.UUID | None = None
    filename: str
    content_type: str = "application/pdf"
    root_folder: str = "documents"
    subfolder_path: str | None = None
    domain: str | None = None
    title: str | None = None


class WealthUploadUrlResponse(BaseModel):
    upload_id: str
    upload_url: str
    blob_path: str
    expires_in: int = 3600


class WealthUploadCompleteRequest(BaseModel):
    upload_id: str


class WealthUploadCompleteResponse(BaseModel):
    job_id: str
    version_id: str
    document_id: str


# ── Process pending ──────────────────────────────────────────


class WealthProcessPendingRequest(BaseModel):
    limit: int = Field(default=10, ge=1, le=50)


class WealthProcessPendingResponse(BaseModel):
    processed: int
    indexed: int
    failed: int
    skipped: int


# ── Paginated response ──────────────────────────────────────


class WealthDocumentPage(BaseModel):
    items: list[WealthDocumentOut]
    limit: int
    offset: int

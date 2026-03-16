"""Wealth Content Pydantic schemas for API serialization."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content_type: str
    title: str
    language: str
    status: str
    storage_path: str | None = None
    created_by: str
    approved_by: str | None = None
    approved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ContentRead(ContentSummary):
    content_md: str | None = None
    content_data: dict | None = None


class ContentTrigger(BaseModel):
    """Body for content generation trigger endpoints."""
    config_overrides: dict | None = None

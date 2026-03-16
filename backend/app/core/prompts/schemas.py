"""Pydantic v2 schemas for prompt management (Phase E)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class PromptInfo(BaseModel):
    """Metadata about a prompt template."""

    model_config = ConfigDict(extra="ignore")

    vertical: str
    template_name: str
    description: str | None = None
    has_org_override: bool = False
    has_global_override: bool = False
    source_level: Literal["org", "global", "filesystem"]


class PromptContent(BaseModel):
    """Resolved prompt content with source info."""

    model_config = ConfigDict(extra="ignore")

    vertical: str
    template_name: str
    content: str
    source_level: Literal["org", "global", "filesystem"]
    version: int | None = None


class PromptUpdate(BaseModel):
    """Request body for updating a prompt override."""

    model_config = ConfigDict(extra="forbid")

    content: str


class PromptPreviewRequest(BaseModel):
    """Request body for previewing a prompt with sample data."""

    model_config = ConfigDict(extra="forbid")

    content: str
    sample_data: dict[str, Any]


class PromptPreviewResponse(BaseModel):
    """Response from prompt preview."""

    model_config = ConfigDict(extra="forbid")

    rendered: str
    errors: list[str] | None = None


class PromptValidateResponse(BaseModel):
    """Response from prompt validation."""

    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str]


class PromptWriteResponse(BaseModel):
    """Response after writing a prompt override."""

    model_config = ConfigDict(extra="forbid")

    version: int
    message: str


class PromptVersionInfo(BaseModel):
    """Version history entry."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    version: int
    content: str
    updated_by: str
    created_at: dt.datetime

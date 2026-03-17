"""Pydantic schemas for the prompt admin API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PromptListItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_name: str
    description: str
    source_level: str  # "org" | "global" | "filesystem"
    version: int | None
    has_override: bool


class PromptDetailResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_name: str
    content: str
    source_level: str
    version: int | None


class PromptPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(max_length=51200)  # 50KB max
    sample_data: dict  # validated recursively for JSON-primitive types


class PromptPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rendered: str
    errors: list[str]


class PromptVersionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int
    content: str
    updated_by: str
    created_at: datetime


class PromptValidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str]

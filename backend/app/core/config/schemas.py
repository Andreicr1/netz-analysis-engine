"""Pydantic schemas for vertical configuration system (Sprint 3 subset)."""

from __future__ import annotations

from pydantic import BaseModel


class ConfigEntry(BaseModel):
    """Metadata for a single config type within a vertical."""

    vertical: str
    config_type: str
    has_override: bool
    description: str | None = None

    model_config = {"from_attributes": True}

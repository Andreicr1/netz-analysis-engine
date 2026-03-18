"""Pydantic schemas for vertical configuration system (Sprint 3 subset)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel


class ConfigEntry(BaseModel):
    """Metadata for a single config type within a vertical."""

    vertical: str
    config_type: str
    has_override: bool
    description: str | None = None

    model_config = {"from_attributes": True}


# ── CFG-01: Typed config result ──────────────────────────────────────────────


class ConfigResultState(enum.Enum):
    """Outcome of a config lookup."""

    FOUND = "found"
    MISSING_OPTIONAL = "missing_optional"
    MISSING_REQUIRED = "missing_required"


@dataclass(frozen=True)
class ConfigResult:
    """Typed wrapper that distinguishes found, missing-optional, missing-required.

    CFG-01: no caller can receive a plain ``{}`` indistinguishable from valid
    empty config.  Every result carries explicit state and resolved_source.

    Usage::

        result = await config_service.get("liquid_funds", "calibration", org_id)
        result.value   # dict — config payload (empty dict ONLY for optional miss)
        result.state   # ConfigResultState — FOUND | MISSING_OPTIONAL | MISSING_REQUIRED
        result.source  # str — "db_default", "yaml_fallback", "miss", etc.
    """

    value: dict[str, Any] = field(default_factory=dict)
    state: ConfigResultState = ConfigResultState.FOUND
    source: str = "unknown"

    @property
    def is_found(self) -> bool:
        return self.state is ConfigResultState.FOUND

    @property
    def is_missing(self) -> bool:
        return self.state in (
            ConfigResultState.MISSING_OPTIONAL,
            ConfigResultState.MISSING_REQUIRED,
        )

"""ProfileLoader — resolve analysis profiles via ConfigService.

Connects ``profiles/`` YAML seed data to ``vertical_engines/`` code via
``ConfigService``.  All config resolution goes through ConfigService
(DB override → DB default → YAML fallback) — never reads YAML directly.

Usage::

    from ai_engine.profile_loader import ProfileLoader

    loader = ProfileLoader(config_service)
    profile = await loader.load("private_credit", org_id=org_uuid)
    # profile.chapters, profile.vertical, profile.config, etc.

    analyzer = loader.get_analyzer("private_credit")
    # Returns a module reference (not an instance) for the vertical engine
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any
from uuid import UUID

from app.core.config.config_service import ConfigService
from ai_engine.vertical_registry import (
    available_profiles as available_vertical_profiles,
    get_vertical_entry,
    import_vertical_module,
)

logger = logging.getLogger(__name__)


# ── Profile dataclass ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ChapterConfig:
    """Single chapter in an analysis profile."""

    id: str
    title: str
    type: str  # ANALYTICAL | DESCRIPTIVE
    max_tokens: int = 4000
    chunk_budget: tuple[int, int] = (20, 4000)


@dataclass(frozen=True)
class AnalysisProfile:
    """Resolved analysis profile with chapters and config."""

    name: str
    display_name: str
    version: int
    vertical: str
    chapters: tuple[ChapterConfig, ...]
    config: dict[str, Any] = field(default_factory=dict)
    tone_normalization: dict[str, Any] = field(default_factory=dict)
    recommendation_chapter: str = ""
    evidence_law_template: str = ""
    evidence_law_ch13_template: str = ""


class ProfileLoader:
    """Loads analysis profiles from ConfigService and resolves vertical engines."""

    def __init__(self, config_service: ConfigService) -> None:
        self._config = config_service

    async def load(
        self,
        profile_name: str,
        org_id: UUID | None = None,
    ) -> AnalysisProfile:
        """Load a complete analysis profile.

        Parameters
        ----------
        profile_name : str
            Profile identifier (e.g. "private_credit", "liquid_funds").
        org_id : UUID | None
            Organization ID for tenant-specific overrides.

        Returns
        -------
        AnalysisProfile
            Frozen dataclass with chapters, config, and metadata.

        Raises
        ------
        ValueError
            If the profile name is not in the registry.
        """
        try:
            entry = get_vertical_entry(profile_name)
        except ValueError as exc:
            raise ValueError(
                f"Unknown profile: {profile_name!r}. "
                f"Available: {available_vertical_profiles()}"
            ) from exc

        vertical = entry.vertical_name

        # Fetch chapters + calibration in parallel — both are required configs,
        # ConfigMissError propagates if either is missing (CFG-01).
        chapters_result, calibration_result = await asyncio.gather(
            self._config.get(vertical, "chapters", org_id),
            self._config.get(vertical, "calibration", org_id),
        )
        chapters_config = chapters_result.value
        calibration = calibration_result.value

        # Parse chapters
        chapters = tuple(
            ChapterConfig(
                id=ch["id"],
                title=ch["title"],
                type=ch.get("type", "ANALYTICAL"),
                max_tokens=ch.get("max_tokens", 4000),
                chunk_budget=tuple(ch.get("chunk_budget", [20, 4000])),
            )
            for ch in chapters_config.get("chapters", [])
        )

        return AnalysisProfile(
            name=chapters_config.get("name", profile_name),
            display_name=chapters_config.get("display_name", profile_name),
            version=chapters_config.get("version", 1),
            vertical=vertical,
            chapters=chapters,
            config=calibration,
            tone_normalization=chapters_config.get("tone_normalization", {}),
            recommendation_chapter=chapters_config.get("recommendation_chapter", ""),
            evidence_law_template=chapters_config.get("evidence_law_template", ""),
            evidence_law_ch13_template=chapters_config.get("evidence_law_ch13_template", ""),
        )

    @staticmethod
    def get_engine_module(profile_name: str) -> ModuleType:
        """Lazily import and return the vertical engine module.

        Parameters
        ----------
        profile_name : str
            Profile identifier.

        Returns
        -------
        ModuleType
            The vertical engine module (e.g. ``vertical_engines.credit``).
        """
        return import_vertical_module(profile_name)

    @staticmethod
    def available_profiles() -> list[str]:
        """Return sorted list of registered profile names."""
        return available_vertical_profiles()

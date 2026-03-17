"""
ConfigService — Read-Only Vertical Configuration (Sprint 3)
============================================================

Resolves configuration for a given vertical + config_type + optional org_id.
Cascade: in-process TTLCache → DB override (RLS) → DB default → YAML fallback.

Sprint 3: read-only with cachetools.TTLCache (in-process, 60s).
Sprint 5-6: add Redis L2 cache + pg_notify invalidation + write methods.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar
from uuid import UUID

import yaml
from cachetools import TTLCache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.models import VerticalConfigDefault, VerticalConfigOverride
from app.core.config.schemas import ConfigEntry

logger = logging.getLogger(__name__)

# In-process cache — not an asyncio primitive, safe at module level.
# Replaced with Redis L2 in Sprint 5-6 when admin API enables writes.
_config_cache: TTLCache[str, dict] = TTLCache(maxsize=2048, ttl=60)

# Sentinel for admin-only key deletion in deep_merge.
_DELETE = object()

# YAML fallback directory (emergency only — logged as ERROR).
_YAML_FALLBACK_DIR = Path(__file__).resolve().parents[3]

# Map (vertical, config_type) → YAML file path relative to project root.
_YAML_FALLBACK_MAP: dict[tuple[str, str], str] = {
    ("liquid_funds", "calibration"): "calibration/config/limits.yaml",
    ("liquid_funds", "portfolio_profiles"): "calibration/config/profiles.yaml",
    ("liquid_funds", "scoring"): "calibration/config/scoring.yaml",
    ("liquid_funds", "blocks"): "calibration/config/blocks.yaml",
    ("private_credit", "chapters"): "profiles/private_credit/profile.yaml",
    ("private_credit", "calibration"): "calibration/seeds/private_credit/calibration.yaml",
    ("private_credit", "scoring"): "calibration/seeds/private_credit/scoring.yaml",
    ("liquid_funds", "chapters"): "profiles/liquid_funds/profile.yaml",
    ("liquid_funds", "macro_intelligence"): "calibration/seeds/liquid_funds/macro_intelligence.yaml",
    ("private_credit", "governance_policy"): "calibration/seeds/private_credit/governance_policy.yaml",
}


class ConfigService:
    """Read-only configuration service for Sprint 3.

    Uses a single DB session (get_db_with_rls) for both defaults and overrides.
    Defaults table has no RLS, so SET LOCAL has zero effect on it.
    Overrides table has RLS, so the same session works correctly for both.
    """

    # IP protection: prompts, chapters, and internal config types never returned
    # to clients. Chapters expose IC memo structure (analytical methodology IP).
    CLIENT_VISIBLE_TYPES: ClassVar[frozenset[str]] = frozenset(
        {"calibration", "scoring", "blocks", "portfolio_profiles"}
    )

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get(
        self,
        vertical: str,
        config_type: str,
        org_id: UUID | None = None,
    ) -> dict:
        """Return deep_merge(default, override) for the given config key.

        Cascade: in-process cache → DB override → DB default → YAML fallback.
        """
        cache_key = f"config:{vertical}:{config_type}:{org_id or 'default'}"

        cached = _config_cache.get(cache_key)
        if cached is not None:
            return cached

        # Query default
        default_row = await self._db.execute(
            select(VerticalConfigDefault.config).where(
                VerticalConfigDefault.vertical == vertical,
                VerticalConfigDefault.config_type == config_type,
            )
        )
        default_config = default_row.scalar_one_or_none()

        if default_config is None:
            # YAML fallback — indicates migration failure or missing seed data
            default_config = self._yaml_fallback(vertical, config_type)
            if default_config is None:
                logger.error(
                    "No config found for (%s, %s) — neither DB nor YAML fallback",
                    vertical,
                    config_type,
                )
                return {}

        # Query override if org_id provided
        override_config = None
        if org_id is not None:
            override_row = await self._db.execute(
                select(VerticalConfigOverride.config).where(
                    VerticalConfigOverride.vertical == vertical,
                    VerticalConfigOverride.config_type == config_type,
                    # Belt-and-suspenders with RLS — explicit org_id filter
                    VerticalConfigOverride.organization_id == org_id,
                )
            )
            override_config = override_row.scalar_one_or_none()

        if override_config:
            result = self.deep_merge(default_config, override_config)
        else:
            result = default_config

        _config_cache[cache_key] = result
        return result

    async def list_configs(
        self,
        vertical: str,
        org_id: UUID | None = None,
        *,
        is_admin: bool = False,
    ) -> list[ConfigEntry]:
        """List all config_types for a vertical, with override status.

        Non-admin callers: filters to CLIENT_VISIBLE_TYPES only (IP protection).
        """
        defaults_result = await self._db.execute(
            select(
                VerticalConfigDefault.config_type,
                VerticalConfigDefault.description,
            ).where(VerticalConfigDefault.vertical == vertical)
        )
        defaults = defaults_result.all()

        # Get override status for this org
        override_types: set[str] = set()
        if org_id is not None:
            overrides_result = await self._db.execute(
                select(VerticalConfigOverride.config_type).where(
                    VerticalConfigOverride.vertical == vertical,
                    VerticalConfigOverride.organization_id == org_id,
                )
            )
            override_types = {row[0] for row in overrides_result.all()}

        entries = []
        for config_type, description in defaults:
            # IP protection: non-admin callers only see CLIENT_VISIBLE_TYPES
            if not is_admin and config_type not in self.CLIENT_VISIBLE_TYPES:
                continue
            entries.append(
                ConfigEntry(
                    vertical=vertical,
                    config_type=config_type,
                    has_override=config_type in override_types,
                    description=description,
                )
            )

        return entries

    @classmethod
    def invalidate(
        cls,
        vertical: str,
        config_type: str,
        org_id: str | None = None,
    ) -> None:
        """Invalidate cached config for a specific key.

        Called by PgNotifier on config_changed events.
        If org_id is provided, invalidates only the org-specific cache entry.
        Always also invalidates the default (no-org) cache entry.
        """
        if org_id:
            key = f"config:{vertical}:{config_type}:{org_id}"
            _config_cache.pop(key, None)
        # Always invalidate default entry too (may be stale after default update)
        default_key = f"config:{vertical}:{config_type}:default"
        _config_cache.pop(default_key, None)
        logger.debug(
            "ConfigService cache invalidated: %s/%s org=%s",
            vertical,
            config_type,
            org_id or "default",
        )

    async def get_invalid_overrides(self) -> list[dict]:
        """Find overrides that violate their guardrails (drift detection).

        Returns list of {vertical, config_type, organization_id, errors}.
        Used by admin health dashboard to detect guardrail drift after
        default guardrails are updated.
        """
        from app.domains.admin.services.config_writer import _validate_against_guardrails

        # Single JOIN query — avoids N+1 (one query per default with guardrails)
        result = await self._db.execute(
            select(
                VerticalConfigOverride.organization_id,
                VerticalConfigOverride.vertical,
                VerticalConfigOverride.config_type,
                VerticalConfigOverride.config,
                VerticalConfigDefault.guardrails,
            ).join(
                VerticalConfigDefault,
                (VerticalConfigOverride.vertical == VerticalConfigDefault.vertical)
                & (VerticalConfigOverride.config_type == VerticalConfigDefault.config_type),
            ).where(VerticalConfigDefault.guardrails.isnot(None))
        )

        invalid: list[dict] = []
        for org_id, vertical, config_type, config, guardrails in result.all():
            errors = _validate_against_guardrails(config, guardrails)
            if errors:
                invalid.append({
                    "vertical": vertical,
                    "config_type": config_type,
                    "organization_id": str(org_id),
                    "errors": errors,
                })

        return invalid

    @staticmethod
    def deep_merge(base: dict, override: dict, *, _depth: int = 0) -> dict:
        """Recursive merge. Override values win on scalar conflicts.

        Dicts are recursively merged. Lists are REPLACED (not appended).
        _DELETE sentinel removes key (Netz admin only — client API strips None
        before merge).

        Max depth of 20 prevents stack overflow on malicious/cyclic input.
        """
        if _depth > 20:
            raise ValueError("deep_merge exceeded max depth of 20 — possible cyclic input")
        result = base.copy()
        for key, value in override.items():
            if value is _DELETE:
                result.pop(key, None)
            elif isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = ConfigService.deep_merge(result[key], value, _depth=_depth + 1)
            else:
                result[key] = value
        return result

    @staticmethod
    def _yaml_fallback(vertical: str, config_type: str) -> dict | None:
        """Emergency YAML fallback. Logged as ERROR — should never happen after migration."""
        yaml_path = _YAML_FALLBACK_MAP.get((vertical, config_type))
        if yaml_path is None:
            return None

        full_path = _YAML_FALLBACK_DIR / yaml_path
        if not full_path.exists():
            return None

        logger.error(
            "ConfigService falling back to YAML for (%s, %s) at %s "
            "— config system degraded, check migration 0004",
            vertical,
            config_type,
            full_path,
        )
        with open(full_path) as f:
            return yaml.safe_load(f)

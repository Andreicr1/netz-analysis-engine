"""
ConfigWriter — Write Methods for Vertical Configuration (Phase E)
==================================================================

Provides upsert, delete, and diff operations for config overrides.
Uses optimistic locking (version column), JSON Schema guardrails,
and pg_notify for cross-process cache invalidation.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

import jsonschema
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.config_service import ConfigService, _config_cache
from app.core.config.models import VerticalConfigDefault, VerticalConfigOverride

logger = logging.getLogger(__name__)


class GuardrailViolation(Exception):
    """Raised when config fails JSON Schema guardrail validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Guardrail validation failed: {'; '.join(errors)}")


class StaleVersionError(Exception):
    """Raised when config version doesn't match expected (optimistic lock)."""

    def __init__(self, current_version: int) -> None:
        self.current_version = current_version
        super().__init__(f"Stale version — current is {current_version}")


class ConfigWriter:
    """Write operations for vertical config overrides.

    All writes validate against guardrails, use optimistic locking,
    and emit pg_notify for cache invalidation.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def put(
        self,
        vertical: str,
        config_type: str,
        org_id: UUID,
        config: dict[str, Any],
        expected_version: int | None = None,
    ) -> int:
        """Upsert config override. Returns new version number.

        Validates config against guardrails from VerticalConfigDefault.
        Uses UPDATE...WHERE version = :expected for atomic optimistic lock.

        Raises:
            GuardrailViolation: config fails JSON Schema guardrails
            StaleVersionError: version mismatch (409 Conflict)
        """
        await self._validate_guardrails(vertical, config_type, config)

        # Check if override exists
        existing = await self._db.execute(
            select(VerticalConfigOverride).where(
                VerticalConfigOverride.vertical == vertical,
                VerticalConfigOverride.config_type == config_type,
                VerticalConfigOverride.organization_id == org_id,
            )
        )
        row = existing.scalar_one_or_none()

        if row is not None:
            # Update existing — optimistic lock
            if expected_version is not None and row.version != expected_version:
                raise StaleVersionError(current_version=row.version)

            new_version = row.version + 1
            result = await self._db.execute(
                update(VerticalConfigOverride)
                .where(
                    VerticalConfigOverride.id == row.id,
                    VerticalConfigOverride.version == row.version,
                )
                .values(config=config, version=new_version)
            )
            if result.rowcount == 0:
                # Race condition — someone else updated between our read and write
                raise StaleVersionError(current_version=row.version)
        else:
            # Insert new override
            new_version = 1
            stmt = pg_insert(VerticalConfigOverride).values(
                organization_id=org_id,
                vertical=vertical,
                config_type=config_type,
                config=config,
                version=new_version,
            )
            await self._db.execute(stmt)

        # Invalidate in-process cache
        self._invalidate_cache(vertical, config_type, org_id)

        # Notify other processes via pg_notify
        await self._notify(vertical, config_type, org_id)

        return new_version

    async def delete(
        self,
        vertical: str,
        config_type: str,
        org_id: UUID,
    ) -> bool:
        """Remove org override. Returns True if a row was deleted."""
        result = await self._db.execute(
            select(VerticalConfigOverride).where(
                VerticalConfigOverride.vertical == vertical,
                VerticalConfigOverride.config_type == config_type,
                VerticalConfigOverride.organization_id == org_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return False

        await self._db.delete(row)
        self._invalidate_cache(vertical, config_type, org_id)
        await self._notify(vertical, config_type, org_id)
        return True

    async def put_default(
        self,
        vertical: str,
        config_type: str,
        config: dict[str, Any],
    ) -> int:
        """Update global default config. Super-admin only. Returns new version."""
        result = await self._db.execute(
            select(VerticalConfigDefault).where(
                VerticalConfigDefault.vertical == vertical,
                VerticalConfigDefault.config_type == config_type,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise ValueError(f"No default config for ({vertical}, {config_type})")

        new_version = row.version + 1
        await self._db.execute(
            update(VerticalConfigDefault)
            .where(
                VerticalConfigDefault.id == row.id,
                VerticalConfigDefault.version == row.version,
            )
            .values(config=config, version=new_version)
        )
        # Invalidate all caches for this config_type (all orgs)
        self._invalidate_cache_prefix(vertical, config_type)
        await self._notify(vertical, config_type, None)
        return new_version

    async def diff(
        self,
        vertical: str,
        config_type: str,
        org_id: UUID,
    ) -> dict[str, Any]:
        """Return default, override, and merged configs for comparison."""
        default_result = await self._db.execute(
            select(VerticalConfigDefault.config).where(
                VerticalConfigDefault.vertical == vertical,
                VerticalConfigDefault.config_type == config_type,
            )
        )
        default_config = default_result.scalar_one_or_none() or {}

        override_result = await self._db.execute(
            select(
                VerticalConfigOverride.config,
                VerticalConfigOverride.version,
            ).where(
                VerticalConfigOverride.vertical == vertical,
                VerticalConfigOverride.config_type == config_type,
                VerticalConfigOverride.organization_id == org_id,
            )
        )
        override_row = override_result.first()
        override_config = override_row[0] if override_row else {}
        override_version = override_row[1] if override_row else None

        merged = ConfigService.deep_merge(default_config, override_config) if override_config else default_config

        return {
            "default": default_config,
            "override": override_config,
            "merged": merged,
            "override_version": override_version,
        }

    async def _validate_guardrails(
        self,
        vertical: str,
        config_type: str,
        config: dict[str, Any],
    ) -> None:
        """Validate config against JSON Schema guardrails from VerticalConfigDefault."""
        result = await self._db.execute(
            select(VerticalConfigDefault.guardrails).where(
                VerticalConfigDefault.vertical == vertical,
                VerticalConfigDefault.config_type == config_type,
            )
        )
        guardrails = result.scalar_one_or_none()
        if guardrails is None:
            return  # No guardrails defined — accept any config

        try:
            jsonschema.validate(instance=config, schema=guardrails)
        except jsonschema.ValidationError as e:
            # Collect all errors
            validator = jsonschema.Draft7Validator(guardrails)
            errors = [err.message for err in validator.iter_errors(config)]
            raise GuardrailViolation(errors) from e

    @staticmethod
    def _invalidate_cache(
        vertical: str, config_type: str, org_id: UUID | None
    ) -> None:
        """Remove specific key from in-process TTLCache."""
        cache_key = f"config:{vertical}:{config_type}:{org_id or 'default'}"
        _config_cache.pop(cache_key, None)

    @staticmethod
    def _invalidate_cache_prefix(vertical: str, config_type: str) -> None:
        """Remove all cache keys matching vertical+config_type (all orgs)."""
        prefix = f"config:{vertical}:{config_type}:"
        keys_to_remove = [k for k in _config_cache if k.startswith(prefix)]
        for key in keys_to_remove:
            _config_cache.pop(key, None)

    async def _notify(
        self,
        vertical: str,
        config_type: str,
        org_id: UUID | None,
    ) -> None:
        """Emit pg_notify for cross-process cache invalidation."""
        payload = json.dumps({
            "vertical": vertical,
            "config_type": config_type,
            "org_id": str(org_id) if org_id else None,
        })
        try:
            await self._db.execute(
                # pg_notify is transactional — delivered after commit
                text("SELECT pg_notify('netz_config_changed', :payload)"),
                {"payload": payload},
            )
        except Exception:
            # pg_notify failure should not break the write — cache will
            # eventually expire via TTL
            logger.warning(
                "pg_notify failed for %s/%s/%s — cache will expire via TTL",
                vertical,
                config_type,
                org_id,
                exc_info=True,
            )

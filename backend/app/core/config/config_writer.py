"""
ConfigWriter — Admin write operations for vertical config overrides.

Validates against guardrails (JSON Schema), optimistic locking via version column,
and audit logging for all mutations.
"""

from __future__ import annotations

import hashlib
import json
import logging
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.models import VerticalConfigDefault, VerticalConfigOverride
from app.domains.admin.models import AdminAuditLog

logger = logging.getLogger(__name__)


def _hash_config(config: dict) -> str:
    """SHA-256 hash of config for audit trail (not full content)."""
    return hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]


def _validate_against_guardrails(config: dict, guardrails: dict | None) -> list[str]:
    """Validate config against JSON Schema guardrails. Returns error messages."""
    if not guardrails:
        return []
    try:
        import jsonschema
        validator = jsonschema.Draft7Validator(guardrails)
        return [e.message for e in validator.iter_errors(config)]
    except Exception as e:
        logger.warning("Guardrail validation error: %s", e)
        return [str(e)]


class ConfigWriter:
    """Write operations for vertical config overrides."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def put(
        self,
        vertical: str,
        config_type: str,
        org_id: UUID,
        config: dict,
        expected_version: int,
        actor_id: str,
    ) -> dict:
        """Upsert config override with optimistic locking and guardrail validation.

        Returns the saved config with updated version.
        Raises 409 if version mismatch, 422 if guardrails fail.
        """
        # Fetch guardrails from default
        default_row = await self._db.execute(
            select(VerticalConfigDefault.guardrails, VerticalConfigDefault.config).where(
                VerticalConfigDefault.vertical == vertical,
                VerticalConfigDefault.config_type == config_type,
            )
        )
        default = default_row.one_or_none()
        if default is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No default config for {vertical}/{config_type}",
            )

        guardrails = default.guardrails

        # Validate branding specifically
        if config_type == "branding":
            from app.domains.admin.validators import validate_branding_tokens
            errors = validate_branding_tokens(config)
            if errors:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Branding validation failed: {'; '.join(errors)}",
                )

        # Validate against guardrails
        errors = _validate_against_guardrails(config, guardrails)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Guardrail validation failed: {'; '.join(errors)}",
            )

        # Get current override for before_hash
        current_row = await self._db.execute(
            select(VerticalConfigOverride).where(
                VerticalConfigOverride.vertical == vertical,
                VerticalConfigOverride.config_type == config_type,
                VerticalConfigOverride.organization_id == org_id,
            )
        )
        current = current_row.scalar_one_or_none()

        before_hash = _hash_config(current.config) if current else None
        after_hash = _hash_config(config)

        if current:
            # UPDATE path — optimistic lock
            result = await self._db.execute(
                update(VerticalConfigOverride)
                .where(
                    VerticalConfigOverride.vertical == vertical,
                    VerticalConfigOverride.config_type == config_type,
                    VerticalConfigOverride.organization_id == org_id,
                    VerticalConfigOverride.version == expected_version,
                )
                .values(config=config, version=VerticalConfigOverride.version + 1)
                .returning(VerticalConfigOverride.version)
            )
            new_version_row = result.scalar_one_or_none()
            if new_version_row is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Config was modified by another admin. Refresh and try again.",
                )
            new_version = new_version_row
        else:
            # INSERT path
            stmt = pg_insert(VerticalConfigOverride).values(
                vertical=vertical,
                config_type=config_type,
                organization_id=org_id,
                config=config,
                version=1,
            ).on_conflict_do_update(
                constraint="uq_overrides_org_vertical_type",
                set_=dict(config=config, version=VerticalConfigOverride.version + 1),
                where=(VerticalConfigOverride.version == expected_version),
            ).returning(VerticalConfigOverride.version)

            result = await self._db.execute(stmt)
            new_version = result.scalar_one_or_none()
            if new_version is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Config was modified by another admin. Refresh and try again.",
                )

        # Audit log
        self._db.add(AdminAuditLog(
            actor_id=actor_id,
            action="config.update",
            resource_type="config",
            resource_id=f"{vertical}/{config_type}",
            target_org_id=org_id,
            before_hash=before_hash,
            after_hash=after_hash,
        ))

        return {"vertical": vertical, "config_type": config_type, "version": new_version}

    async def delete_override(
        self,
        vertical: str,
        config_type: str,
        org_id: UUID,
        actor_id: str,
    ) -> None:
        """Remove override — tenant falls back to default."""
        # Get current for audit
        current_row = await self._db.execute(
            select(VerticalConfigOverride.config).where(
                VerticalConfigOverride.vertical == vertical,
                VerticalConfigOverride.config_type == config_type,
                VerticalConfigOverride.organization_id == org_id,
            )
        )
        current_config = current_row.scalar_one_or_none()

        result = await self._db.execute(
            delete(VerticalConfigOverride).where(
                VerticalConfigOverride.vertical == vertical,
                VerticalConfigOverride.config_type == config_type,
                VerticalConfigOverride.organization_id == org_id,
            )
        )

        if result.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No override found to delete",
            )

        # Audit log
        self._db.add(AdminAuditLog(
            actor_id=actor_id,
            action="config.delete",
            resource_type="config",
            resource_id=f"{vertical}/{config_type}",
            target_org_id=org_id,
            before_hash=_hash_config(current_config) if current_config else None,
            after_hash=None,
        ))

    async def put_default(
        self,
        vertical: str,
        config_type: str,
        config: dict,
        actor_id: str,
    ) -> dict:
        """Update global default config (super-admin only)."""
        current_row = await self._db.execute(
            select(VerticalConfigDefault).where(
                VerticalConfigDefault.vertical == vertical,
                VerticalConfigDefault.config_type == config_type,
            )
        )
        current = current_row.scalar_one_or_none()
        if current is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No default config for {vertical}/{config_type}",
            )

        before_hash = _hash_config(current.config)

        await self._db.execute(
            update(VerticalConfigDefault)
            .where(
                VerticalConfigDefault.vertical == vertical,
                VerticalConfigDefault.config_type == config_type,
            )
            .values(config=config, version=VerticalConfigDefault.version + 1)
        )

        # Audit
        self._db.add(AdminAuditLog(
            actor_id=actor_id,
            action="config.update_default",
            resource_type="config_default",
            resource_id=f"{vertical}/{config_type}",
            target_org_id=None,
            before_hash=before_hash,
            after_hash=_hash_config(config),
        ))

        return {"vertical": vertical, "config_type": config_type}

    async def diff(
        self,
        vertical: str,
        config_type: str,
        org_id: UUID,
    ) -> dict:
        """Return {default, override, merged, changed_keys}."""
        from app.core.config.config_service import ConfigService

        default_row = await self._db.execute(
            select(VerticalConfigDefault.config).where(
                VerticalConfigDefault.vertical == vertical,
                VerticalConfigDefault.config_type == config_type,
            )
        )
        default_config = default_row.scalar_one_or_none() or {}

        override_row = await self._db.execute(
            select(VerticalConfigOverride.config).where(
                VerticalConfigOverride.vertical == vertical,
                VerticalConfigOverride.config_type == config_type,
                VerticalConfigOverride.organization_id == org_id,
            )
        )
        override_config = override_row.scalar_one_or_none()

        merged = ConfigService.deep_merge(default_config, override_config) if override_config else default_config

        # Calculate changed keys
        changed_keys = []
        if override_config:
            for key in override_config:
                if default_config.get(key) != override_config[key]:
                    changed_keys.append(key)

        return {
            "default": default_config,
            "override": override_config,
            "merged": merged,
            "changed_keys": changed_keys,
        }

    async def validate_override(
        self,
        vertical: str,
        config_type: str,
        config: dict,
    ) -> list[str]:
        """Dry-run guardrail validation without persisting."""
        default_row = await self._db.execute(
            select(VerticalConfigDefault.guardrails).where(
                VerticalConfigDefault.vertical == vertical,
                VerticalConfigDefault.config_type == config_type,
            )
        )
        guardrails = default_row.scalar_one_or_none()
        errors = _validate_against_guardrails(config, guardrails)

        if config_type == "branding":
            from app.domains.admin.validators import validate_branding_tokens
            errors.extend(validate_branding_tokens(config))

        return errors

from __future__ import annotations

import datetime as dt
import logging
import uuid
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.models import AuditEvent

logger = logging.getLogger(__name__)


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


async def write_audit_event(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID | None = None,
    actor_id: str | None = None,
    actor_roles: list[str] | None = None,
    request_id: str | None = None,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    access_level: str = "internal",
    organization_id: uuid.UUID | None = None,
) -> None:
    """Write an audit event to the audit_events table.

    The caller must have an active RLS session (organization_id is set
    via SET LOCAL by get_db_with_rls). If organization_id is not passed
    explicitly, it is read from the current RLS context.
    """
    # Resolve organization_id from RLS context if not provided
    if organization_id is None:
        row = await db.execute(
            text("SELECT current_setting('app.current_organization_id', true)"),
        )
        org_str = row.scalar()
        if org_str:
            organization_id = uuid.UUID(org_str)

    event = AuditEvent(
        organization_id=organization_id,
        fund_id=fund_id,
        access_level=access_level,
        actor_id=actor_id or "unknown",
        actor_roles=actor_roles or [],
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before_state=_json_safe(before),
        after_state=_json_safe(after),
        request_id=request_id,
        created_by=actor_id or "unknown",
        updated_by=actor_id or "unknown",
    )
    db.add(event)
    await db.flush()
    logger.debug(
        "audit: %s entity=%s/%s actor=%s",
        action,
        entity_type,
        entity_id,
        actor_id or "unknown",
    )


async def get_audit_log(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID | None = None,
    entity_id: str | uuid.UUID | None = None,
    entity_type: str | None = None,
    limit: int = 200,
) -> list[AuditEvent]:
    """Retrieve audit events scoped by RLS (organization_id)."""
    stmt = select(AuditEvent)

    if fund_id is not None:
        stmt = stmt.where(AuditEvent.fund_id == fund_id)
    if entity_id is not None:
        stmt = stmt.where(AuditEvent.entity_id == str(entity_id))
    if entity_type:
        stmt = stmt.where(AuditEvent.entity_type == entity_type)

    stmt = stmt.order_by(AuditEvent.created_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())

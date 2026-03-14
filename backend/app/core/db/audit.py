from __future__ import annotations

import datetime as dt
import logging
import uuid
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    fund_id: uuid.UUID,
    actor_id: str | None = None,
    actor_roles: list[str] | None = None,
    request_id: str | None = None,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    access_level: str = "internal",
) -> None:
    """Write an audit event to the database.

    Logs the event details. The actual AuditEvent model insertion is
    deferred until the model is available in this repo; for now we log
    and flush a lightweight record if the model exists.
    """
    try:
        from app.core.db.models import AuditEvent

        event = AuditEvent(
            fund_id=fund_id,
            access_level=access_level,
            actor_id=actor_id or "unknown",
            actor_roles=actor_roles or [],
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            before=_json_safe(before),
            after=_json_safe(after),
            request_id=request_id or "unknown",
            created_by=actor_id or "unknown",
            updated_by=actor_id or "unknown",
        )
        db.add(event)
        await db.flush()
    except ImportError:
        logger.info(
            "audit: %s entity=%s/%s actor=%s",
            action,
            entity_type,
            entity_id,
            actor_id or "unknown",
        )


async def get_audit_log(
    db: AsyncSession,
    *,
    fund_id: uuid.UUID,
    entity_id: str | uuid.UUID,
    entity_type: str | None = None,
    limit: int = 200,
) -> list:
    """Retrieve audit events for a given entity."""
    try:
        from app.core.db.models import AuditEvent

        stmt = select(AuditEvent).where(
            AuditEvent.fund_id == fund_id,
            AuditEvent.entity_id == str(entity_id),
        )
        if entity_type:
            stmt = stmt.where(AuditEvent.entity_type == entity_type)
        stmt = stmt.order_by(AuditEvent.created_at.asc()).limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())
    except ImportError:
        return []

"""Admin audit trail routes.

Provides paginated, filterable read access to the audit_events table.
Super-admin only (cross-tenant via get_db_admin).
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db.models import AuditEvent
from app.core.security.admin_auth import require_super_admin
from app.core.security.clerk_auth import Actor
from app.core.tenancy.admin_middleware import get_db_admin

router = APIRouter(
    prefix="/admin/audit",
    tags=["admin-audit"],
    dependencies=[Depends(require_super_admin)],
)


# -- Schemas ---------------------------------------------------------------


class AuditEventResponse(BaseModel):
    """Single audit event returned to the client."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: uuid.UUID
    organization_id: uuid.UUID
    fund_id: uuid.UUID | None
    actor_id: str
    actor_roles: list[str]
    action: str
    entity_type: str
    entity_id: str
    before_state: dict[str, object] | None
    after_state: dict[str, object] | None
    request_id: str | None
    created_at: dt.datetime


class AuditListResponse(BaseModel):
    """Paginated audit event list."""

    model_config = ConfigDict(extra="forbid")

    events: list[AuditEventResponse]
    total: int
    limit: int
    offset: int


# -- Routes ----------------------------------------------------------------


@router.get("/", response_model=AuditListResponse)
async def list_audit_events(
    entity_type: str | None = Query(default=None, description="Filter by entity type (Deal, Document, Fund, etc.)"),
    action: str | None = Query(default=None, description="Filter by action (CREATE, UPDATE, DELETE)"),
    actor_id: str | None = Query(default=None, description="Filter by actor ID"),
    organization_id: uuid.UUID | None = Query(default=None, description="Filter by organization ID"),
    fund_id: uuid.UUID | None = Query(default=None, description="Filter by fund ID"),
    entity_id: str | None = Query(default=None, description="Filter by entity ID"),
    date_from: dt.datetime | None = Query(default=None, description="Start of date range (inclusive)"),
    date_to: dt.datetime | None = Query(default=None, description="End of date range (inclusive)"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_admin),
    actor: Actor = Depends(require_super_admin),
) -> AuditListResponse:
    """List audit events with pagination and filters.

    Cross-tenant read (no RLS) -- requires super_admin role.
    """
    filters = []
    if entity_type is not None:
        filters.append(AuditEvent.entity_type == entity_type)
    if action is not None:
        filters.append(AuditEvent.action == action)
    if actor_id is not None:
        filters.append(AuditEvent.actor_id == actor_id)
    if organization_id is not None:
        filters.append(AuditEvent.organization_id == organization_id)
    if fund_id is not None:
        filters.append(AuditEvent.fund_id == fund_id)
    if entity_id is not None:
        filters.append(AuditEvent.entity_id == entity_id)
    if date_from is not None:
        filters.append(AuditEvent.created_at >= date_from)
    if date_to is not None:
        filters.append(AuditEvent.created_at <= date_to)

    # Count query
    count_stmt = select(func.count(AuditEvent.id))
    if filters:
        count_stmt = count_stmt.where(*filters)
    total_result = await db.execute(count_stmt)
    total = total_result.scalar_one()

    # Data query
    stmt = select(AuditEvent)
    if filters:
        stmt = stmt.where(*filters)
    stmt = stmt.order_by(AuditEvent.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(stmt)
    events = result.scalars().all()

    return AuditListResponse(
        events=[AuditEventResponse.model_validate(e) for e in events],
        total=total,
        limit=limit,
        offset=offset,
    )

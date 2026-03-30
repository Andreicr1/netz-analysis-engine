"""Core DB models — infrastructure tables that live outside domain boundaries.

AuditEvent: RLS-scoped audit trail for entity-level changes (CREATE, UPDATE, DELETE).
Used by write_audit_event() / get_audit_log() in app.core.db.audit.
"""

from __future__ import annotations

import uuid

from sqlalchemy import String, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import (
    AuditMetaMixin,
    Base,
    IdMixin,
    OrganizationScopedMixin,
)


class AuditEvent(Base, IdMixin, OrganizationScopedMixin, AuditMetaMixin):
    """Immutable audit event for entity-level changes. RLS-scoped by organization_id.

    TimescaleDB hypertable partitioned by created_at (1-week chunks).
    Compression: 1 month. segmentby: organization_id.
    Always include created_at filter in queries for chunk pruning.

    Tracks CREATE / UPDATE / DELETE actions across all domain entities
    (Deal, Document, Fund, etc.) with optional before/after JSONB snapshots.
    """

    __tablename__ = "audit_events"

    fund_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True,
    )
    access_level: Mapped[str] = mapped_column(
        String(32), default="internal", nullable=False,
    )
    actor_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
    )
    actor_roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}",
    )
    action: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    entity_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    entity_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True,
    )
    before_state: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True,
    )
    after_state: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True,
    )
    request_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True,
    )

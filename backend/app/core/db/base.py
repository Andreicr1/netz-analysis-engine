"""SQLAlchemy Base + Mixins — Netz Analysis Engine
================================================

Unified mixins for all domain models. Every tenant-scoped table uses
OrganizationScopedMixin. Global reference tables (macro_data, allocation_blocks)
use Base directly without organization scoping.

Convention: All models use SA 2.0 Mapped[] + mapped_column() style.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import DateTime, String, Uuid, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    type_annotation_map = {
        dt.datetime: DateTime(timezone=True),
    }


class IdMixin:
    """UUID primary key mixin."""

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class OrganizationScopedMixin:
    """Multi-tenancy mixin. Every tenant-scoped table gets this.

    Global tables (macro_data, allocation_blocks) do NOT use this mixin.
    RLS policies filter on organization_id via SET LOCAL per transaction.
    """

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )


class FundScopedMixin:
    """Fund isolation mixin. Used alongside OrganizationScopedMixin."""

    fund_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )

    access_level: Mapped[str] = mapped_column(
        String(32),
        default="internal",
        index=True,
    )


class AuditMetaMixin:
    """Audit trail mixin."""

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

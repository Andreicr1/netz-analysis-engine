"""
SQLAlchemy models for vertical configuration tables.

vertical_config_defaults: Global (no RLS, no organization_id). Netz-managed.
vertical_config_overrides: Tenant-scoped (RLS on organization_id).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, IdMixin, OrganizationScopedMixin


class VerticalConfigDefault(Base, IdMixin, AuditMetaMixin):
    """Vertical-level default configuration. No RLS — shared across all tenants.

    Same pattern as macro_data and allocation_blocks.
    """

    __tablename__ = "vertical_config_defaults"
    __table_args__ = (
        UniqueConstraint("vertical", "config_type", name="uq_defaults_vertical_type"),
    )

    vertical: Mapped[str] = mapped_column(String(50), nullable=False)
    config_type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    guardrails: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


class VerticalConfigOverride(Base, IdMixin, OrganizationScopedMixin, AuditMetaMixin):
    """Tenant-specific config override. RLS enforced on organization_id.

    Stores sparse overrides — only changed fields. Deep-merged with default at read time.
    """

    __tablename__ = "vertical_config_overrides"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "vertical",
            "config_type",
            name="uq_overrides_org_vertical_type",
        ),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    vertical: Mapped[str] = mapped_column(String(50), nullable=False)
    config_type: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

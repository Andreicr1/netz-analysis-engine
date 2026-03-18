"""
SQLAlchemy models for admin infrastructure tables.

tenant_assets: Tenant-scoped (RLS on organization_id). Stores logo/favicon bytes.
prompt_overrides: Nullable organization_id (global overrides have NULL org_id).
prompt_override_versions: Version history for prompt overrides.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, IdMixin, OrganizationScopedMixin


class TenantAsset(Base, IdMixin, OrganizationScopedMixin):
    """Tenant-scoped binary assets (logos, favicons). RLS enforced."""

    __tablename__ = "tenant_assets"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "asset_type", name="uq_tenant_assets_org_type"
        ),
    )

    org_slug: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PromptOverride(Base, IdMixin):
    """Prompt template overrides. NULL organization_id = global override.

    Not using OrganizationScopedMixin because organization_id is nullable.
    RLS policy allows access to both org-scoped and global rows.
    """

    __tablename__ = "prompt_overrides"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "vertical",
            "template_name",
            name="uq_prompt_overrides_org_vertical_template",
        ),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    vertical: Mapped[str] = mapped_column(Text, nullable=False)
    template_name: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationship to version history
    versions: Mapped[list[PromptOverrideVersion]] = relationship(
        back_populates="prompt_override",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class PromptOverrideVersion(Base, IdMixin):
    """Immutable version history for prompt overrides."""

    __tablename__ = "prompt_override_versions"

    prompt_override_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("prompt_overrides.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[str] = mapped_column(Text, nullable=False)
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationship back to parent
    prompt_override: Mapped[PromptOverride] = relationship(
        back_populates="versions",
        lazy="raise",
    )


class AdminAuditLog(Base, IdMixin):
    """Immutable admin audit trail. No RLS — cross-tenant by design."""

    __tablename__ = "admin_audit_log"

    actor_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str] = mapped_column(Text, nullable=False)
    target_org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    before_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

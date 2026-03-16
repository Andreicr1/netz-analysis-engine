"""DD Report and DD Chapter ORM models.

DDReport tracks fund due diligence reports with versioning and is_current
pattern. DDChapter has direct organization_id for independent RLS isolation
with a composite FK to prevent cross-tenant references.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, OrganizationScopedMixin


class DDReport(OrganizationScopedMixin, Base):
    __tablename__ = "dd_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    fund_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="draft"
    )
    config_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    decision_anchor: Mapped[str | None] = mapped_column(String(20))
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(String(128))

    # Relationships
    chapters: Mapped[list[DDChapter]] = relationship(
        "DDChapter",
        back_populates="dd_report",
        lazy="raise",
        foreign_keys="[DDChapter.dd_report_id]",
    )


class DDChapter(OrganizationScopedMixin, Base):
    __tablename__ = "dd_chapters"
    __table_args__ = (
        ForeignKeyConstraint(
            ["dd_report_id", "organization_id"],
            ["dd_reports.id", "dd_reports.organization_id"],
            name="fk_dd_chapters_report_org",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dd_report_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    chapter_tag: Mapped[str] = mapped_column(String(50), nullable=False)
    chapter_order: Mapped[int] = mapped_column(Integer, nullable=False)
    content_md: Mapped[str | None] = mapped_column(Text)
    evidence_refs: Mapped[dict | None] = mapped_column(JSONB)
    quant_data: Mapped[dict | None] = mapped_column(JSONB)
    critic_iterations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    critic_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending"
    )
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Relationships
    dd_report: Mapped[DDReport] = relationship(
        "DDReport",
        back_populates="chapters",
        lazy="raise",
        foreign_keys="[DDChapter.dd_report_id, DDChapter.organization_id]",
        primaryjoin="and_(DDChapter.dd_report_id == DDReport.id, DDChapter.organization_id == DDReport.organization_id)",
    )

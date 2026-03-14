"""Report scheduling models for automated periodic report generation."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin


class ReportSchedule(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Defines an automated report generation schedule."""

    __tablename__ = "report_schedules"

    name: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="MONTHLY_PACK | INVESTOR_STATEMENT | EVIDENCE_PACK | FACT_SHEET",
    )
    frequency: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="MONTHLY | QUARTERLY | SEMI_ANNUAL | ANNUAL | AD_HOC",
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    next_run_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_status: Mapped[str | None] = mapped_column(
        String(32), nullable=True,
        comment="SUCCESS | FAILED | SKIPPED",
    )

    config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True,
        comment="Schedule-specific config (pack_type, recipients, etc.)",
    )

    auto_distribute: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    distribution_list: Mapped[list | None] = mapped_column(
        JSONB, server_default="[]", nullable=True,
        comment="List of recipient emails for auto-distribution",
    )

    run_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_report_schedules_fund_active", "fund_id", "is_active"),
        Index("ix_report_schedules_next_run", "next_run_date", "is_active"),
    )


class ReportRun(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Immutable record of a scheduled report execution."""

    __tablename__ = "report_runs"

    schedule_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    status: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True,
        comment="RUNNING | SUCCESS | FAILED | DISTRIBUTED",
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    output_blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    output_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    distributed_to: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    distributed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_report_runs_schedule", "schedule_id", "started_at"),
        Index("ix_report_runs_fund_type", "fund_id", "report_type"),
    )

"""WealthGeneratedReport — persistent registry of system-generated PDFs."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, IdMixin, OrganizationScopedMixin


class WealthGeneratedReport(Base, IdMixin, OrganizationScopedMixin):
    """Persistent record of every generated PDF report stored in R2.

    Decoupled from Redis TTL — provides permanent download capability
    and history browsing via storage_path.
    """
    __tablename__ = "wealth_generated_reports"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True,
    )
    report_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        # Values: "monthly_report" | "long_form_dd" | "fact_sheet"
    )
    job_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    storage_path: Mapped[str] = mapped_column(String(800), nullable=False)
    # Human-readable filename for Content-Disposition header
    display_filename: Mapped[str] = mapped_column(String(300), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default="now()", nullable=False,
    )
    generated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="completed",
        # Values: "completed" | "failed"
    )

"""Universe Approval ORM model.

Tracks instrument approval decisions for the investment universe. Fund/equity
approvals require a DD Report; bond approvals use lighter Bond Brief.
analysis_report_id is nullable for instrument types that don't require analysis.
The is_current pattern with partial unique index ensures only one active
approval per instrument per organization.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin
from app.domains.wealth.enums import UniverseDecision  # noqa: F401 — used as column doc reference


class UniverseApproval(OrganizationScopedMixin, Base):
    __tablename__ = "universe_approvals"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("instruments_universe.instrument_id"),
        nullable=False,
        index=True,
    )
    analysis_report_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("dd_reports.id"),
        nullable=True,
    )
    decision: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending",
    )  # values: see UniverseDecision enum
    rationale: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(128))
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

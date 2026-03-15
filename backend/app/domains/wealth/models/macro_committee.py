"""Macro Committee review model — CIO approval workflow for macro intelligence.

Organization-scoped (with RLS). Links to global macro_regional_snapshots
via cross-scope FK (org-scoped review referencing global snapshot).
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, IdMixin, OrganizationScopedMixin


class MacroReview(IdMixin, OrganizationScopedMixin, AuditMetaMixin, Base):
    """Macro committee review — pending/approved/rejected by CIO.

    Organization-scoped with RLS. Links to global MacroRegionalSnapshot
    via snapshot_id FK (cross-scope: org review → global snapshot).
    """

    __tablename__ = "macro_reviews"

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending",
    )
    is_emergency: Mapped[bool] = mapped_column(
        nullable=False, server_default="false",
    )
    as_of_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("macro_regional_snapshots.id"),
        nullable=True,
    )
    report_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(128))
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    decision_rationale: Mapped[str | None] = mapped_column(Text)

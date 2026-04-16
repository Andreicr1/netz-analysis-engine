"""Tenant-scoped instrument selection from the global catalog.

Links an organization to instruments they've selected for their universe,
with org-specific metadata (block assignment, approval workflow).

instruments_universe is GLOBAL (no RLS).
instruments_org is ORG-SCOPED (RLS by organization_id).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class InstrumentOrg(OrganizationScopedMixin, Base):
    __tablename__ = "instruments_org"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("instruments_universe.instrument_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("allocation_blocks.block_id"), index=True,
    )
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="pending",
    )
    selected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    source: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="manual",
    )
    block_overridden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false",
    )

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class RebalanceEvent(OrganizationScopedMixin, Base):
    __tablename__ = "rebalance_events"
    __table_args__ = (
        Index("ix_rebalance_events_profile_event_date", "profile", "event_date"),
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    trigger_reason: Mapped[str | None] = mapped_column(Text)
    weights_before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    weights_after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cvar_before: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cvar_after: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    approved_by: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    actor_source: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

"""Instrument Screening Metrics ORM model.

Stores computed quant metrics per instrument per calc_date. Used by Layer 3
of the screener engine. Source tracks provenance (yahoo_finance | csv | computed).

IMPORTANT: Has organization_id + RLS (defense-in-depth, prevents cross-tenant
leak if queried without JOIN through instruments_universe).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class InstrumentScreeningMetrics(OrganizationScopedMixin, Base):
    __tablename__ = "instrument_screening_metrics"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("instruments_universe.instrument_id"),
    )
    calc_date: Mapped[date] = mapped_column(Date, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(
        String(30), nullable=False,
    )  # yahoo_finance | csv | computed
    data_period_days: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    __table_args__ = (
        PrimaryKeyConstraint("instrument_id", "calc_date"),
    )

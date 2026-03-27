"""Strategy drift alert model — org-scoped with RLS.

TimescaleDB hypertable partitioned by detected_at (1-month chunks).
Compression: 3 months. segmentby: instrument_id.
Always include detected_at filter in queries for chunk pruning.

Persists drift detection results per instrument. Uses is_current flag
pattern (same as ScreeningResult) with partial unique index guard.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base, OrganizationScopedMixin


class StrategyDriftAlert(OrganizationScopedMixin, Base):
    __tablename__ = "strategy_drift_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("instruments_universe.instrument_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    anomalous_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_metrics: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_details: Mapped[dict] = mapped_column(JSONB, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    detected_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    snapshot_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    drift_magnitude: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    drift_threshold: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    rebalance_triggered: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    # Relationship (lazy="raise" per CLAUDE.md)
    instrument = relationship("Instrument", lazy="raise")

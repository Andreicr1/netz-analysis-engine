"""Screening Run and Screening Result ORM models.

ScreeningRun tracks a batch or on-demand screening execution.
ScreeningResult stores per-instrument outcomes with full audit trail
(layer_results JSONB includes criterion/expected/actual/passed per criterion).

is_current is a denormalized optimization — the primary query mechanism uses
run_id from the latest completed ScreeningRun. See plan for race condition fix.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class ScreeningRun(OrganizationScopedMixin, Base):
    __tablename__ = "screening_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    run_type: Mapped[str] = mapped_column(String(20), nullable=False)  # batch | on_demand
    instrument_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="running",
    )


class ScreeningResult(OrganizationScopedMixin, Base):
    __tablename__ = "screening_results"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("instruments_universe.instrument_id"),
        nullable=False,
        index=True,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("screening_runs.run_id"),
        nullable=False,
        index=True,
    )
    overall_status: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )  # PASS | FAIL | WATCHLIST
    score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    failed_at_layer: Mapped[int | None] = mapped_column(SmallInteger)
    layer_results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    required_analysis_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="dd_report",
    )  # dd_report | bond_brief | none
    screened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    is_current: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )

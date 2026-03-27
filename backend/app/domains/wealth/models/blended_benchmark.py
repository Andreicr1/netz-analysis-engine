"""Blended Benchmark models — global tables (no organization_id, no RLS).

Allows composing custom benchmarks from allocation blocks with weighted
constituents. NAV series computed dynamically from benchmark_nav returns.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base


class BlendedBenchmark(Base):
    __tablename__ = "blended_benchmarks"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    portfolio_profile: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    components: Mapped[list[BlendedBenchmarkComponent]] = relationship(
        "BlendedBenchmarkComponent",
        back_populates="benchmark",
        cascade="all, delete-orphan",
        lazy="raise",
    )


class BlendedBenchmarkComponent(Base):
    __tablename__ = "blended_benchmark_components"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    benchmark_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("blended_benchmarks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("allocation_blocks.block_id", ondelete="RESTRICT"),
        nullable=False,
    )
    weight: Mapped[float] = mapped_column(
        Numeric(6, 4), nullable=False,
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    benchmark: Mapped[BlendedBenchmark] = relationship(
        "BlendedBenchmark", back_populates="components", lazy="raise",
    )
    block = relationship("AllocationBlock", lazy="raise")

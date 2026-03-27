"""Benchmark NAV model — global table (no organization_id, no RLS).

TimescaleDB hypertable partitioned by nav_date (1-month chunks).
Compression: 3 months. segmentby: block_id.
Always include nav_date filter in queries for chunk pruning.

Stores benchmark index NAV and return data per allocation block.
Same global pattern as AllocationBlock and MacroData.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import Base


class BenchmarkNav(Base):
    __tablename__ = "benchmark_nav"

    block_id: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("allocation_blocks.block_id", ondelete="RESTRICT"),
        primary_key=True,
    )
    nav_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    nav: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    return_1d: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    return_type: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="log",
    )
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="yfinance",
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

    # Relationship (lazy="raise" per CLAUDE.md)
    block = relationship("AllocationBlock", lazy="raise")

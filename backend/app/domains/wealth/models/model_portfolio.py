"""Model Portfolio ORM model.

Represents constructed model portfolios per risk profile. Fund selection
schema stored as JSONB. No schema_version (YAGNI — fix #34).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class ModelPortfolio(OrganizationScopedMixin, Base):
    __tablename__ = "model_portfolios"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    benchmark_composite: Mapped[str | None] = mapped_column(String(255))
    inception_date: Mapped[date | None] = mapped_column(Date)
    backtest_start_date: Mapped[date | None] = mapped_column(Date)
    inception_nav: Mapped[Decimal] = mapped_column(
        Numeric(12, 4), nullable=False, server_default="1000.0",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="draft",
    )
    fund_selection_schema: Mapped[dict | None] = mapped_column(JSONB)
    backtest_result: Mapped[dict | None] = mapped_column(JSONB)
    stress_result: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    created_by: Mapped[str | None] = mapped_column(String(128))

"""Portfolio View ORM model — IC views for Black-Litterman.

Stores analyst views (absolute or relative return expectations) per model
portfolio. Used by the BL engine to compute posterior expected returns.
Org-scoped with RLS.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class PortfolioView(OrganizationScopedMixin, Base):
    __tablename__ = "portfolio_views"
    __table_args__ = (
        Index("ix_portfolio_views_portfolio_id", "portfolio_id"),
        Index(
            "ix_portfolio_views_active",
            "portfolio_id",
            "effective_from",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    asset_instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
    )
    peer_instrument_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
    )
    view_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )  # "absolute" | "relative"
    expected_return: Mapped[float] = mapped_column(
        Numeric(8, 6), nullable=False,
    )
    confidence: Mapped[float] = mapped_column(
        Numeric(4, 3), nullable=False,
    )  # 0.0 - 1.0
    rationale: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(128))
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )

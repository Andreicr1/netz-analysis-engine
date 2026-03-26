"""Model Portfolio NAV — synthetic daily NAV for model portfolios.

Mirrors nav_timeseries schema (Duck Typing) so quant analytics
can treat a model portfolio as a fund for charting and statistics.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class ModelPortfolioNav(OrganizationScopedMixin, Base):
    __tablename__ = "model_portfolio_nav"

    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_portfolios.id", ondelete="CASCADE"),
        primary_key=True,
    )
    nav_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nav: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    daily_return: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.domains.credit.portfolio.enums import ReportingFrequency


class FundInvestment(Base):
    """Asset extension table.

    Represents an investment into an underlying fund (FoF / commitment).
    Always linked 1:1 to PortfolioAsset.

    IMPORTANT: Subtype tables must never contain fund_id directly.
    Fund scoping is enforced via join to PortfolioAsset.
    """

    __tablename__ = "fund_investments"

    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("portfolio_assets.id", ondelete="CASCADE"),
        primary_key=True,
    )

    manager_name: Mapped[str] = mapped_column(String(255), nullable=False)

    underlying_fund_name: Mapped[str] = mapped_column(String(255), nullable=False)

    reporting_frequency: Mapped[ReportingFrequency] = mapped_column(
        Enum(ReportingFrequency, name="reporting_frequency_enum"),
        nullable=False,
    )

    nav_source: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )


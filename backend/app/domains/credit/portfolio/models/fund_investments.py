from __future__ import annotations

import uuid

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, OrganizationScopedMixin
from app.domains.credit.portfolio.enums import ReportingFrequency


class FundInvestment(Base, OrganizationScopedMixin, AuditMetaMixin):
    """Asset extension table.

    Represents an investment into an underlying fund (FoF / commitment).
    Always linked 1:1 to PortfolioAsset.

    PK is asset_id (not UUID id) — 1:1 with PortfolioAsset.
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

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin, OrganizationScopedMixin
from app.domains.credit.reporting.enums import NavSnapshotStatus


class NAVSnapshot(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "nav_snapshots"

    period_month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # YYYY-MM

    nav_total_usd: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    cash_balance_usd: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    assets_value_usd: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    liabilities_usd: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)

    status: Mapped[NavSnapshotStatus] = mapped_column(
        SAEnum(NavSnapshotStatus, name="nav_snapshot_status_enum"),
        nullable=False,
        default=NavSnapshotStatus.DRAFT,
        index=True,
    )

    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finalized_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    __table_args__ = (
        Index("ix_nav_snapshots_fund_period", "fund_id", "period_month"),
        Index("ix_nav_snapshots_fund_status", "fund_id", "status"),
    )

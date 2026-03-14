import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class NavTimeseries(OrganizationScopedMixin, Base):
    __tablename__ = "nav_timeseries"

    fund_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("funds_universe.fund_id"), primary_key=True
    )
    nav_date: Mapped[date] = mapped_column(Date, primary_key=True)
    nav: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    return_1d: Mapped[Decimal | None] = mapped_column(Numeric(12, 8))
    aum_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    source: Mapped[str | None] = mapped_column(String(30))
    return_type: Mapped[str] = mapped_column(String(10), nullable=False, server_default="arithmetic")

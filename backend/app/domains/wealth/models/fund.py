import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class Fund(OrganizationScopedMixin, Base):
    __tablename__ = "funds_universe"

    fund_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    isin: Mapped[str | None] = mapped_column(String(12), unique=True)
    ticker: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    manager_name: Mapped[str | None] = mapped_column(String(255))
    fund_type: Mapped[str | None] = mapped_column(String(50))
    geography: Mapped[str | None] = mapped_column(String(50), index=True)
    asset_class: Mapped[str | None] = mapped_column(String(50))
    sub_category: Mapped[str | None] = mapped_column(String(80))
    block_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("allocation_blocks.block_id"), index=True
    )
    currency: Mapped[str | None] = mapped_column(String(3))
    domicile: Mapped[str | None] = mapped_column(String(50))
    liquidity_days: Mapped[int | None] = mapped_column(Integer)
    aum_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    inception_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    data_source: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

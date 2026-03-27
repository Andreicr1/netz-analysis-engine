import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class PortfolioSnapshot(OrganizationScopedMixin, Base):
    """TimescaleDB hypertable partitioned by snapshot_date (1-month chunks).

    Compression: 3 months. segmentby: organization_id.
    Always include snapshot_date filter in queries for chunk pruning.
    """

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        UniqueConstraint("organization_id", "profile", "snapshot_date"),
        Index("ix_portfolio_snapshots_profile_snapshot_date", "profile", "snapshot_date"),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    profile: Mapped[str] = mapped_column(String(20), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    weights: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fund_selection: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cvar_current: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cvar_limit: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cvar_utilized_pct: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    trigger_status: Mapped[str | None] = mapped_column(String(20))
    consecutive_breach_days: Mapped[int] = mapped_column(Integer, server_default="0")
    regime: Mapped[str | None] = mapped_column(String(20))
    core_weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    satellite_weight: Mapped[Decimal | None] = mapped_column(Numeric(6, 4))
    regime_probs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    cvar_lower_5: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    cvar_upper_95: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))

"""DEPRECATED: Fund ORM model — use Instrument (instrument.py) instead.

The Fund model maps to the legacy ``funds_universe`` table. New code MUST use
the polymorphic :class:`Instrument` model (``instruments_universe`` table) which
supports fund, bond, and equity types via ``instrument_type`` + JSONB attributes.

This file is retained only for backward compatibility with existing routes and
workers that still query ``funds_universe``.  It will be removed alongside
migration 0012 (``DROP TABLE funds_universe``) in a dedicated cleanup PR.

See also: SR-4 audit finding (dual model path Fund/Instrument).
"""

import uuid
import warnings
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

# Emit a deprecation warning when this module is imported so that new code
# referencing Fund is flagged during development / test runs.
warnings.warn(
    "Fund model (funds_universe) is deprecated — use Instrument "
    "(instruments_universe) instead.  See SR-4 audit finding.",
    DeprecationWarning,
    stacklevel=2,
)


class Fund(OrganizationScopedMixin, Base):
    """DEPRECATED: Use :class:`Instrument` for all new code."""
    __tablename__ = "funds_universe"

    fund_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    isin: Mapped[str | None] = mapped_column(String(12))
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
    approval_status: Mapped[str | None] = mapped_column(
        String(20), server_default="pending_dd"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

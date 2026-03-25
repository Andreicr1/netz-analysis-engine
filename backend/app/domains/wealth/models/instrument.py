"""Instrument Universe ORM model.

Polymorphic replacement for funds_universe. Supports fund, bond, and equity
instrument types via a shared table with type-specific JSONB attributes.

IMPORTANT: This replaces Fund (fund.py). fund.py is DEPRECATED and will be
removed alongside migration 0012 (DROP funds_universe) in a separate PR.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base, OrganizationScopedMixin


class Instrument(OrganizationScopedMixin, Base):
    __tablename__ = "instruments_universe"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    instrument_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # fund | bond | equity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(30))
    ticker: Mapped[str | None] = mapped_column(String(20))
    bloomberg_ticker: Mapped[str | None] = mapped_column(String(30))
    asset_class: Mapped[str] = mapped_column(String(50), nullable=False)
    geography: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD"
    )
    block_id: Mapped[str | None] = mapped_column(
        String(80), ForeignKey("allocation_blocks.block_id"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    approval_status: Mapped[str] = mapped_column(
        String(20), server_default="pending"
    )
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

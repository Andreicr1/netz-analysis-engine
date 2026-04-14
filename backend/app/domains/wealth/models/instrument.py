"""Instrument Universe ORM model — GLOBAL catalog (no RLS).

Polymorphic instrument catalog shared across all tenants.
Org-specific data (block_id, approval_status) lives in instruments_org.

See instrument_org.py for tenant-scoped selection/assignment.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class Instrument(Base):
    __tablename__ = "instruments_universe"

    instrument_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    instrument_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
    )  # fund | bond | equity
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    isin: Mapped[str | None] = mapped_column(String(30))
    ticker: Mapped[str | None] = mapped_column(String(20))
    bloomberg_ticker: Mapped[str | None] = mapped_column(String(30))
    asset_class: Mapped[str] = mapped_column(String(50), nullable=False)
    geography: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD",
    )
    investment_geography: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    # GENERATED column (migration 0134) — reads from attributes->>'is_institutional'.
    # Non-institutional rows (retirement, CIT, wrap, sub-scale, etc.) are flagged
    # by the universe_sanitization worker (lock 900_063).
    is_institutional: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true",
    )
    attributes: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )

"""Capital Call and Distribution models for fund administration."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import (
    Boolean,
    Date,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin


class CapitalCall(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """A capital call notice issued to fund investors."""

    __tablename__ = "capital_calls"

    call_number: Mapped[int] = mapped_column(nullable=False)
    call_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_amount: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    purpose: Mapped[str] = mapped_column(String(500), nullable=False)
    purpose_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(32), default="DRAFT", nullable=False, index=True,
        comment="DRAFT | ISSUED | PARTIALLY_FUNDED | FULLY_FUNDED | CANCELLED",
    )

    notice_blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    total_received: Mapped[float] = mapped_column(Numeric(20, 2), default=0, nullable=False)

    deal_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_capital_calls_fund_status", "fund_id", "status"),
        Index("ix_capital_calls_fund_date", "fund_id", "call_date"),
    )


class CapitalCallAllocation(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Per-investor allocation within a capital call."""

    __tablename__ = "capital_call_allocations"

    capital_call_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    investor_name: Mapped[str] = mapped_column(String(300), nullable=False)
    investor_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    commitment_amount: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    pro_rata_pct: Mapped[float] = mapped_column(Numeric(8, 4), nullable=False)
    called_amount: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)

    paid_amount: Mapped[float] = mapped_column(Numeric(20, 2), default=0, nullable=False)
    paid_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_paid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    bank_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_cc_alloc_call", "capital_call_id"),
        Index("ix_cc_alloc_investor", "investor_id", "capital_call_id"),
    )


class Distribution(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """A distribution event to fund investors."""

    __tablename__ = "distributions"

    distribution_number: Mapped[int] = mapped_column(nullable=False)
    distribution_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    total_amount: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    distribution_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="RETURN_OF_CAPITAL | INCOME | GAIN | MIXED",
    )

    status: Mapped[str] = mapped_column(
        String(32), default="DRAFT", nullable=False, index=True,
        comment="DRAFT | APPROVED | DISTRIBUTED | CANCELLED",
    )

    source_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    notice_blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    allocations: Mapped[list | None] = mapped_column(
        JSONB, server_default="[]", nullable=True,
        comment="Per-investor distribution breakdown",
    )

    __table_args__ = (
        Index("ix_distributions_fund_status", "fund_id", "status"),
        Index("ix_distributions_fund_date", "fund_id", "distribution_date"),
    )

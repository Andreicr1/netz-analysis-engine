from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin


class Obligation(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "obligations"

    name: Mapped[str] = mapped_column(String(200), index=True)
    regulator: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # CIMA-first placeholder
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    # ── Domain-rich columns (migrated from JSON engine) ──
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # CIMA | LPA | IMA | SERVICE_CONTRACT
    frequency: Mapped[str | None] = mapped_column(String(32), nullable=True)  # ANNUAL | QUARTERLY | MONTHLY | AD_HOC
    next_due_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)
    risk_level: Mapped[str | None] = mapped_column(String(16), nullable=True)  # HIGH | MEDIUM | LOW
    responsible_party: Mapped[str | None] = mapped_column(String(200), nullable=True)
    document_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    legal_basis: Mapped[str | None] = mapped_column(String(500), nullable=True)


class ObligationRequirement(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "obligation_requirements"

    obligation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("obligations.id", ondelete="CASCADE"), index=True)
    doc_type: Mapped[str] = mapped_column(String(100), index=True)
    periodicity: Mapped[str | None] = mapped_column(String(32), nullable=True)  # monthly/annual/etc
    expiry_days: Mapped[int | None] = mapped_column(nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class ObligationStatus(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "obligation_status"

    obligation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("obligations.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)  # ok/missing/expired/unknown
    last_computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (Index("ix_obligation_status_fund_obligation", "fund_id", "obligation_id"),)


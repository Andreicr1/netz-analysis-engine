from __future__ import annotations

import uuid

from sqlalchemy import Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin


class InvestorStatement(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "investor_statements"

    investor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True, index=True)
    period_month: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # YYYY-MM

    commitment: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False, server_default="0")
    capital_called: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False, server_default="0")
    distributions: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False, server_default="0")
    ending_balance: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False, server_default="0")

    blob_path: Mapped[str] = mapped_column(String(800), nullable=False)

    __table_args__ = (
        Index("ix_investor_statements_fund_period", "fund_id", "period_month"),
    )

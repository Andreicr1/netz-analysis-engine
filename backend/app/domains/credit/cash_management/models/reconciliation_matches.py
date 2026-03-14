from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin


class ReconciliationMatch(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Append-only record of a manual reconciliation decision.

    BankStatementLine also stores the current match pointer, but this table is the
    institutional evidence of *who matched what and when*.
    """

    __tablename__ = "reconciliation_matches"

    bank_line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_statement_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cash_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cash_transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    matched_by: Mapped[str] = mapped_column(String(128), nullable=False)
    matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("bank_line_id", name="uq_reconciliation_matches_bank_line"),
        Index("ix_reconciliation_matches_fund_tx", "fund_id", "cash_transaction_id"),
    )

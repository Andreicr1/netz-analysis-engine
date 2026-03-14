from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin
from app.domains.credit.cash_management.enums import CashTransactionDirection, ReconciliationStatus


class BankStatementUpload(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Represents a bank statement document upload for manual reconciliation.
    Each upload corresponds to a statement period and is stored as immutable evidence.
    """

    __tablename__ = "bank_statement_uploads"

    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String(128), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    blob_path: Mapped[str] = mapped_column(String(800), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    __table_args__ = (Index("ix_bank_statements_fund_period", "fund_id", "period_start", "period_end"),)


class BankStatementLine(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Individual ledger line from a bank statement.
    Can be manually entered or parsed from CSV/PDF.
    Used for reconciliation against CashTransaction records.
    """

    __tablename__ = "bank_statement_lines"

    statement_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bank_statement_uploads.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    value_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
    amount_usd: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    direction: Mapped[CashTransactionDirection] = mapped_column(SAEnum(CashTransactionDirection, name="cash_direction_enum"), nullable=False)
    
    # Reconciliation fields
    matched_transaction_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("cash_transactions.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    reconciliation_status: Mapped[ReconciliationStatus] = mapped_column(
        SAEnum(ReconciliationStatus, name="reconciliation_status_enum"),
        nullable=False,
        server_default=ReconciliationStatus.UNMATCHED.value,
        index=True,
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reconciled_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reconciliation_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    __table_args__ = (
        Index("ix_bank_lines_statement_date", "statement_id", "value_date"),
        Index("ix_bank_lines_reconciliation", "reconciliation_status", "matched_transaction_id"),
    )

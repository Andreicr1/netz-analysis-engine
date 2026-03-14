from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin
from app.domains.credit.cash_management.enums import (
    CashTransactionDirection,
    CashTransactionStatus,
    CashTransactionType,
)


class FundCashAccount(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Represents the single USD bank account for a fund.
    Only one per fund is allowed (enforced via unique constraint on fund_id).
    """

    __tablename__ = "fund_cash_accounts"

    bank_name: Mapped[str] = mapped_column(
        String(200), nullable=False, server_default="Fund Bank Cayman",
    )
    administrator_name: Mapped[str] = mapped_column(
        String(200), nullable=False, server_default="Zedra",
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD",
    )
    account_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    swift_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        CheckConstraint("currency = 'USD'", name="ck_fund_cash_accounts_usd_only"),
        Index("ix_fund_cash_accounts_fund", "fund_id", unique=True),
    )


class CashAccount(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Legacy cash account model - kept for backward compatibility."""

    __tablename__ = "cash_accounts"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD",
    )
    bank_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    account_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    __table_args__ = (
        CheckConstraint("currency = 'USD'", name="ck_cash_accounts_usd_only"),
        Index("ix_cash_accounts_fund_currency", "fund_id", "currency"),
    )


class CashTransaction(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    """Core ledger of all cash movements.
    Every transaction is append-only and must have classification, justification, and evidence.
    """

    __tablename__ = "cash_transactions"

    type: Mapped[CashTransactionType] = mapped_column(
        SAEnum(CashTransactionType, name="cash_tx_type_enum"), nullable=False,
    )
    direction: Mapped[CashTransactionDirection] = mapped_column(
        SAEnum(CashTransactionDirection, name="cash_direction_enum"), nullable=False,
    )
    amount: Mapped[float] = mapped_column(Numeric(20, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="USD",
    )
    value_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reference_code: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, unique=True,
    )
    status: Mapped[CashTransactionStatus] = mapped_column(
        SAEnum(CashTransactionStatus, name="cash_tx_status_enum"),
        nullable=False,
        server_default=CashTransactionStatus.DRAFT.value,
        index=True,
    )

    # Parties / wire info (USD)
    beneficiary_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    beneficiary_bank: Mapped[str | None] = mapped_column(String(255), nullable=True)
    beneficiary_account: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intermediary_bank: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intermediary_swift: Mapped[str | None] = mapped_column(String(32), nullable=True)
    beneficiary_swift: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payment_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Governance fields
    justification_text: Mapped[str | None] = mapped_column(String(4000), nullable=True)
    policy_basis: Mapped[list[dict] | None] = mapped_column(
        JSON, nullable=True,
    )  # list[{document_id, section, excerpt}]

    investment_memo_document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), nullable=True,
    )
    ic_approvals_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0",
    )
    ic_approval_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Admin/bank execution tracking
    sent_to_admin_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    admin_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    execution_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    bank_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Reconciliation confirmation (explicit, audit-grade)
    reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    reconciled_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(4000), nullable=True)

    # Evidence pointers
    instructions_blob_uri: Mapped[str | None] = mapped_column(
        String(800), nullable=True,
    )
    evidence_bundle_blob_uri: Mapped[str | None] = mapped_column(
        String(800), nullable=True,
    )
    evidence_bundle_sha256: Mapped[str | None] = mapped_column(
        String(64), nullable=True,
    )

    # Counterparty registry linkage (nullable — legacy transactions have free-text only)
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("counterparties.id", ondelete="SET NULL"), nullable=True,
    )
    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("counterparty_bank_accounts.id", ondelete="SET NULL"), nullable=True,
    )

    # Adobe Sign e-signature
    adobe_sign_agreement_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Adobe Sign agreement ID for transfer-order e-signature tracking",
    )

    __table_args__ = (
        CheckConstraint("currency = 'USD'", name="ck_cash_transactions_usd_only"),
        Index("ix_cash_transactions_fund_status", "fund_id", "status"),
    )


class CashTransactionApproval(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "cash_transaction_approvals"

    transaction_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("cash_transactions.id", ondelete="CASCADE"), index=True,
    )
    approver_role: Mapped[str] = mapped_column(
        String(32), nullable=False,
    )  # DIRECTOR / IC_MEMBER
    approver_name: Mapped[str] = mapped_column(String(255), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    evidence_blob_uri: Mapped[str | None] = mapped_column(String(800), nullable=True)
    comment: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    __table_args__ = (
        Index("ix_cash_approvals_tx_role", "transaction_id", "approver_role"),
    )

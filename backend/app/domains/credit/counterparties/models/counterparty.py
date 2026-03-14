from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin
from app.domains.credit.counterparties.enums import (
    BankAccountChangeStatus,
    BankAccountChangeType,
    CounterpartyEntityType,
    CounterpartyStatus,
    DocumentRole,
    ServiceType,
)


class Counterparty(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "counterparties"

    entity_type: Mapped[CounterpartyEntityType] = mapped_column(
        SAEnum(CounterpartyEntityType, name="counterparty_entity_type_enum"),
        nullable=False,
    )
    legal_name: Mapped[str] = mapped_column(String(500), nullable=False)
    trading_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    country_of_incorporation: Mapped[str | None] = mapped_column(
        String(3), nullable=True,
    )
    registration_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
    )
    status: Mapped[CounterpartyStatus] = mapped_column(
        SAEnum(CounterpartyStatus, name="counterparty_status_enum"),
        nullable=False,
        server_default=CounterpartyStatus.ACTIVE.value,
    )

    # Deal linkage (for APPROVED_INVESTMENT type)
    deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("deals.id", ondelete="SET NULL"), nullable=True,
    )
    pipeline_deal_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("pipeline_deals.id", ondelete="SET NULL"), nullable=True,
    )

    # International compliance
    lei: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_jurisdiction: Mapped[str | None] = mapped_column(String(3), nullable=True)

    # Service provider fields (nullable, only for SERVICE_PROVIDER)
    service_type: Mapped[ServiceType | None] = mapped_column(
        SAEnum(ServiceType, name="service_type_enum"), nullable=True,
    )
    contract_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_value: Mapped[Decimal | None] = mapped_column(
        Numeric(20, 2), nullable=True,
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships (lazy="raise" — explicit loading only)
    bank_accounts: Mapped[list[CounterpartyBankAccount]] = relationship(
        back_populates="counterparty", lazy="raise",
    )
    documents: Mapped[list[CounterpartyDocument]] = relationship(
        back_populates="counterparty", lazy="raise",
    )

    __table_args__ = (
        # fund_id index already created by FundScopedMixin
        Index("ix_counterparties_entity_type", "entity_type"),
        Index("ix_counterparties_legal_name", "legal_name"),
        Index("ix_counterparties_status", "status"),
        Index("ix_counterparties_deal_id", "deal_id"),
        # Prevent duplicate APPROVED_INVESTMENT counterparties for the same deal (race condition guard).
        # Partial index allows multiple counterparty types (e.g. borrower + guarantor) per deal.
        sa.Index(
            "uq_counterparties_approved_investment",
            "fund_id",
            "deal_id",
            postgresql_where=sa.text(
                "entity_type = 'APPROVED_INVESTMENT' AND deal_id IS NOT NULL",
            ),
            unique=True,
        ),
    )


class CounterpartyBankAccount(Base, IdMixin, AuditMetaMixin):
    __tablename__ = "counterparty_bank_accounts"

    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("counterparties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number: Mapped[str] = mapped_column(String(100), nullable=False)
    swift_code: Mapped[str] = mapped_column(String(11), nullable=False)
    iban: Mapped[str | None] = mapped_column(String(34), nullable=True)
    intermediary_bank: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intermediary_swift: Mapped[str | None] = mapped_column(String(11), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    counterparty: Mapped[Counterparty] = relationship(
        back_populates="bank_accounts", lazy="raise",
    )

    # counterparty_id index already created by index=True on the FK column


class CounterpartyDocument(Base, IdMixin, AuditMetaMixin):
    __tablename__ = "counterparty_documents"

    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("counterparties.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_role: Mapped[DocumentRole] = mapped_column(
        SAEnum(DocumentRole, name="document_role_enum"), nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    counterparty: Mapped[Counterparty] = relationship(
        back_populates="documents", lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint(
            "counterparty_id", "document_id",
            name="uq_counterparty_document",
        ),
    )


class BankAccountChange(Base, IdMixin, AuditMetaMixin):
    __tablename__ = "bank_account_changes"

    bank_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("counterparty_bank_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    counterparty_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("counterparties.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    change_type: Mapped[BankAccountChangeType] = mapped_column(
        SAEnum(BankAccountChangeType, name="bank_account_change_type_enum"),
        nullable=False,
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[BankAccountChangeStatus] = mapped_column(
        SAEnum(BankAccountChangeStatus, name="bank_account_change_status_enum"),
        nullable=False,
        server_default=BankAccountChangeStatus.PENDING_APPROVAL.value,
    )
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    reviewed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "reviewed_by IS NULL OR reviewed_by != requested_by",
            name="ck_bank_account_changes_four_eyes",
        ),
        Index("ix_bank_account_changes_counterparty", "counterparty_id"),
        Index("ix_bank_account_changes_status", "status"),
    )

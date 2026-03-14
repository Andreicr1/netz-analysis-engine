from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Boolean, Date, ForeignKey, Index, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin


class Borrower(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "borrowers"

    legal_name: Mapped[str] = mapped_column(String(300), index=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    loans: Mapped[list["Loan"]] = relationship(back_populates="borrower")


class Loan(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "loans"

    borrower_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("borrowers.id", ondelete="RESTRICT"), index=True)
    external_reference: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    principal_amount: Mapped[float] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    interest_rate_bps: Mapped[int | None] = mapped_column(nullable=True)

    start_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    maturity_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(32), default="active", index=True)

    borrower: Mapped["Borrower"] = relationship(back_populates="loans")


class Cashflow(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "cashflows"

    loan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"), index=True)
    flow_date: Mapped[dt.date] = mapped_column(Date, index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))
    flow_type: Mapped[str] = mapped_column(String(32), index=True)  # interest/principal/fee/etc
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class Covenant(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "covenants"

    loan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    covenant_type: Mapped[str] = mapped_column(String(64), index=True)  # e.g. DSCR, leverage
    threshold: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    comparator: Mapped[str] = mapped_column(String(8), default=">=")  # >=, <=, etc.
    frequency: Mapped[str | None] = mapped_column(String(32), nullable=True)  # monthly/quarterly
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class CovenantTest(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "covenant_tests"

    covenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("covenants.id", ondelete="CASCADE"), index=True)
    tested_at: Mapped[dt.date] = mapped_column(Date, index=True)
    value: Mapped[float | None] = mapped_column(Numeric(18, 6), nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    inputs: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class CovenantBreach(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "covenant_breaches"

    covenant_test_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("covenant_tests.id", ondelete="CASCADE"),
        index=True,
        unique=True,
    )
    breach_detected_at: Mapped[dt.date] = mapped_column(Date, index=True)
    severity: Mapped[str] = mapped_column(String(32), default="warning", index=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Exposure(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "exposures"

    loan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("loans.id", ondelete="CASCADE"), index=True)
    as_of: Mapped[dt.date] = mapped_column(Date, index=True)
    exposure_amount: Mapped[float] = mapped_column(Numeric(18, 2))
    exposure_type: Mapped[str] = mapped_column(String(64), default="principal", index=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class Alert(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "portfolio_alerts"

    alert_type: Mapped[str] = mapped_column(String(32), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info", index=True)
    message: Mapped[str] = mapped_column(Text)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    entity_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (Index("ix_portfolio_alerts_fund_status", "fund_id", "status"),)


class PortfolioMetric(Base, IdMixin, FundScopedMixin, AuditMetaMixin):
    __tablename__ = "portfolio_metrics"

    as_of: Mapped[dt.date] = mapped_column(Date, index=True)
    metric_name: Mapped[str] = mapped_column(String(120), index=True)
    metric_value: Mapped[float] = mapped_column(Numeric(18, 6))
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


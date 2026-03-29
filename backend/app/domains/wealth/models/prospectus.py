"""SEC Fund Prospectus ORM models — RR1 Risk/Return Summary data.

Global tables (no RLS, no organization_id).
Source: SEC DERA RR1 bulk TSV filings.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric, SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base


class SecFundProspectusReturn(Base):
    """Annual calendar-year returns per fund series (bar chart data)."""

    __tablename__ = "sec_fund_prospectus_returns"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    annual_return_pct: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False)
    filing_date: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )


class SecFundProspectusStats(Base):
    """Fee, expense, and risk summary per fund series/class."""

    __tablename__ = "sec_fund_prospectus_stats"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    class_id: Mapped[str] = mapped_column(String, primary_key=True, server_default="")
    filing_date: Mapped[date | None] = mapped_column(Date)
    management_fee_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    expense_ratio_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    net_expense_ratio_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    fee_waiver_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    distribution_12b1_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    acquired_fund_fees_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    other_expenses_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 6))
    portfolio_turnover_pct: Mapped[Decimal | None] = mapped_column(Numeric)
    expense_example_1y: Mapped[Decimal | None] = mapped_column(Numeric)
    expense_example_3y: Mapped[Decimal | None] = mapped_column(Numeric)
    expense_example_5y: Mapped[Decimal | None] = mapped_column(Numeric)
    expense_example_10y: Mapped[Decimal | None] = mapped_column(Numeric)
    bar_chart_best_qtr_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    bar_chart_worst_qtr_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    bar_chart_ytd_pct: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    avg_annual_return_1y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    avg_annual_return_5y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    avg_annual_return_10y: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

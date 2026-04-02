"""Portfolio module models — stub for Sprint 2b.

Loan, Covenant, CovenantTest, CovenantBreach were operational module models
removed from scope. These stubs prevent import errors in ai_engine and
dashboard routes that still reference them.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, Boolean, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin, OrganizationScopedMixin


class Loan(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""

    __tablename__ = "loans_stub"


class Covenant(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""

    __tablename__ = "covenants_stub"

    name: Mapped[str | None] = mapped_column(String(200), nullable=True)


class CovenantTest(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""

    __tablename__ = "covenant_tests_stub"

    covenant_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    tested_at: Mapped[dt.date | None] = mapped_column(nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class CovenantBreach(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""

    __tablename__ = "covenant_breaches_stub"

    covenant_test_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True, index=True)
    severity: Mapped[str | None] = mapped_column(String(20), nullable=True)


class PortfolioMetric(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""

    __tablename__ = "portfolio_metrics_stub"

    as_of: Mapped[dt.date | None] = mapped_column(nullable=True, index=True)
    metric_name: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    metric_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta: Mapped[dict[str, object] | None] = mapped_column(JSON, nullable=True)

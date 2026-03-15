"""Portfolio module models — stub for Sprint 2b.

Loan, Covenant, CovenantTest, CovenantBreach were operational module models
removed from scope. These stubs prevent import errors in ai_engine and
dashboard routes that still reference them.
"""

from __future__ import annotations

from app.core.db.base import AuditMetaMixin, Base, FundScopedMixin, IdMixin, OrganizationScopedMixin


class Loan(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""
    __tablename__ = "loans_stub"


class Covenant(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""
    __tablename__ = "covenants_stub"


class CovenantTest(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""
    __tablename__ = "covenant_tests_stub"


class CovenantBreach(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""
    __tablename__ = "covenant_breaches_stub"


class PortfolioMetric(Base, IdMixin, OrganizationScopedMixin, FundScopedMixin, AuditMetaMixin):
    """Stub — operational module, not in analytical scope."""
    __tablename__ = "portfolio_metrics_stub"

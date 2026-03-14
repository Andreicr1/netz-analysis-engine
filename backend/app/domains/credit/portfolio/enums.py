from __future__ import annotations

from enum import Enum


class AssetType(str, Enum):
    DIRECT_LOAN = "DIRECT_LOAN"
    FUND_INVESTMENT = "FUND_INVESTMENT"
    EQUITY_STAKE = "EQUITY_STAKE"
    SPV_NOTE = "SPV_NOTE"


class Strategy(str, Enum):
    CORE_DIRECT_LENDING = "CORE_DIRECT_LENDING"
    OPPORTUNISTIC = "OPPORTUNISTIC"
    DISTRESSED = "DISTRESSED"
    VENTURE_DEBT = "VENTURE_DEBT"
    FUND_OF_FUNDS = "FUND_OF_FUNDS"


class ObligationType(str, Enum):
    NAV_REPORT = "NAV_REPORT"
    COVENANT_TEST = "COVENANT_TEST"
    FINANCIAL_STATEMENT = "FINANCIAL_STATEMENT"
    AUDIT_REPORT = "AUDIT_REPORT"
    COMPLIANCE_CERT = "COMPLIANCE_CERT"


class ObligationStatus(str, Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


class AlertType(str, Enum):
    OBLIGATION_OVERDUE = "OBLIGATION_OVERDUE"
    COVENANT_BREACH = "COVENANT_BREACH"
    NAV_DEVIATION = "NAV_DEVIATION"
    MANUAL = "MANUAL"


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ActionStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class ReportingFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    ANNUAL = "ANNUAL"

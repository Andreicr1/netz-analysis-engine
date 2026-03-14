from __future__ import annotations

from enum import Enum


class ReportPackStatus(str, Enum):
    DRAFT = "DRAFT"
    GENERATED = "GENERATED"
    PUBLISHED = "PUBLISHED"


class NavSnapshotStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PUBLISHED = "PUBLISHED"


class MonthlyPackType(str, Enum):
    INVESTOR_REPORT = "INVESTOR_REPORT"
    AUDITOR_PACK = "AUDITOR_PACK"
    ADMIN_PACKAGE = "ADMIN_PACKAGE"


class ValuationMethod(str, Enum):
    AMORTIZED_COST = "AMORTIZED_COST"
    FAIR_VALUE = "FAIR_VALUE"
    MARK_TO_MARKET = "MARK_TO_MARKET"
    THIRD_PARTY_APPRAISAL = "THIRD_PARTY_APPRAISAL"


class ReportSectionType(str, Enum):
    NAV_SUMMARY = "NAV_SUMMARY"
    PORTFOLIO_EXPOSURE = "PORTFOLIO_EXPOSURE"
    OBLIGATIONS = "OBLIGATIONS"
    ACTIONS = "ACTIONS"

"""EDGAR data models — dataclasses and enums for SEC filing data.

Conventions:
- Mutable @dataclass (matches existing quant_engine convention, not frozen)
- dict[str, Any] for untyped nested structures (provenance metadata varies by source)
- str, Enum for fixed-vocabulary fields (InsiderSignalType, SignalSeverity)
- structlog for logging
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

# ── Enums ─────────────────────────────────────────────────────────


class InsiderSignalType(str, Enum):
    """Types of credit-relevant insider trading signals."""
    NET_SELLING_THRESHOLD = "net_selling_threshold"
    CLUSTER_SELLING = "cluster_selling"
    EXECUTIVE_SALE = "executive_sale"


class SignalSeverity(str, Enum):
    """Severity levels for insider trading signals."""
    WATCH = "watch"
    ELEVATED = "elevated"
    CRITICAL = "critical"


class GoingConcernVerdict(str, Enum):
    """Three-tier going concern classification."""
    CONFIRMED = "confirmed"
    MITIGATED = "mitigated"
    NONE = "none"


# ── CIK Resolution ───────────────────────────────────────────────


@dataclass
class CikResolution:
    """Result of CIK number resolution for a single entity."""
    cik: str | None
    company_name: str | None
    method: str  # "ticker", "fuzzy", "blob_light", "blob_heavy", "not_found"
    confidence: float  # 0.0-1.0


# ── Financial Data ────────────────────────────────────────────────


@dataclass
class FinancialStatements:
    """Multi-period financial statements from XBRL.

    Each statement is a list of period dicts: [{period, line_item_1, line_item_2, ...}]
    Ratios are credit-relevant only: leverage, NII coverage, ICR, DSCR.
    """
    income_statement: list[dict[str, Any]] | None = None
    balance_sheet: list[dict[str, Any]] | None = None
    cash_flow: list[dict[str, Any]] | None = None
    ratios: dict[str, float | None] = field(default_factory=dict)
    periods_available: int = 0
    source_filings: list[dict[str, Any]] = field(default_factory=list)


# ── Insider Trading ───────────────────────────────────────────────


@dataclass
class InsiderSignal:
    """Detected insider trading signal relevant to credit analysis."""
    signal_type: InsiderSignalType
    severity: SignalSeverity
    entity_name: str
    description: str
    insiders: list[dict[str, Any]]
    transactions: list[dict[str, Any]]
    aggregate_value: float
    period_days: int
    detected_at: str  # ISO date string


# ── Entity Result ─────────────────────────────────────────────────


@dataclass
class EdgarEntityResult:
    """Per-entity EDGAR data result. Never raises — errors go to warnings."""
    entity_name: str
    role: str
    cik: str | None = None
    ticker: str | None = None
    is_direct_target: bool = False
    company_name: str | None = None
    sic: str | None = None
    fiscal_year_end: str | None = None
    financials: FinancialStatements | None = None
    bdc_reit_metrics: dict[str, Any] | None = None
    am_platform_metrics: dict[str, Any] | None = None
    going_concern: dict[str, Any] | None = None
    insider_signals: list[InsiderSignal] | None = None
    warnings: list[str] = field(default_factory=list)
    also_matched_as: list[str] = field(default_factory=list)
    resolution_method: str | None = None
    resolution_confidence: float = 0.0

"""SEC data provider models — frozen dataclasses for all SEC data types.

Fully standalone: zero imports from ``app.*``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Literal

# ── CIK Resolution ───────────────────────────────────────────────


@dataclass(frozen=True)
class CikResolution:
    """Result of CIK number resolution for a single entity."""

    cik: str | None
    company_name: str | None
    method: str  # "ticker", "fuzzy", "efts", "not_found"
    confidence: float  # 0.0-1.0


# ── ADV (Investment Adviser) ─────────────────────────────────────


@dataclass(frozen=True)
class AdvManager:
    """Investment adviser profile from SEC Form ADV."""

    crd_number: str
    cik: str | None
    firm_name: str
    sec_number: str | None
    registration_status: str | None
    aum_total: int | None
    aum_discretionary: int | None
    aum_non_discretionary: int | None
    total_accounts: int | None
    fee_types: dict[str, Any] | None
    client_types: dict[str, Any] | None
    state: str | None
    country: str | None
    website: str | None
    compliance_disclosures: int | None
    last_adv_filed_at: str | None
    data_fetched_at: str | None


@dataclass(frozen=True)
class AdvFund:
    """Fund entry from SEC Form ADV Schedule D."""

    crd_number: str
    fund_name: str
    fund_id: str | None
    gross_asset_value: int | None
    fund_type: str | None
    is_fund_of_funds: bool | None
    investor_count: int | None


@dataclass(frozen=True)
class AdvTeamMember:
    """Key person from Form ADV brochure supplement."""

    crd_number: str
    person_name: str
    title: str | None
    role: str | None
    education: dict[str, Any] | None
    certifications: list[str] = field(default_factory=list)
    years_experience: int | None = None
    bio_summary: str | None = None


@dataclass(frozen=True)
class AdvBrochureSection:
    """Classified section from ADV Part 2A brochure PDF."""

    crd_number: str
    section: str  # e.g. "investment_philosophy", "risk_management"
    content: str
    filing_date: str  # ISO date


# ── 13F Holdings ─────────────────────────────────────────────────


@dataclass(frozen=True)
class ThirteenFHolding:
    """Single position from a 13F-HR quarterly filing."""

    cik: str
    report_date: str
    filing_date: str
    accession_number: str
    cusip: str
    issuer_name: str
    asset_class: str | None
    shares: int | None
    market_value: int | None  # USD (edgartools provides value in dollars)
    discretion: str | None
    voting_sole: int | None
    voting_shared: int | None
    voting_none: int | None
    sector: str | None = None


@dataclass(frozen=True)
class ThirteenFDiff:
    """Quarter-over-quarter change for a single 13F position."""

    cik: str
    cusip: str
    issuer_name: str
    quarter_from: str
    quarter_to: str
    shares_before: int | None
    shares_after: int | None
    shares_delta: int | None
    value_before: int | None
    value_after: int | None
    action: str
    weight_before: float | None
    weight_after: float | None


# ── Institutional Ownership (Reverse 13F) ────────────────────────


@dataclass(frozen=True)
class InstitutionalAllocation:
    """Single institutional investor's position in a target security."""

    filer_cik: str
    filer_name: str
    filer_type: str | None
    report_date: str
    target_cusip: str
    target_issuer: str
    market_value: int | None
    shares: int | None


class CoverageType(str, Enum):
    """SEC institutional ownership coverage classification."""

    FOUND = "found"
    PUBLIC_SECURITIES_NO_HOLDERS = "public_securities_no_holders"
    NO_PUBLIC_SECURITIES = "no_public_securities"


@dataclass(frozen=True)
class InstitutionalOwnershipResult:
    """Aggregated institutional ownership for a single entity."""

    manager_cik: str
    coverage: CoverageType
    investors: list[InstitutionalAllocation] = field(default_factory=list)
    note: str | None = None


# ── CUSIP → Ticker Mapping ──────────────────────────────────────


@dataclass(frozen=True)
class CusipTickerResult:
    """Result of CUSIP → ticker resolution via OpenFIGI batch API."""

    cusip: str
    ticker: str | None
    issuer_name: str | None
    exchange: str | None
    security_type: str | None
    figi: str | None
    composite_figi: str | None
    resolved_via: str  # "openfigi" | "unresolved"
    is_tradeable: bool


# ── N-PORT Holdings ─────────────────────────────────────────────


@dataclass(frozen=True)
class NportHolding:
    """Single position from an N-PORT monthly filing."""

    cik: str
    report_date: str
    cusip: str
    isin: str | None
    issuer_name: str | None
    asset_class: str | None
    sector: str | None
    market_value: int | None
    quantity: float | None
    currency: str | None
    pct_of_nav: float | None
    is_restricted: bool | None
    fair_value_level: str | None


# ── Registered Funds (Mutual Funds, ETFs) ──────────────────────


@dataclass(frozen=True)
class RegisteredFund:
    """Registered fund from SEC N-PORT filings (mutual fund, ETF, etc.)."""

    cik: str
    fund_name: str
    fund_type: str  # 'mutual_fund' | 'etf' | 'closed_end' | 'interval_fund'
    crd_number: str | None
    ticker: str | None
    isin: str | None
    series_id: str | None
    class_id: str | None
    total_assets: int | None
    total_shareholder_accounts: int | None
    inception_date: date | None
    fiscal_year_end: str | None
    currency: str
    domicile: str
    last_nport_date: date | None
    aum_below_threshold: bool
    data_fetched_at: datetime


@dataclass(frozen=True)
class FundStyleSnapshot:
    """Style classification snapshot derived from N-PORT holdings."""

    cik: str
    report_date: date
    style_label: str
    growth_tilt: float
    sector_weights: dict[str, float]
    equity_pct: float | None
    fixed_income_pct: float | None
    cash_pct: float | None
    confidence: float


@dataclass(frozen=True)
class FundDataAvailability:
    """Data availability matrix for a fund detail page."""

    fund_universe: Literal["registered", "private"]
    has_holdings: bool
    has_nav_history: bool
    has_style_analysis: bool
    has_portfolio_manager: bool
    has_peer_analysis: bool
    disclosure_note: str | None


# ── Generic Result Wrapper ───────────────────────────────────────


@dataclass(frozen=True)
class SeriesFetchResult:
    """Generic wrapper for SEC data fetches with staleness metadata."""

    data: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_stale: bool = False
    data_fetched_at: str | None = None

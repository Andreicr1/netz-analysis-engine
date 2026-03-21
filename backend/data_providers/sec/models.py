"""SEC data provider models — frozen dataclasses for all SEC data types.

Fully standalone: zero imports from ``app.*``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

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


# ── Generic Result Wrapper ───────────────────────────────────────


@dataclass(frozen=True)
class SeriesFetchResult:
    """Generic wrapper for SEC data fetches with staleness metadata."""

    data: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    is_stale: bool = False
    data_fetched_at: str | None = None

"""Pydantic schemas for SEC registered fund endpoints."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

# ── Registered Funds (N-PORT based) ──────────────────────────────────────


class RegisteredFundSummary(BaseModel):
    """Registered fund row in manager's fund list."""

    cik: str
    fund_name: str
    fund_type: str
    ticker: str | None = None
    total_assets: int | None = None
    last_nport_date: date | None = None
    style_label: str | None = None
    style_confidence: float | None = None


class RegisteredFundListResponse(BaseModel):
    """List of registered funds for a manager."""

    funds: list[RegisteredFundSummary] = Field(default_factory=list)
    total: int = 0


# ── Private Funds (Schedule D) ───────────────────────────────────────────


class PrivateFundSummary(BaseModel):
    """Private fund row from ADV Schedule D."""

    fund_name: str
    fund_type: str | None = None
    gross_asset_value: int | None = None
    investor_count: int | None = None
    is_fund_of_funds: bool | None = None


class PrivateFundListResponse(BaseModel):
    """List of private funds for a manager."""

    funds: list[PrivateFundSummary] = Field(default_factory=list)
    total: int = 0


# ── Fund Detail (Fact Sheet) ────────────────────────────────────────────


class FundFirmInfo(BaseModel):
    """Adviser firm summary embedded in fund detail."""

    crd_number: str
    firm_name: str
    aum_total: int | None = None
    compliance_disclosures: int | None = None
    state: str | None = None
    website: str | None = None


class FundTeamMember(BaseModel):
    """Portfolio manager from ADV Part 2B."""

    person_name: str
    title: str | None = None
    role: str | None = None
    years_experience: int | None = None
    certifications: list[str] = Field(default_factory=list)


class FundStyleInfo(BaseModel):
    """Latest style classification snapshot."""

    style_label: str
    growth_tilt: float
    sector_weights: dict[str, float] = Field(default_factory=dict)
    equity_pct: float | None = None
    fixed_income_pct: float | None = None
    cash_pct: float | None = None
    confidence: float
    report_date: date


class FundDataAvailabilitySchema(BaseModel):
    """Data availability matrix for conditional UI rendering."""

    fund_universe: str
    has_holdings: bool = False
    has_nav_history: bool = False
    has_style_analysis: bool = False
    has_portfolio_manager: bool = False
    has_peer_analysis: bool = False
    disclosure_note: str | None = None


class FundDetailResponse(BaseModel):
    """Full fund detail for fact sheet page."""

    cik: str
    fund_name: str
    fund_type: str
    ticker: str | None = None
    isin: str | None = None
    total_assets: int | None = None
    total_shareholder_accounts: int | None = None
    inception_date: date | None = None
    currency: str = "USD"
    domicile: str = "US"
    last_nport_date: date | None = None

    firm: FundFirmInfo | None = None
    team: list[FundTeamMember] = Field(default_factory=list)
    latest_style: FundStyleInfo | None = None
    data_availability: FundDataAvailabilitySchema


# ── Holdings (N-PORT) ────────────────────────────────────────────────────


class NportHoldingItem(BaseModel):
    """Single N-PORT holding row."""

    cusip: str | None = None
    isin: str | None = None
    issuer_name: str | None = None
    asset_class: str | None = None
    sector: str | None = None
    market_value: int | None = None
    quantity: float | None = None
    pct_of_nav: float | None = None
    currency: str | None = None
    fair_value_level: str | None = None


class NportHoldingsPage(BaseModel):
    """Paginated N-PORT holdings response."""

    holdings: list[NportHoldingItem] = Field(default_factory=list)
    available_quarters: list[date] = Field(default_factory=list)
    total_count: int = 0
    total_value: int | None = None


# ── Style History ────────────────────────────────────────────────────────


class StyleSnapshotItem(BaseModel):
    """Single quarter style snapshot."""

    report_date: date
    style_label: str
    growth_tilt: float
    sector_weights: dict[str, float] = Field(default_factory=dict)
    equity_pct: float | None = None
    fixed_income_pct: float | None = None
    cash_pct: float | None = None
    confidence: float


class StyleHistoryResponse(BaseModel):
    """Style classification history with drift detection."""

    snapshots: list[StyleSnapshotItem] = Field(default_factory=list)
    drift_detected: bool = False
    quarters_analyzed: int = 0

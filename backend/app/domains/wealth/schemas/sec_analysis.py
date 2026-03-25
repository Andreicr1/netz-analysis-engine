"""Pydantic schemas for SEC Analysis endpoints.

Request/response models for the US Fund Analysis page — CIK-based
manager search, holdings with quarter selection, style drift,
reverse CUSIP lookup, and peer comparison.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

# ═══════════════════════════════════════════════════════════════════════════
#  Sub-schemas
# ═══════════════════════════════════════════════════════════════════════════


class SecManagerItem(BaseModel):
    """Single row in the manager search results."""

    model_config = ConfigDict(from_attributes=True)

    crd_number: str
    cik: str | None = None
    firm_name: str
    registration_status: str | None = None
    aum_total: int | None = None
    state: str | None = None
    country: str | None = None
    sic: str | None = None
    sic_description: str | None = None
    last_adv_filed_at: date | None = None
    compliance_disclosures: int | None = None
    has_13f_filings: bool = False
    last_filing_date: date | None = None


class SecHoldingItem(BaseModel):
    """Single holding row with optional quarter-over-quarter deltas."""

    cusip: str
    company_name: str
    sector: str | None = None
    shares: int | None = None
    market_value: int | None = None
    pct_portfolio: float | None = None
    delta_shares: int | None = None
    delta_value: int | None = None
    delta_action: str | None = None  # NEW_POSITION / INCREASED / DECREASED / EXITED


class SectorWeight(BaseModel):
    """Sector allocation for a single quarter."""

    quarter: str
    sector: str
    weight_pct: float


class StyleDriftSignal(BaseModel):
    """Drift signal for a sector between two quarters."""

    sector: str
    weight_current: float
    weight_prev: float
    delta: float
    signal: str  # DRIFT / STABLE


class ReverseLookupItem(BaseModel):
    """Single holder of a given CUSIP."""

    cik: str
    firm_name: str
    shares: int | None = None
    market_value: int | None = None
    pct_of_total: float | None = None
    report_date: str


class PeerHoldingOverlap(BaseModel):
    """Overlap between two managers."""

    cik_a: str
    cik_b: str
    overlap_pct: float


# ═══════════════════════════════════════════════════════════════════════════
#  Response schemas
# ═══════════════════════════════════════════════════════════════════════════


class SecManagerSearchPage(BaseModel):
    """Paginated manager search response."""

    managers: list[SecManagerItem]
    total_count: int
    page: int
    page_size: int
    has_next: bool


class SecManagerDetail(BaseModel):
    """Manager detail with latest holdings summary."""

    model_config = ConfigDict(from_attributes=True)

    crd_number: str
    cik: str | None = None
    firm_name: str
    registration_status: str | None = None
    aum_total: int | None = None
    state: str | None = None
    country: str | None = None
    website: str | None = None
    sic: str | None = None
    sic_description: str | None = None
    last_adv_filed_at: date | None = None
    latest_quarter: str | None = None
    holdings_count: int = 0
    total_portfolio_value: int | None = None


class SecHoldingsPage(BaseModel):
    """Holdings for a manager in a given quarter."""

    cik: str
    quarter: str | None = None
    available_quarters: list[str] = Field(default_factory=list)
    holdings: list[SecHoldingItem] = Field(default_factory=list)
    total_count: int = 0
    total_value: int | None = None
    page: int = 1
    page_size: int = 50
    has_next: bool = False


class SecStyleDrift(BaseModel):
    """Sector allocation history + current drift signals."""

    cik: str
    history: list[SectorWeight] = Field(default_factory=list)
    drift_signals: list[StyleDriftSignal] = Field(default_factory=list)


class SecReverseLookup(BaseModel):
    """Reverse lookup: all holders of a given CUSIP."""

    cusip: str
    company_name: str | None = None
    holders: list[ReverseLookupItem] = Field(default_factory=list)
    total_holders: int = 0


class SecPeerCompare(BaseModel):
    """Comparison of 2-5 managers."""

    managers: list[SecManagerDetail] = Field(default_factory=list)
    sector_allocations: dict[str, dict[str, float]] = Field(default_factory=dict)
    overlaps: list[PeerHoldingOverlap] = Field(default_factory=list)
    hhi_scores: dict[str, float] = Field(default_factory=dict)
    fund_breakdowns: dict[str, SecManagerFundBreakdown] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════
#  Fund breakdown schemas (A-05)
# ═══════════════════════════════════════════════════════════════════════════


class SecManagerFundItem(BaseModel):
    """Single fund-type bucket in the breakdown."""

    fund_type: str
    fund_count: int
    pct_of_total: float


class SecManagerFundBreakdown(BaseModel):
    """Fund-type breakdown for a manager."""

    crd_number: str
    total_funds: int
    breakdown: list[SecManagerFundItem] = Field(default_factory=list)


class SecSicCodeItem(BaseModel):
    """SIC code option with count."""

    sic: str
    sic_description: str | None = None
    count: int


class SecHoldingsHistoryPoint(BaseModel):
    """Single quarter data point for holdings history."""

    quarter: str
    total_holders: int
    total_market_value: int


class SecHoldingsHistory(BaseModel):
    """Quarterly institutional ownership history for a CUSIP."""

    cusip: str
    quarters: list[SecHoldingsHistoryPoint] = Field(default_factory=list)

"""Pydantic schemas for the Unified Fund Catalog.

Polymorphic UnifiedFundItem normalizes three universes (registered_us,
private_us, ucits_eu) into a single schema.  The embedded DisclosureMatrix
drives conditional UI rendering — the frontend uses it to decide which
panels/fields to show vs badge as "No Disclosure".
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class DisclosureMatrix(BaseModel):
    """Data availability flags driven by fund universe and source."""

    has_holdings: bool = False
    has_nav_history: bool = False
    has_quant_metrics: bool = False
    has_fund_details: bool = False
    has_style_analysis: bool = False
    has_13f_overlay: bool = False
    has_peer_analysis: bool = False
    holdings_source: Literal["nport", "13f"] | None = None
    nav_source: Literal["yfinance"] | None = None
    aum_source: Literal["nport", "schedule_d", "yfinance"] | None = None
    nav_status: Literal["available", "pending_import", "unavailable"] = "unavailable"


class UnifiedFundItem(BaseModel):
    """Single row in the unified fund catalog."""

    # Identity
    external_id: str
    universe: Literal["registered_us", "private_us", "ucits_eu"]
    name: str
    ticker: str | None = None
    isin: str | None = None

    # Series / share class (registered_us only)
    series_id: str | None = None
    series_name: str | None = None
    class_id: str | None = None
    class_name: str | None = None

    # Classification
    region: Literal["US", "EU"]
    fund_type: str
    strategy_label: str | None = None
    investment_geography: str | None = None
    domicile: str | None = None
    currency: str | None = None

    # Manager
    manager_name: str | None = None
    manager_id: str | None = None

    # Metrics (nullable — frontend checks disclosure)
    aum: float | None = None
    inception_date: date | None = None
    total_shareholder_accounts: int | None = None
    investor_count: int | None = None
    vintage_year: int | None = None

    # Fee & performance (from sec_fund_prospectus_stats — registered_us + etf only)
    expense_ratio_pct: float | None = None
    avg_annual_return_1y: float | None = None
    avg_annual_return_10y: float | None = None

    # N-CEN enrichment flags (registered_us only)
    is_index: bool | None = None
    is_target_date: bool | None = None
    is_fund_of_fund: bool | None = None

    # MMF metrics (money_market only — batch-enriched, not in UNION ALL)
    mmf_category: str | None = None
    seven_day_gross_yield: float | None = None
    weighted_avg_maturity: int | None = None
    weighted_avg_life: int | None = None

    # Series dedup — how many share classes exist for this series
    class_count: int = 1

    # Screening overlay (if imported to tenant universe)
    instrument_id: str | None = None
    screening_status: Literal["PASS", "FAIL", "WATCHLIST"] | None = None
    screening_score: float | None = None
    approval_status: str | None = None

    # Disclosure — drives frontend rendering
    disclosure: DisclosureMatrix


class CatalogFacetItem(BaseModel):
    value: str
    label: str
    count: int


class CatalogFacets(BaseModel):
    universes: list[CatalogFacetItem] = Field(default_factory=list)
    regions: list[CatalogFacetItem] = Field(default_factory=list)
    fund_types: list[CatalogFacetItem] = Field(default_factory=list)
    strategy_labels: list[CatalogFacetItem] = Field(default_factory=list)
    geographies: list[CatalogFacetItem] = Field(default_factory=list)
    domiciles: list[CatalogFacetItem] = Field(default_factory=list)
    total: int = 0


class UnifiedCatalogPage(BaseModel):
    items: list[UnifiedFundItem]
    total: int
    page: int
    page_size: int
    has_next: bool
    facets: CatalogFacets | None = None


class ManagerCatalogItem(BaseModel):
    """Single row in the manager-grouped catalog (Level 1)."""

    manager_id: str
    manager_name: str
    total_aum: float | None = None
    fund_count: int = 0
    fund_types: list[str] = Field(default_factory=list)
    # Enriched from sec_managers (joined server-side)
    state: str | None = None
    country: str | None = None
    website: str | None = None


class ManagerCatalogPage(BaseModel):
    items: list[ManagerCatalogItem]
    total: int
    page: int
    page_size: int
    has_next: bool


# ── Fact Sheet Support ──


class FundHolding(BaseModel):
    name: str
    cusip: str | None = None
    sector: str | None = None
    pct_of_nav: float
    market_value: float | None = None


class TeamMember(BaseModel):
    person_name: str
    title: str | None = None
    role: str | None = None
    education: str | None = None
    certifications: list[str] = Field(default_factory=list)
    years_experience: int | None = None
    bio_summary: str | None = None


class NavPoint(BaseModel):
    nav_date: date
    nav: float


class FundFactSheet(BaseModel):
    fund: UnifiedFundItem
    team: list[TeamMember] = Field(default_factory=list)
    top_holdings: list[FundHolding] = Field(default_factory=list)
    annual_returns: list[dict[str, Any]] = Field(default_factory=list)
    nav_history: list[NavPoint] = Field(default_factory=list)
    sector_history: list[dict[str, Any]] = Field(default_factory=list)
    prospectus_stats: dict[str, Any] | None = None
    share_classes: list[dict[str, Any]] = Field(default_factory=list)
    scoring_metrics: dict[str, Any] | None = None


class ShareClassItem(BaseModel):
    """Single share class within a registered fund."""

    class_id: str
    class_name: str | None = None
    ticker: str | None = None
    expense_ratio_pct: float | None = None
    net_assets: float | None = None
    avg_annual_return_pct: float | None = None
    holdings_count: int | None = None
    portfolio_turnover_pct: float | None = None
    perf_inception_date: date | None = None


class FundClassesResponse(BaseModel):
    """Share classes for a specific fund."""

    external_id: str
    fund_name: str | None = None
    classes: list[ShareClassItem] = Field(default_factory=list)
    total_classes: int = 0

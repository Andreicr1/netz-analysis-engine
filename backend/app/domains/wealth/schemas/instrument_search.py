"""Schemas for global instrument search and screener facets."""

from __future__ import annotations

from pydantic import BaseModel


class InstrumentSearchItem(BaseModel):
    instrument_id: str | None = None
    source: str  # "internal" | "esma" | "sec"
    instrument_type: str  # fund | bond | equity | etf | hedge_fund
    name: str
    isin: str | None = None
    ticker: str | None = None
    asset_class: str
    geography: str
    domicile: str | None = None
    currency: str
    strategy: str | None = None
    aum: float | None = None
    manager_name: str | None = None
    manager_crd: str | None = None
    esma_manager_id: str | None = None
    approval_status: str | None = None
    screening_status: str | None = None  # PASS | FAIL | WATCHLIST
    screening_score: float | None = None
    nav_1y_return: float | None = None
    nav_3m_return: float | None = None
    block_id: str | None = None
    structure: str | None = None  # UCITS | Cayman LP | Delaware LP | SICAV


class InstrumentSearchPage(BaseModel):
    items: list[InstrumentSearchItem]
    total: int
    page: int
    page_size: int
    has_next: bool


class FacetItem(BaseModel):
    value: str
    label: str
    count: int


class ScreenerFacets(BaseModel):
    instrument_types: list[FacetItem] = []
    geographies: list[FacetItem] = []
    asset_classes: list[FacetItem] = []
    domiciles: list[FacetItem] = []
    currencies: list[FacetItem] = []
    strategies: list[FacetItem] = []
    sources: list[FacetItem] = []
    screening_statuses: list[FacetItem] = []
    total_universe: int = 0
    total_screened: int = 0
    total_approved: int = 0


class EsmaImportRequest(BaseModel):
    block_id: str | None = None
    strategy: str | None = None

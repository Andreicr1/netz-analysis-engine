"""Discovery FCL (Fund-Centric Layout) schemas.

Pydantic v2 models backing the three-column Discovery page:

- Col1: manager list with keyset pagination.
- Col2: funds belonging to a selected manager.
- Col3 (and standalone Analysis page) consume individual fund rows.

The cursor shapes are intentionally small so they can be serialized
into URLs and survive page refreshes without leaking SQL details.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class DiscoveryFilters(BaseModel):
    strategies: list[str] | None = None
    geographies: list[str] | None = None
    fund_types: list[str] | None = None
    min_aum_usd: float | None = None
    max_expense_ratio_pct: float | None = None
    region: Literal["US", "EU", "ALL"] = "ALL"


class ManagerCursor(BaseModel):
    aum: float | None = None
    crd: str | None = None


class ManagerRow(BaseModel):
    manager_id: str
    manager_name: str
    firm_name: str | None = None
    cik: str | None = None
    aum_total: float | None = None
    fund_count: int
    fund_types: list[str]
    strategy_label_top: str | None = None


class ManagersListResponse(BaseModel):
    rows: list[ManagerRow]
    next_cursor: ManagerCursor | None = None
    total_estimate: int | None = None


class FundCursor(BaseModel):
    aum: float | None = None
    external_id: str | None = None


class FundRow(BaseModel):
    external_id: str
    universe: str
    name: str
    ticker: str | None = None
    isin: str | None = None
    fund_type: str | None = None
    strategy_label: str | None = None
    aum_usd: float | None = None
    currency: str | None = None
    domicile: str | None = None
    series_id: str | None = None
    has_holdings: bool
    has_nav: bool
    expense_ratio_pct: float | None = None
    avg_annual_return_1y: float | None = None
    avg_annual_return_10y: float | None = None


class FundsListResponse(BaseModel):
    rows: list[FundRow]
    next_cursor: FundCursor | None = None
    manager_summary: ManagerRow

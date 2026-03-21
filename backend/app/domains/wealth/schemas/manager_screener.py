"""Pydantic schemas for Manager Screener endpoints.

Request/response models for the SEC manager screening, comparison,
and universe management features.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

# ═══════════════════════════════════════════════════════════════════════════
#  Request schemas
# ═══════════════════════════════════════════════════════════════════════════


class ManagerCompareRequest(BaseModel):
    """Compare 2-5 managers side by side."""

    crd_numbers: list[str] = Field(..., min_length=2, max_length=5)


class ManagerToUniverseRequest(BaseModel):
    """Add a SEC manager to the tenant's instrument universe."""

    asset_class: str
    geography: str
    currency: str = "USD"
    block_id: str | None = None


# ═══════════════════════════════════════════════════════════════════════════
#  Response sub-schemas
# ═══════════════════════════════════════════════════════════════════════════


class ManagerFundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fund_name: str
    fund_id: str | None = None
    gross_asset_value: int | None = None
    fund_type: str | None = None
    is_fund_of_funds: bool | None = None
    investor_count: int | None = None


class ManagerTeamMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    person_name: str
    title: str | None = None
    role: str | None = None
    education: dict | None = None
    certifications: list[str] | None = None
    years_experience: int | None = None
    bio_summary: str | None = None


class HoldingRow(BaseModel):
    """Single holding in top-10 list."""

    cusip: str
    issuer_name: str
    sector: str | None = None
    market_value: int | None = None
    weight: float | None = None


class DriftQuarter(BaseModel):
    """Drift metrics for a single quarter."""

    quarter: date
    turnover: float
    new_positions: int = 0
    exited_positions: int = 0
    increased: int = 0
    decreased: int = 0
    unchanged: int = 0
    total_changes: int = 0


class InstitutionalHolder(BaseModel):
    """Single institutional holder from 13F reverse lookup."""

    filer_name: str
    filer_type: str | None = None
    filer_cik: str
    market_value: int | None = None


# ═══════════════════════════════════════════════════════════════════════════
#  Response schemas — screener list
# ═══════════════════════════════════════════════════════════════════════════


class ManagerRow(BaseModel):
    """Single row in the manager screener list."""

    model_config = ConfigDict(from_attributes=True)

    crd_number: str
    firm_name: str
    aum_total: int | None = None
    registration_status: str | None = None
    state: str | None = None
    country: str | None = None
    compliance_disclosures: int | None = None
    top_sectors: dict[str, float] = Field(default_factory=dict)
    hhi: float | None = None
    position_count: int | None = None
    drift_churn: int | None = None
    has_institutional_holders: bool = False
    universe_status: str | None = None


class ManagerScreenerPage(BaseModel):
    """Paginated screener response."""

    managers: list[ManagerRow]
    total_count: int
    page: int
    page_size: int
    has_next: bool


# ═══════════════════════════════════════════════════════════════════════════
#  Response schemas — detail tabs
# ═══════════════════════════════════════════════════════════════════════════


class ManagerProfileRead(BaseModel):
    """Profile tab — ADV fields + funds + team."""

    model_config = ConfigDict(from_attributes=True)

    crd_number: str
    cik: str | None = None
    firm_name: str
    sec_number: str | None = None
    registration_status: str | None = None
    aum_total: int | None = None
    aum_discretionary: int | None = None
    aum_non_discretionary: int | None = None
    total_accounts: int | None = None
    fee_types: dict | None = None
    client_types: dict | None = None
    state: str | None = None
    country: str | None = None
    website: str | None = None
    compliance_disclosures: int | None = None
    last_adv_filed_at: date | None = None
    funds: list[ManagerFundRead] = Field(default_factory=list)
    team: list[ManagerTeamMemberRead] = Field(default_factory=list)


class ManagerHoldingsRead(BaseModel):
    """Holdings tab — sector allocation, top 10, HHI, history."""

    sector_allocation: dict[str, float] = Field(default_factory=dict)
    top_holdings: list[HoldingRow] = Field(default_factory=list)
    hhi: float | None = None
    history: list[dict] = Field(default_factory=list)


class ManagerDriftRead(BaseModel):
    """Drift tab — quarterly turnover timeline."""

    quarters: list[DriftQuarter] = Field(default_factory=list)
    style_drift_detected: bool = False


class ManagerInstitutionalRead(BaseModel):
    """Institutional tab — 13F reverse lookup."""

    coverage_type: str = "none"  # none | partial | full
    holders: list[InstitutionalHolder] = Field(default_factory=list)


class ManagerUniverseRead(BaseModel):
    """Universe status tab."""

    instrument_id: uuid.UUID | None = None
    approval_status: str | None = None
    asset_class: str | None = None
    geography: str | None = None
    currency: str | None = None
    block_id: str | None = None
    added_at: datetime | None = None


class ManagerCompareResult(BaseModel):
    """Comparison of 2-5 managers."""

    managers: list[ManagerProfileRead]
    sector_allocations: dict[str, dict[str, float]] = Field(default_factory=dict)
    jaccard_overlap: float | None = None
    drift_comparison: list[dict] = Field(default_factory=list)

"""Universe Approval Pydantic schemas for API serialization."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class UniverseApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    instrument_id: uuid.UUID
    analysis_report_id: uuid.UUID | None = None
    decision: str
    rationale: str | None = None
    created_by: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    is_current: bool
    created_at: datetime
    # Enrichment fields (populated by route, not ORM)
    fund_name: str | None = None
    ticker: str | None = None
    block_id: str | None = None


class UniverseAssetRead(BaseModel):
    """Enriched view of an approved fund in the universe.

    Tier 1 institutional density fields (spec §3.1) are populated via
    LEFT JOIN against `fund_risk_metrics` (latest `calc_date` per
    instrument) and `nav_timeseries` (latest `aum_usd`). `None` values
    mean the worker has not produced that metric yet — the UI renders
    "—" rather than blocking.

    `correlation_to_portfolio` is populated when the caller passes
    `current_holdings=<uuid1>,<uuid2>,...` to `GET /universe`. It is
    the Pearson correlation of the candidate's daily return series
    against the equal-weight synthetic portfolio of the current
    holdings, computed in the route loader on-the-fly using
    `nav_timeseries.return_1d`. `None` when no holdings are supplied
    or when the candidate lacks sufficient NAV history (< 45 obs
    overlap with the portfolio series).
    """

    model_config = ConfigDict(extra="ignore")

    # Identity + classification
    instrument_id: uuid.UUID
    fund_name: str
    ticker: str | None = None
    isin: str | None = None
    block_id: str | None = None
    geography: str | None = None
    investment_geography: str | None = None
    asset_class: str | None = None
    approval_status: str | None = None
    approval_decision: str = "approved"
    approved_at: datetime | None = None

    # Tier 1 density — from fund_risk_metrics + nav_timeseries
    aum_usd: Decimal | None = None
    expense_ratio: Decimal | None = None
    return_3y_ann: Decimal | None = None
    return_5y_ann: Decimal | None = None
    return_10y_ann: Decimal | None = None
    sharpe_1y: Decimal | None = None
    max_drawdown_1y: Decimal | None = None
    blended_momentum_score: Decimal | None = None
    liquidity_tier: str | None = None
    manager_score: Decimal | None = None

    # Tier 1 correlation — computed on-the-fly per request
    correlation_to_portfolio: Decimal | None = None


class UniverseApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: str
    rationale: str | None = None

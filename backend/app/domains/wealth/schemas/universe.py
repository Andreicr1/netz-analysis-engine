"""Universe Approval Pydantic schemas for API serialization."""

from __future__ import annotations

import uuid
from datetime import datetime

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
    """Enriched view of an approved fund in the universe."""

    model_config = ConfigDict(extra="ignore")

    instrument_id: uuid.UUID
    fund_name: str
    ticker: str | None = None
    isin: str | None = None
    block_id: str | None = None
    geography: str | None = None
    investment_geography: str | None = None
    asset_class: str | None = None
    approval_status: str | None = None
    approval_decision: str
    approved_at: datetime | None = None


class UniverseApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="ignore")

    decision: str
    rationale: str | None = None

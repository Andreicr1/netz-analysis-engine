"""Portfolio View Pydantic schemas for API serialization."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class PortfolioViewCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    asset_instrument_id: uuid.UUID | None = None
    peer_instrument_id: uuid.UUID | None = None
    view_type: str = Field(pattern=r"^(absolute|relative)$")
    expected_return: float
    confidence: float = Field(ge=0.01, le=1.0)
    rationale: str | None = None
    effective_from: date
    effective_to: date | None = None


class PortfolioViewRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    portfolio_id: uuid.UUID
    asset_instrument_id: uuid.UUID | None = None
    peer_instrument_id: uuid.UUID | None = None
    view_type: str
    expected_return: float
    confidence: float
    rationale: str | None = None
    created_by: str | None = None
    effective_from: date
    effective_to: date | None = None
    created_at: datetime

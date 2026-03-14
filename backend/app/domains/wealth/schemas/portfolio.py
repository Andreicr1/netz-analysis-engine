import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PortfolioSummary(BaseModel):
    profile: str
    snapshot_date: date | None = None
    cvar_current: Decimal | None = None
    cvar_limit: Decimal | None = None
    cvar_utilized_pct: Decimal | None = None
    trigger_status: str | None = None
    regime: str | None = None
    core_weight: Decimal | None = None
    satellite_weight: Decimal | None = None


class PortfolioSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    snapshot_id: uuid.UUID
    profile: str
    snapshot_date: date
    weights: dict[str, Any]
    fund_selection: dict[str, Any] | None = None
    cvar_current: Decimal | None = None
    cvar_limit: Decimal | None = None
    cvar_utilized_pct: Decimal | None = None
    trigger_status: str | None = None
    consecutive_breach_days: int = 0
    regime: str | None = None
    core_weight: Decimal | None = None
    satellite_weight: Decimal | None = None
    regime_probs: dict[str, Any] | None = None
    # Bayesian credible interval bounds (negative = loss, same sign as cvar_current).
    # cvar_lower_5 is the 5th posterior percentile (worst-case tail);
    # cvar_upper_95 is the 95th percentile (best-case tail within the interval).
    # Both are None until the Bayesian CVaR worker has run for the snapshot date.
    cvar_lower_5: Decimal | None = None
    cvar_upper_95: Decimal | None = None


class RebalanceRequest(BaseModel):
    trigger_reason: str | None = Field(None, max_length=5000)


class RebalanceEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_id: uuid.UUID
    profile: str
    event_date: date
    event_type: str
    trigger_reason: str | None = None
    weights_before: dict[str, Any] | None = None
    weights_after: dict[str, Any] | None = None
    cvar_before: Decimal | None = None
    cvar_after: Decimal | None = None
    status: str
    approved_by: str | None = None
    notes: str | None = None
    created_at: datetime


class RebalanceApproveRequest(BaseModel):
    notes: str | None = Field(None, max_length=5000)

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
    computed_at: datetime | None = None


class PortfolioSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

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
    computed_at: datetime | None = None


class RebalanceRequest(BaseModel):
    trigger_reason: str | None = Field(None, max_length=5000)


class RebalanceEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

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


# ── Position & Performance schemas ──────────────────────────


class PositionDetail(BaseModel):
    """Single position in a model portfolio with cost basis and live pricing."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    instrument_id: uuid.UUID
    ticker: str | None = None
    name: str
    asset_class: str = ""
    currency: str = "USD"
    weight: Decimal = Field(..., description="Allocation weight 0.0-1.0")
    block_id: str | None = None

    # Price data (from nav_timeseries)
    last_price: Decimal | None = Field(None, description="Latest NAV/price")
    previous_close: Decimal | None = Field(None, description="Previous trading day close")
    price_date: date | None = None

    # Computed fields (populated by service layer)
    position_value: Decimal | None = Field(None, description="weight * portfolio_nav")
    intraday_pnl: Decimal | None = Field(None, description="(last_price - prev_close) * weight * portfolio_nav / last_price")
    intraday_pnl_pct: Decimal | None = Field(None, description="(last_price - prev_close) / prev_close * 100")


class PerformancePoint(BaseModel):
    """Single data point in a portfolio performance time series."""

    nav_date: date
    nav: Decimal
    daily_return: Decimal | None = None
    cumulative_return: Decimal | None = None
    benchmark_nav: Decimal | None = None
    benchmark_cumulative_return: Decimal | None = None


class PortfolioPerformanceSeries(BaseModel):
    """Historical NAV and return series for charting."""

    portfolio_id: uuid.UUID
    profile: str
    inception_date: date | None = None
    inception_nav: Decimal = Decimal("1000")
    benchmark_name: str | None = None
    series: list[PerformancePoint]
    as_of: date


# ── Drift Report schemas ──────────────────────────────────────


class BlockDriftRead(BaseModel):
    """Per-block drift between current and target weights."""

    block_id: str
    current_weight: float
    target_weight: float
    absolute_drift: float
    relative_drift: float
    status: str  # "ok" | "maintenance" | "urgent"


class DriftReportRead(BaseModel):
    """Block-level allocation drift report for a portfolio profile."""

    profile: str
    as_of_date: date
    blocks: list[BlockDriftRead]
    max_drift_pct: float
    overall_status: str  # "ok" | "maintenance" | "urgent"
    rebalance_recommended: bool
    estimated_turnover: float


class LiveDriftResponse(BaseModel):
    """Response for GET /model-portfolios/{id}/drift/live.

    Computes block-level drift using live NAV prices from nav_timeseries
    instead of stale PortfolioSnapshot weights.
    """

    portfolio_id: str
    profile: str
    as_of: date
    total_aum: float
    blocks: list[BlockDriftRead]
    max_drift_pct: float
    overall_status: str  # "ok" | "maintenance" | "urgent"
    rebalance_recommended: bool
    estimated_turnover: float
    latest_nav_date: date | None = None


# ── Monitoring Alert schemas ──────────────────────────────────


class AlertRead(BaseModel):
    """A single monitoring alert."""

    alert_type: str
    severity: str
    title: str
    detail: str
    entity_id: str | None = None
    entity_type: str | None = None


class AlertBatchRead(BaseModel):
    """Batch of alerts from a monitoring scan."""

    alerts: list[AlertRead]
    scanned_at: str
    organization_id: str

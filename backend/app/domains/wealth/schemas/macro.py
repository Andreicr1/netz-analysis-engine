"""Pydantic schemas for macroeconomic data."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MacroDataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    series_id: str
    obs_date: date
    value: float
    source: str | None = None
    is_derived: bool = False


class MacroIndicators(BaseModel):
    """Current macro indicators for regime detection."""

    vix: float | None = None
    vix_date: date | None = None
    yield_curve_10y2y: float | None = None
    yield_curve_date: date | None = None
    cpi_yoy: float | None = None
    cpi_date: date | None = None
    fed_funds_rate: float | None = None
    fed_funds_date: date | None = None


# ---------------------------------------------------------------------------
#  Regional Macro Intelligence (Phase 1)
# ---------------------------------------------------------------------------


class DataFreshnessRead(BaseModel):
    """Staleness metadata for a single indicator."""

    last_date: date | None = None
    days_stale: int | None = None
    weight: float
    status: str  # "fresh", "decaying", "stale"


class DimensionScoreRead(BaseModel):
    """Score for a single macro dimension."""

    score: float
    n_indicators: int
    indicators: dict[str, float] = {}  # series_id → percentile score


class RegionalScoreRead(BaseModel):
    """Complete macro scoring for a single region."""

    composite_score: float
    coverage: float
    dimensions: dict[str, DimensionScoreRead] = {}
    data_freshness: dict[str, DataFreshnessRead] = {}


class GlobalIndicatorsRead(BaseModel):
    """Global macro risk indicators."""

    geopolitical_risk_score: float
    energy_stress: float
    commodity_stress: float
    usd_strength: float


class MacroScoresResponse(BaseModel):
    """GET /api/wealth/macro/scores response."""

    as_of_date: date
    regions: dict[str, RegionalScoreRead]
    global_indicators: GlobalIndicatorsRead


class MacroSnapshotResponse(BaseModel):
    """GET /api/wealth/macro/snapshot response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    as_of_date: date
    data_json: dict[str, Any]


# ---------------------------------------------------------------------------
#  Phase 2: Regime Hierarchy + Committee Workflow
# ---------------------------------------------------------------------------


class RegimeHierarchyRead(BaseModel):
    """Hierarchical regime: global + per-region."""

    global_regime: str
    regional_regimes: dict[str, str]  # region → regime
    composition_reasons: dict[str, str] = {}
    as_of_date: date | None = None


class MacroReviewRead(BaseModel):
    """Macro committee review response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    status: str
    is_emergency: bool
    as_of_date: date
    snapshot_id: UUID | None = None
    report_json: dict[str, Any]
    approved_by: str | None = None
    approved_at: datetime | None = None
    decision_rationale: str | None = None
    created_at: datetime
    created_by: str | None = None


class TacticalPositionInput(BaseModel):
    """Tactical position to create on approval."""

    profile: str
    block_id: str
    overweight: float = Field(ge=-0.20, le=0.20)
    conviction_score: float | None = Field(default=None, ge=0, le=100)
    rationale: str | None = None


class MacroReviewApprove(BaseModel):
    """PATCH body for approving a macro review."""

    decision_rationale: str = Field(max_length=2000)
    tactical_positions: list[TacticalPositionInput] | None = None


class MacroReviewReject(BaseModel):
    """PATCH body for rejecting a macro review."""

    decision_rationale: str = Field(max_length=2000)

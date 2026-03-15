"""Pydantic schemas for macroeconomic data."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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

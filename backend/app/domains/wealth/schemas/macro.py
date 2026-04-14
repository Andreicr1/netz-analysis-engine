"""Pydantic schemas for macroeconomic data.

User-facing schemas here route through the Wealth sanitation layer
(`app.domains.wealth.schemas.sanitized`) so regime enums and quant
jargon are translated into the Risk Methodology v3 institutional
phrasing before reaching any API consumer. See the charter docstring
in `sanitized.py` for governance details.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.wealth.schemas.sanitized import (
    sanitize_report_json,
)


class MacroDataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

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
    analysis_text: str | None = None


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

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    as_of_date: date
    data_json: dict[str, Any]


# ---------------------------------------------------------------------------
#  Phase 2: Regime Hierarchy + Committee Workflow
# ---------------------------------------------------------------------------


class MacroReviewRead(BaseModel):
    """Macro committee review response.

    `report_json` is a free-form committee payload whose known
    jargon branches (`regime.global`, `regime.regional.*`,
    `score_components`, `metrics`) are rewritten in-place by the
    `_sanitize_report_json` after-validator. Unknown branches are
    preserved byte-for-byte.
    """

    model_config = ConfigDict(from_attributes=True, extra="ignore")

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

    @model_validator(mode="after")
    def _sanitize_report_json(self) -> MacroReviewRead:
        sanitised = sanitize_report_json(self.report_json)
        if sanitised is not None and sanitised is not self.report_json:
            object.__setattr__(self, "report_json", sanitised)
        return self


class MacroReviewApprove(BaseModel):
    """PATCH body for approving a macro review."""

    decision_rationale: str = Field(max_length=2000)


class MacroReviewReject(BaseModel):
    """PATCH body for rejecting a macro review."""

    decision_rationale: str = Field(max_length=2000)


# ---------------------------------------------------------------------------
#  Phase 3A: Raw Hypertable Data Panels
# ---------------------------------------------------------------------------


class BisTimePoint(BaseModel):
    """Single BIS data observation."""

    period: date
    value: float
    source: str = "BIS SDMX"


class BisDataResponse(BaseModel):
    """GET /macro/bis response — raw BIS time series."""

    country: str
    indicator: str
    data: list[BisTimePoint]


class ImfYearPoint(BaseModel):
    """Single IMF WEO annual observation."""

    year: int
    value: float
    source: str = "IMF WEO"
    provenance: str = "model_inference"


class ImfDataResponse(BaseModel):
    """GET /macro/imf response — raw IMF WEO forecasts."""

    country: str
    indicator: str
    data: list[ImfYearPoint]


class TreasuryTimePoint(BaseModel):
    """Single Treasury data observation."""

    obs_date: date
    value: float
    source: str = "US Treasury"


class TreasuryDataResponse(BaseModel):
    """GET /macro/treasury response — raw Treasury time series."""

    series: str
    data: list[TreasuryTimePoint]


class OfrTimePoint(BaseModel):
    """Single OFR data observation."""

    obs_date: date
    value: float
    source: str = "OFR"


class OfrDataResponse(BaseModel):
    """GET /macro/ofr response — raw OFR hedge fund data."""

    metric: str
    data: list[OfrTimePoint]


class FredTimePoint(BaseModel):
    """Single FRED / macro_data observation."""

    obs_date: date
    value: float
    source: str = "FRED"


class FredDataResponse(BaseModel):
    """GET /macro/fred response — raw FRED time series from macro_data."""

    series_id: str
    data: list[FredTimePoint]

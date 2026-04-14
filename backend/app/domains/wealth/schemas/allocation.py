from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domains.wealth.schemas.sanitized import humanize_regime


class StrategicAllocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    allocation_id: uuid.UUID
    profile: str
    block_id: str
    target_weight: Decimal
    min_weight: Decimal
    max_weight: Decimal
    risk_budget: Decimal | None = None
    rationale: str | None = None
    approved_by: str | None = None
    effective_from: date
    effective_to: date | None = None
    created_at: datetime


class StrategicAllocationItem(BaseModel):
    block_id: str
    target_weight: Decimal = Field(ge=0, le=1)
    min_weight: Decimal = Field(ge=0, le=1)
    max_weight: Decimal = Field(ge=0, le=1)
    risk_budget: Decimal | None = None
    rationale: str | None = Field(None, max_length=5000)

    @model_validator(mode="after")
    def validate_weight_bounds(self) -> StrategicAllocationItem:
        if self.min_weight > self.max_weight:
            raise ValueError("min_weight must be <= max_weight")
        if self.target_weight < self.min_weight or self.target_weight > self.max_weight:
            raise ValueError("target_weight must be between min_weight and max_weight")
        return self


class StrategicAllocationUpdate(BaseModel):
    allocations: list[StrategicAllocationItem]

    @model_validator(mode="after")
    def validate_weights_sum(self) -> StrategicAllocationUpdate:
        total = sum(a.target_weight for a in self.allocations)
        if abs(total - Decimal("1")) > Decimal("0.01"):
            raise ValueError(f"target_weight values must sum to ~1.0, got {total}")
        return self


class TacticalPositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    position_id: uuid.UUID
    profile: str
    block_id: str
    overweight: Decimal
    conviction_score: Decimal | None = None
    signal_source: str | None = None
    rationale: str | None = None
    valid_from: date
    valid_to: date | None = None
    source: str | None = "ic_manual"
    created_at: datetime


class TacticalPositionItem(BaseModel):
    block_id: str
    overweight: Decimal = Field(ge=Decimal("-0.5"), le=Decimal("0.5"))
    conviction_score: Decimal | None = None
    signal_source: str | None = None
    rationale: str | None = Field(None, max_length=5000)
    source: str | None = "ic_manual"


class TacticalPositionUpdate(BaseModel):
    positions: list[TacticalPositionItem]


class EffectiveAllocationRead(BaseModel):
    profile: str
    block_id: str
    strategic_weight: Decimal | None = None
    tactical_overweight: Decimal | None = None
    effective_weight: Decimal | None = None
    min_weight: Decimal | None = None
    max_weight: Decimal | None = None


class AllocationProposal(BaseModel):
    weights: dict[str, Decimal]  # instrument_id -> weight (0-1, sum must ~ 1.0)
    rationale: str  # min 20 chars

    @field_validator("rationale")
    @classmethod
    def rationale_min_length(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("rationale must be at least 20 characters (after stripping whitespace)")
        return v.strip()


class BlockProposalRead(BaseModel):
    """Single block in an allocation proposal."""

    block_id: str
    neutral_weight: Decimal
    proposed_weight: Decimal
    min_weight: Decimal
    max_weight: Decimal
    tilt_applied: Decimal
    tilt_source: str


class MacroAllocationProposalRead(BaseModel):
    """Allocation proposal generated from macro regime analysis."""

    profile: str
    regime: str
    proposals: list[BlockProposalRead]
    total_weight: Decimal
    rationale: str
    regional_scores: dict[str, float]


class SimulationResult(BaseModel):
    profile: str
    proposed_cvar_95_3m: Decimal | None = None
    cvar_limit: Decimal | None = None
    cvar_utilization_pct: Decimal | None = None
    cvar_delta_vs_current: Decimal | None = None  # positive = worse
    tracking_error_expected: Decimal | None = None
    within_limit: bool
    warnings: list[str] = []
    computed_at: datetime


class RegimeSignalRead(BaseModel):
    """Structured breakdown of a single regime signal."""

    key: str
    label: str
    raw_value: float | None = None
    unit: str = ""
    stress_score: float = 0.0
    weight_base: float = 0.0
    weight_effective: float = 0.0
    category: str = "financial"
    fred_series: str | None = None


class GlobalRegimeRead(BaseModel):
    """Global regime snapshot — no org context needed."""

    as_of_date: date
    raw_regime: str
    stress_score: Decimal | None = None
    signal_details: dict[str, object] = {}
    signal_breakdown: list[RegimeSignalRead] = []

    @model_validator(mode="after")
    def _humanize(self) -> "GlobalRegimeRead":
        object.__setattr__(self, "raw_regime", humanize_regime(self.raw_regime))
        return self


# ── TAA (Tactical Asset Allocation) schemas (Sprint 3) ──────────


class EffectiveBandRead(BaseModel):
    """A single block's effective band (regime-adjusted, IPS-clamped)."""

    min: float
    max: float
    center: float | None = None


class RegimeBandsRead(BaseModel):
    """Current smoothed regime centers + effective bands for a profile."""

    profile: str
    as_of_date: date
    raw_regime: str
    stress_score: Decimal | None = None
    smoothed_centers: dict[str, float]
    effective_bands: dict[str, EffectiveBandRead]
    transition_velocity: dict[str, float] | None = None
    ips_clamps_applied: list[str] = []
    taa_enabled: bool = True


class TaaHistoryRow(BaseModel):
    """Single row in the TAA regime state history."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    as_of_date: date
    raw_regime: str
    stress_score: Decimal | None = None
    smoothed_centers: dict[str, float]
    effective_bands: dict[str, dict[str, float]]
    transition_velocity: dict[str, float] | None = None
    created_at: datetime


class TaaHistoryRead(BaseModel):
    """Paginated TAA regime state history for audit."""

    profile: str
    rows: list[TaaHistoryRow]
    total: int


class RegimeBandRange(BaseModel):
    """Contiguous date range where the same regime was active."""

    start: date
    end: date
    regime: str


class RegimeOverlayRead(BaseModel):
    """Regime history overlaid on S&P500 NAV for chart rendering."""

    dates: list[date] = []
    spy_values: list[float] = []
    regime_bands: list[RegimeBandRange] = []
    period: str


class EffectiveAllocationWithRegimeRead(BaseModel):
    """Effective allocation enriched with regime-adjusted bands."""

    profile: str
    block_id: str
    strategic_weight: Decimal | None = None
    tactical_overweight: Decimal | None = None
    effective_weight: Decimal | None = None
    min_weight: Decimal | None = None
    max_weight: Decimal | None = None
    regime_min: float | None = None
    regime_max: float | None = None
    regime_center: float | None = None

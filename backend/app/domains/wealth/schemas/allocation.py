import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrategicAllocationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    def validate_weight_bounds(self):
        if self.min_weight > self.max_weight:
            raise ValueError("min_weight must be <= max_weight")
        if self.target_weight < self.min_weight or self.target_weight > self.max_weight:
            raise ValueError("target_weight must be between min_weight and max_weight")
        return self


class StrategicAllocationUpdate(BaseModel):
    allocations: list[StrategicAllocationItem]

    @model_validator(mode="after")
    def validate_weights_sum(self):
        total = sum(a.target_weight for a in self.allocations)
        if abs(total - 1) > Decimal("0.01"):
            raise ValueError(f"target_weight values must sum to ~1.0, got {total}")
        return self


class TacticalPositionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position_id: uuid.UUID
    profile: str
    block_id: str
    overweight: Decimal
    conviction_score: Decimal | None = None
    signal_source: str | None = None
    rationale: str | None = None
    valid_from: date
    valid_to: date | None = None
    created_at: datetime


class TacticalPositionItem(BaseModel):
    block_id: str
    overweight: Decimal = Field(ge=Decimal("-0.5"), le=Decimal("0.5"))
    conviction_score: Decimal | None = None
    signal_source: str | None = None
    rationale: str | None = Field(None, max_length=5000)


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

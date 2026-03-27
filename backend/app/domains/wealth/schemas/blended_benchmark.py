"""Pydantic schemas for blended benchmarks."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


class BlendedBenchmarkComponentCreate(BaseModel):
    block_id: str
    weight: Decimal = Field(gt=0, le=1)


class BlendedBenchmarkCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    components: list[BlendedBenchmarkComponentCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_weights_sum(self) -> BlendedBenchmarkCreate:
        total = sum(c.weight for c in self.components)
        if abs(total - Decimal(1)) > Decimal("0.0001"):
            msg = f"Component weights must sum to 1.0 (got {total})"
            raise ValueError(msg)
        return self


class BlendedBenchmarkComponentRead(BaseModel):
    id: uuid.UUID
    block_id: str
    weight: Decimal
    display_name: str | None = None
    benchmark_ticker: str | None = None

    model_config = {"from_attributes": True}


class BlendedBenchmarkRead(BaseModel):
    id: uuid.UUID
    portfolio_profile: str
    name: str
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime
    components: list[BlendedBenchmarkComponentRead] = []

    model_config = {"from_attributes": True}


class BlendedBenchmarkNAV(BaseModel):
    date: dt.date
    nav: float
    return_1d: float


class BlockRead(BaseModel):
    block_id: str
    display_name: str
    benchmark_ticker: str | None
    geography: str
    asset_class: str

    model_config = {"from_attributes": True}

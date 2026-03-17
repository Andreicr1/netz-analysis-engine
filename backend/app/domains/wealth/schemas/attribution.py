"""Pydantic schemas for attribution API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class SectorAttributionRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sector: str
    block_id: str
    allocation_effect: float
    selection_effect: float
    interaction_effect: float
    total_effect: float


class AttributionRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile: str
    start_date: date
    end_date: date
    granularity: str
    total_portfolio_return: float
    total_benchmark_return: float
    total_excess_return: float
    allocation_total: float
    selection_total: float
    interaction_total: float
    total_allocation_combined: float
    sectors: list[SectorAttributionRead]
    n_periods: int
    benchmark_available: bool
    benchmark_approach: str = "policy"

"""Model Portfolio Pydantic schemas for API serialization."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ModelPortfolioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    profile: str
    display_name: str
    description: str | None = None
    benchmark_composite: str | None = None
    inception_date: date | None = None
    backtest_start_date: date | None = None
    inception_nav: Decimal
    status: str
    fund_selection_schema: dict | None = None
    created_at: datetime
    created_by: str | None = None


class ModelPortfolioCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    profile: str
    display_name: str
    description: str | None = None
    benchmark_composite: str | None = None
    inception_date: date | None = None
    backtest_start_date: date | None = None


class ModelPortfolioUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    display_name: str | None = None
    description: str | None = None
    benchmark_composite: str | None = None
    inception_date: date | None = None
    backtest_start_date: date | None = None


# ── Parametric Stress Test ──────────────────────────────────────────────────


class StressTestRequest(BaseModel):
    """Request body for POST /{portfolio_id}/stress-test."""

    scenario_name: Literal[
        "gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps", "custom"
    ] = "custom"
    shocks: dict[str, float] | None = None


class StressTestResponse(BaseModel):
    """Response body for POST /{portfolio_id}/stress-test."""

    portfolio_id: str
    scenario_name: str
    nav_impact_pct: float
    cvar_stressed: float | None = None
    block_impacts: dict[str, float]
    worst_block: str | None = None
    best_block: str | None = None


# ── Holdings Overlap ──────────────────────────────────────────────────────


class CusipExposureRead(BaseModel):
    cusip: str
    issuer_name: str | None = None
    total_exposure_pct: float
    funds_holding: list[str]
    is_breach: bool


class SectorExposureRead(BaseModel):
    sector: str
    total_exposure_pct: float
    cusip_count: int


class OverlapResultRead(BaseModel):
    portfolio_id: str
    computed_at: datetime
    limit_pct: float
    total_holdings: int
    funds_analyzed: int
    funds_without_data: int
    top_cusip_exposures: list[CusipExposureRead]
    sector_exposures: list[SectorExposureRead]
    breaches: list[CusipExposureRead]
    has_sufficient_data: bool
    data_warning: str | None = None


# ── Construction Advisor ──────────────────────────────────────────────────


class BlockGapRead(BaseModel):
    block_id: str
    display_name: str
    asset_class: str
    target_weight: float
    current_weight: float
    gap_weight: float
    priority: int
    reason: str


class CoverageAnalysisRead(BaseModel):
    total_blocks: int
    covered_blocks: int
    covered_pct: float
    block_gaps: list[BlockGapRead] = []


class CandidateFundRead(BaseModel):
    block_id: str
    instrument_id: str
    name: str
    ticker: str | None = None
    strategy_label: str | None = None
    volatility_1y: float | None = None
    correlation_with_portfolio: float
    overlap_pct: float
    projected_cvar_95: float | None = None
    cvar_improvement: float
    in_universe: bool
    external_id: str
    has_holdings_data: bool = True


class MinimumViableSetRead(BaseModel):
    funds: list[str]
    projected_cvar_95: float
    projected_within_limit: bool
    blocks_filled: list[str]
    search_method: str


class AlternativeProfileRead(BaseModel):
    profile: str
    cvar_limit: float
    current_cvar_would_pass: bool


class ConstructionAdviceRead(BaseModel):
    portfolio_id: str
    profile: str
    current_cvar_95: float
    cvar_limit: float
    cvar_gap: float
    coverage: CoverageAnalysisRead
    candidates: list[CandidateFundRead] = []
    minimum_viable_set: MinimumViableSetRead | None = None
    alternative_profiles: list[AlternativeProfileRead] = []
    projected_cvar_is_heuristic: bool = True

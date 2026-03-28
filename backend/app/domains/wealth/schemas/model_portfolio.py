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

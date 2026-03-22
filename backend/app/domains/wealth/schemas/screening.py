"""Screening schemas — Pydantic models for screening runs and results."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ScreeningRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    run_id: uuid.UUID
    organization_id: uuid.UUID
    run_type: str
    instrument_count: int
    config_hash: str
    started_at: datetime
    completed_at: datetime | None = None
    status: str


class ScreeningResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    instrument_id: uuid.UUID
    run_id: uuid.UUID
    overall_status: str
    score: float | None = None
    failed_at_layer: int | None = None
    layer_results: list[dict[str, Any]]
    required_analysis_type: str
    screened_at: datetime
    is_current: bool

    # Joined from instruments_universe
    name: str | None = None
    isin: str | None = None
    ticker: str | None = None
    instrument_type: str | None = None
    block_id: str | None = None
    geography: str | None = None
    strategy: str | None = None
    currency: str | None = None
    aum: float | None = None
    manager: str | None = None
    manager_crd: str | None = None


class ScreeningRunRequest(BaseModel):
    """Request to trigger screening."""

    instrument_type: str | None = None
    block_id: str | None = None
    instrument_ids: list[uuid.UUID] | None = Field(
        default=None, max_length=100
    )


class ScreeningRunResponse(BaseModel):
    """Response after triggering a screening run."""

    run_id: uuid.UUID
    status: str
    instrument_count: int

"""Instrument schemas — Pydantic models for instruments_universe."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class InstrumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    instrument_id: uuid.UUID
    organization_id: uuid.UUID
    instrument_type: str
    name: str
    isin: str | None = None
    ticker: str | None = None
    bloomberg_ticker: str | None = None
    asset_class: str
    geography: str
    currency: str
    block_id: str | None = None
    is_active: bool
    approval_status: str
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class InstrumentCreate(BaseModel):
    instrument_type: str = Field(pattern=r"^(fund|bond|equity)$")
    name: str = Field(min_length=1, max_length=255)
    isin: str | None = None
    ticker: str | None = None
    bloomberg_ticker: str | None = None
    asset_class: str
    geography: str
    currency: str = "USD"
    block_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class InstrumentImportYahoo(BaseModel):
    """Request to import instruments via Yahoo Finance ticker(s)."""

    tickers: list[str] = Field(min_length=1, max_length=50)


class InstrumentImportCsvResponse(BaseModel):
    """Response from CSV import."""

    imported: int
    skipped: int
    errors: list[dict[str, Any]] = Field(default_factory=list)

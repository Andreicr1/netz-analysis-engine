"""Fact-Sheet Pydantic schemas for API serialization."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class FactSheetGenerate(BaseModel):
    """Request body for fact-sheet generation."""

    model_config = ConfigDict(extra="ignore")

    format: Literal["executive", "institutional"] = "executive"


class FactSheetSummary(BaseModel):
    """Summary of a generated fact-sheet."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: str  # storage path or identifier
    portfolio_id: uuid.UUID
    format: str  # "executive" or "institutional"
    language: str  # "pt" or "en"
    as_of: date
    storage_path: str
    generated_at: datetime


class FactSheetListResponse(BaseModel):
    """Response for listing fact-sheets."""

    model_config = ConfigDict(extra="ignore")

    fact_sheets: list[FactSheetSummary] = []

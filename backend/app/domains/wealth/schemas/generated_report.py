"""Pydantic schemas for unified portfolio report endpoints."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Report types known to the system ────────────────────────────────
ReportType = Literal["fact_sheet", "monthly_report"]


class ReportHistoryItem(BaseModel):
    """Single report in portfolio report history."""

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    portfolio_id: uuid.UUID
    report_type: str
    job_id: str
    display_filename: str
    generated_at: datetime
    size_bytes: int | None = None
    status: str


class ReportHistoryResponse(BaseModel):
    """GET /model-portfolios/{id}/reports response."""

    model_config = ConfigDict(extra="ignore")

    portfolio_id: uuid.UUID
    reports: list[ReportHistoryItem]
    total: int


class ReportGenerateRequest(BaseModel):
    """POST /model-portfolios/{id}/reports/generate request body."""

    model_config = ConfigDict(extra="ignore")

    report_type: ReportType
    as_of_date: date | None = Field(
        default=None,
        description="Reference date for the report. Defaults to today.",
    )
    language: Literal["pt", "en"] = "pt"
    format: Literal["executive", "institutional"] = "executive"


class ReportGenerateResponse(BaseModel):
    """POST /model-portfolios/{id}/reports/generate response."""

    model_config = ConfigDict(extra="ignore")

    job_id: str
    portfolio_id: uuid.UUID
    report_type: str
    status: str = "accepted"

"""DD Report Pydantic schemas for API serialization."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class DDChapterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    chapter_tag: str
    chapter_order: int
    content_md: str | None = None
    evidence_refs: dict | None = None
    quant_data: dict | None = None
    critic_iterations: int
    critic_status: str
    generated_at: datetime | None = None


class DDReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: uuid.UUID
    instrument_id: uuid.UUID
    report_type: str = "dd_report"
    version: int
    status: str
    confidence_score: Decimal | None = None
    decision_anchor: str | None = None
    is_current: bool
    created_at: datetime
    created_by: str | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    rejection_reason: str | None = None


class DDReportRead(DDReportSummary):
    config_snapshot: dict | None = None
    schema_version: int
    chapters: list[DDChapterRead] = []


class DDReportCreate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    config_overrides: dict | None = None


class DDReportRejectRequest(BaseModel):
    reason: str = Field(..., min_length=10, max_length=2000)


class DDReportRegenerate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapter_tags: list[str] | None = None

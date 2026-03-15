from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domains.credit.reporting.enums import MonthlyPackType, ReportPackStatus


class ReportPackCreate(BaseModel):
    period_start: date
    period_end: date


class ReportPackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    fund_id: UUID
    period_start: date
    period_end: date
    status: ReportPackStatus
    title: str

    nav_snapshot_id: UUID | None = None
    blob_path: str | None = None
    generated_at: datetime | None = None
    generated_by: str | None = None
    pack_type: MonthlyPackType | None = None

    published_at: datetime | None = None

    created_at: datetime
    updated_at: datetime


from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domains.credit.reporting.enums import ReportPackStatus


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
    created_at: datetime
    published_at: datetime | None


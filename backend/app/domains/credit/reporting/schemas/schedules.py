from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# ReportSchedule schemas
# ---------------------------------------------------------------------------


class ReportScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID

    name: str
    report_type: str
    frequency: str

    is_active: bool
    next_run_date: date | None = None
    last_run_at: datetime | None = None
    last_run_status: str | None = None

    config: dict[str, Any] | None = None

    auto_distribute: bool
    distribution_list: list[Any] | None = None

    run_count: int
    notes: str | None = None

    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# ReportRun schemas
# ---------------------------------------------------------------------------


class ReportRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID

    schedule_id: uuid.UUID
    report_type: str
    status: str

    started_at: datetime
    completed_at: datetime | None = None

    output_blob_uri: str | None = None
    output_metadata: dict[str, Any] | None = None

    error_message: str | None = None
    distributed_to: list[Any] | None = None
    distributed_at: datetime | None = None

    created_at: datetime
    updated_at: datetime

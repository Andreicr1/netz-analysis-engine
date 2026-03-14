from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ActionCreate(BaseModel):
    title: str


class ActionUpdate(BaseModel):
    status: str
    evidence_notes: str | None = None


class ActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    title: str
    status: str
    description: str | None = None

    created_at: datetime
    updated_at: datetime
    created_by: str | None = None
    updated_by: str | None = None


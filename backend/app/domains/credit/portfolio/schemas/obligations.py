from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict

from app.domains.credit.portfolio.enums import ObligationStatus, ObligationType


class ObligationCreate(BaseModel):
    obligation_type: ObligationType
    due_date: date


class ObligationUpdate(BaseModel):
    status: ObligationStatus


class ObligationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_id: uuid.UUID
    obligation_type: ObligationType
    status: ObligationStatus
    due_date: date


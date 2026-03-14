from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class InvestorStatementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID

    investor_id: uuid.UUID | None = None
    period_month: str

    commitment: Decimal
    capital_called: Decimal
    distributions: Decimal
    ending_balance: Decimal

    blob_path: str

    created_at: datetime
    updated_at: datetime

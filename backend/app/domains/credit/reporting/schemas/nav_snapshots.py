from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.domains.credit.reporting.enums import NavSnapshotStatus


class NAVSnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID

    period_month: str

    nav_total_usd: Decimal
    cash_balance_usd: Decimal
    assets_value_usd: Decimal
    liabilities_usd: Decimal

    status: NavSnapshotStatus

    finalized_at: datetime | None = None
    finalized_by: str | None = None

    published_at: datetime | None = None
    published_by: str | None = None

    created_at: datetime
    updated_at: datetime

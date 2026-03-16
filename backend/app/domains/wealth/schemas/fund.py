import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class FundRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    fund_id: uuid.UUID
    isin: str | None = None
    ticker: str | None = None
    name: str
    manager_name: str | None = None
    fund_type: str | None = None
    geography: str | None = None
    asset_class: str | None = None
    sub_category: str | None = None
    block_id: str | None = None
    currency: str | None = None
    domicile: str | None = None
    liquidity_days: int | None = None
    aum_usd: Decimal | None = None
    inception_date: date | None = None
    is_active: bool
    data_source: str | None = None
    approval_status: str | None = None
    created_at: datetime
    updated_at: datetime


class NavPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    nav_date: date
    nav: Decimal | None = None
    return_1d: Decimal | None = None
    aum_usd: Decimal | None = None
    currency: str | None = None
    source: str | None = None

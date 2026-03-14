from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

from app.domains.credit.portfolio.enums import ReportingFrequency


class FundInvestmentCreate(BaseModel):
    manager_name: str
    underlying_fund_name: str
    reporting_frequency: ReportingFrequency
    nav_source: str | None = None


class FundInvestmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    asset_id: uuid.UUID
    manager_name: str
    underlying_fund_name: str
    reporting_frequency: ReportingFrequency
    nav_source: str | None


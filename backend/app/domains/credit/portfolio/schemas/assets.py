from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.domains.credit.portfolio.enums import AssetType, Strategy


class PortfolioAssetCreate(BaseModel):
    asset_type: AssetType
    strategy: Strategy
    name: str = Field(min_length=2, max_length=255)


class PortfolioAssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fund_id: uuid.UUID
    access_level: str
    asset_type: AssetType
    strategy: Strategy
    name: str


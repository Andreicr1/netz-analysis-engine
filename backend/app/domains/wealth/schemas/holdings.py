"""Holdings Reverse Lookup — find institutional investors holding a specific asset."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel


class HoldingHolder(BaseModel):
    holder_name: str
    holder_id: str  # CIK or CRD
    holder_type: Literal["manager", "fund"]
    weight_pct: float | None = None
    market_value: float | None = None
    report_date: date | None = None


class ReverseLookupResponse(BaseModel):
    asset_name: str
    cusip: str | None = None
    isin: str | None = None
    holders: list[HoldingHolder]

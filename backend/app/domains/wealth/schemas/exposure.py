"""Exposure Monitor schemas — geographic and sector allocation heatmap data."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ExposureCell(BaseModel):
    row: str
    column: str
    weight: float


class ExposureMatrixRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    dimension: str
    aggregation: str
    rows: list[str]
    columns: list[str]
    data: list[list[float]]


class FundFreshness(BaseModel):
    fund_name: str
    last_updated_days: int


class ExposureMetadataRead(BaseModel):
    model_config = ConfigDict(extra="ignore")

    freshness: list[FundFreshness]

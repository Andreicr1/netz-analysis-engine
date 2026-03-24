"""Exposure Monitor schemas — geographic and sector allocation heatmap data."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class ExposureMatrixRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    dimension: str
    aggregation: str
    rows: list[str]
    columns: list[str]
    data: list[list[float]]
    is_empty: bool
    as_of: date | None


class ExposureMetadataRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    as_of: date | None
    snapshot_count: int
    profile_count: int

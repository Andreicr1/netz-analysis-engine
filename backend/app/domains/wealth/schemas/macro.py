"""Pydantic schemas for macroeconomic data."""

from datetime import date

from pydantic import BaseModel, ConfigDict


class MacroDataRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    series_id: str
    obs_date: date
    value: float
    source: str | None = None
    is_derived: bool = False


class MacroIndicators(BaseModel):
    """Current macro indicators for regime detection."""

    vix: float | None = None
    vix_date: date | None = None
    yield_curve_10y2y: float | None = None
    yield_curve_date: date | None = None
    cpi_yoy: float | None = None
    cpi_date: date | None = None
    fed_funds_rate: float | None = None
    fed_funds_date: date | None = None

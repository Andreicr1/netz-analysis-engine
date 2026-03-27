"""Instrument data provider protocol and shared data models.

InstrumentDataProvider defines the interface for market data sources.
CsvImportAdapter does NOT implement this protocol — CSV is an import
mechanism, not a market data provider (Liskov violation to force both).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import pandas as pd


@dataclass(frozen=True, slots=True)
class RawInstrumentData:
    """Normalized instrument data from any provider."""

    ticker: str | None
    isin: str | None
    name: str
    instrument_type: str  # fund | bond | equity
    asset_class: str
    geography: str
    currency: str
    source: str  # yahoo_finance | csv | manual
    raw_attributes: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class InstrumentDataProvider(Protocol):
    """Protocol for market data providers (Yahoo, Bloomberg, Lipper)."""

    def fetch_instrument(self, ticker: str) -> RawInstrumentData | None: ...

    def fetch_batch(self, tickers: list[str]) -> list[RawInstrumentData]: ...

    def fetch_batch_history(
        self, tickers: list[str], period: str = "3y",
    ) -> dict[str, pd.DataFrame]: ...


def safe_get(
    info: dict,
    key: str,
    default: Any = None,
    coerce: type | None = None,
) -> Any:
    """Safely extract a value from a dict, rejecting NaN/Infinity.

    Used by providers to normalize raw API responses.
    """
    val = info.get(key)
    if val is None:
        return default
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return default
    if coerce is not None:
        try:
            return coerce(val)
        except (ValueError, TypeError):
            return default
    return val

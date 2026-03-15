"""Derived computed fields from raw FRED series.

Pure computation, no I/O. Imports only models.py (leaf).
"""
from __future__ import annotations


def _compute_yield_curve_2s10s(
    risk_free_10y: float | None,
    risk_free_2y: float | None,
) -> float | None:
    """Compute 10Y minus 2Y Treasury spread."""
    if risk_free_10y is None or risk_free_2y is None:
        return None
    return round(risk_free_10y - risk_free_2y, 4)


def _compute_cpi_yoy(
    current_cpi: float | None,
    prior_cpi: float | None,
) -> float | None:
    """Compute CPI year-over-year percentage change."""
    if current_cpi is None or prior_cpi in (None, 0):
        return None
    assert prior_cpi is not None
    return round(((current_cpi / prior_cpi) - 1.0) * 100.0, 4)


def _compute_gdp_growth(
    current_gdp: float | None,
    prior_gdp: float | None,
) -> float | None:
    """Compute annualized quarter-over-quarter GDP growth."""
    if current_gdp is None or prior_gdp in (None, 0):
        return None
    assert prior_gdp is not None
    return round((((current_gdp / prior_gdp) ** 4) - 1.0) * 100.0, 4)

"""Pure derivation functions for the 6 Kelly-Pruitt-Su equity characteristics.

All functions are stateless and testable without DB.
"""

from __future__ import annotations

import math
from datetime import date

import pandas as pd


def derive_size(market_cap_eom: float | None) -> float | None:
    if market_cap_eom is None or market_cap_eom <= 0:
        return None
    return float(math.log(market_cap_eom))


def derive_book_to_market(
    total_equity: float | None, market_cap_eom: float | None
) -> float | None:
    if total_equity is None or market_cap_eom is None or market_cap_eom <= 0:
        return None
    return float(total_equity / market_cap_eom)


def derive_momentum_12_1(nav_series: pd.Series, as_of: date) -> float | None:
    """Compute 12-1 momentum: cumulative return from t-12 to t-1 (skip most recent month)."""
    if nav_series.empty:
        return None
    window = nav_series.loc[:as_of].iloc[-13:-1]
    if len(window) < 11:
        return None
    start_val = window.iloc[0]
    end_val = window.iloc[-1]
    if start_val <= 0:
        return None
    return float(end_val / start_val - 1)


def derive_quality_roa(
    net_income_ttm: float | None, total_assets: float | None
) -> float | None:
    if net_income_ttm is None or total_assets is None or total_assets <= 0:
        return None
    return float(net_income_ttm / total_assets)


def derive_investment_growth(
    total_assets_now: float | None, total_assets_yoy: float | None
) -> float | None:
    if total_assets_now is None or total_assets_yoy is None or total_assets_yoy <= 0:
        return None
    return float(total_assets_now / total_assets_yoy - 1)


def derive_profitability_gross(
    gross_profit: float | None,
    revenue: float | None,
    cost_of_revenue: float | None,
) -> float | None:
    if revenue is None or revenue <= 0:
        return None
    if gross_profit is not None:
        return float(gross_profit / revenue)
    if cost_of_revenue is not None:
        return float((revenue - cost_of_revenue) / revenue)
    return None

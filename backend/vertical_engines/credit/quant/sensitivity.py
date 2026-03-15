"""Credit-specific sensitivity analysis (2D + 3D grids).

Uses itertools.product for grid iteration with credit-specific axes:
default_rate_pct x recovery_rate_pct x rate_shock_bps.

Sync service — pure computation, no I/O.

Imports only models.py (leaf).
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

# Default grid axes
DEFAULT_RATES_GRID = [1.0, 3.0, 5.0, 8.0]
RECOVERY_RATES_GRID = [80.0, 65.0, 50.0, 35.0]
RATE_SHOCKS_BPS = [0, 100, 200]


def build_sensitivity_2d(
    base_return_pct: float | None,
    proxy_flags: list[str],
    *,
    default_rates: list[float] | None = None,
    recovery_rates: list[float] | None = None,
) -> list[dict[str, Any]]:
    """Build 2D sensitivity grid: default_rate x recovery_rate.

    Args:
        base_return_pct: Base return percentage. None -> empty grid.
        proxy_flags: Proxy flag list (passed for interface compat, not used).
        default_rates: Override default rate grid axis.
        recovery_rates: Override recovery rate grid axis.
    """
    if base_return_pct is None:
        return []

    dr_grid = default_rates or DEFAULT_RATES_GRID
    rr_grid = recovery_rates or RECOVERY_RATES_GRID

    grid: list[dict[str, Any]] = []
    for dr in dr_grid:
        for rr in rr_grid:
            loss_impact = dr * (1.0 - rr / 100.0)
            net = round(base_return_pct - loss_impact, 4)
            grid.append({
                "default_rate_pct": dr,
                "recovery_rate_pct": rr,
                "loss_impact_pct": round(loss_impact, 4),
                "net_return_pct": net,
            })
    return grid


def build_sensitivity_3d_summary(
    base_return_pct: float | None,
    sensitivity_2d: list[dict[str, Any]],
    *,
    rate_shocks_bps: list[int] | None = None,
) -> dict[str, Any]:
    """Build 3D summary: default x recovery x rate shocks.

    Args:
        base_return_pct: Base return percentage.
        sensitivity_2d: Output from build_sensitivity_2d().
        rate_shocks_bps: Override rate shock axis (basis points).
    """
    if base_return_pct is None or not sensitivity_2d:
        return {}

    shocks = rate_shocks_bps or RATE_SHOCKS_BPS

    all_cells: list[dict[str, Any]] = []
    for shock in shocks:
        shock_pct = shock / 100.0
        for cell in sensitivity_2d:
            shocked_return = round(cell["net_return_pct"] - shock_pct, 4)
            all_cells.append({
                "rate_shock_bps": shock,
                "default_rate_pct": cell["default_rate_pct"],
                "recovery_rate_pct": cell["recovery_rate_pct"],
                "shocked_net_return_pct": shocked_return,
            })

    all_cells.sort(key=lambda c: c["shocked_net_return_pct"])
    top_fragile = all_cells[:5]

    # Break-even: linear scan for first zero-crossing
    break_even: dict[str, Any] = {}
    for cell in all_cells:
        if cell["shocked_net_return_pct"] <= 0.0:
            break_even = {
                "rate_shock_bps": cell["rate_shock_bps"],
                "default_rate_pct": cell["default_rate_pct"],
                "recovery_rate_pct": cell["recovery_rate_pct"],
                "note": "First combination where net return <= 0%",
            }
            break

    # Dominant driver: range-of-means comparison (shock=0 subset)
    shock0 = [c for c in all_cells if c["rate_shock_bps"] == 0]
    dominant = "unknown"
    if shock0:
        dr_groups: dict[float, list[float]] = {}
        rr_groups: dict[float, list[float]] = {}
        for c in shock0:
            dr_groups.setdefault(c["default_rate_pct"], []).append(c["shocked_net_return_pct"])
            rr_groups.setdefault(c["recovery_rate_pct"], []).append(c["shocked_net_return_pct"])
        dr_means = [sum(v) / len(v) for v in dr_groups.values()]
        rr_means = [sum(v) / len(v) for v in rr_groups.values()]
        dr_range = max(dr_means) - min(dr_means) if dr_means else 0
        rr_range = max(rr_means) - min(rr_means) if rr_means else 0
        if dr_range > rr_range * 1.5:
            dominant = "default_rate"
        elif rr_range > dr_range * 1.5:
            dominant = "recovery_rate"
        else:
            dominant = "balanced"

    return {
        "top_fragile_combinations": top_fragile,
        "break_even_thresholds": break_even,
        "dominant_driver": dominant,
        "rate_shocks_bps": shocks,
        "note": "3D summary: default_rate x recovery_rate x rate_shock",
    }

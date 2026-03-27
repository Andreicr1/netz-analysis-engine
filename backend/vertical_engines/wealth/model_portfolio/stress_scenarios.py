"""Stress scenario definitions for model portfolio testing.

Each scenario defines a historical crisis window. The track_record module
fetches the full returns matrix once and slices in memory per scenario
to avoid redundant DB round-trips.

Parametric stress testing (BL-10): preset shock vectors applied to
block-level weights for instant NAV impact and stressed CVaR estimation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import structlog

logger = structlog.get_logger()


@dataclass(frozen=True, slots=True)
class StressScenario:
    """Definition of a historical stress scenario."""

    name: str
    start_date: date
    end_date: date
    description: str


SCENARIOS: list[StressScenario] = [
    StressScenario(
        name="2008_gfc",
        start_date=date(2007, 10, 1),
        end_date=date(2009, 3, 31),
        description="Global Financial Crisis — subprime mortgage collapse, Lehman failure",
    ),
    StressScenario(
        name="2020_covid",
        start_date=date(2020, 2, 15),
        end_date=date(2020, 4, 30),
        description="COVID-19 pandemic — rapid global selloff and recovery",
    ),
    StressScenario(
        name="2022_rate_hike",
        start_date=date(2022, 1, 1),
        end_date=date(2022, 12, 31),
        description="Fed rate hike cycle — bond rout, growth-to-value rotation",
    ),
]


# ── Parametric stress testing (BL-10) ──────────────────────────────────


@dataclass(frozen=True, slots=True)
class StressScenarioResult:
    """Result of a parametric stress scenario."""

    scenario_name: str
    nav_impact_pct: float  # ΔP/P = Σ(w_block × shock_block)
    cvar_stressed: float | None  # CVaR re-computed with stressed returns
    block_impacts: dict[str, float]  # {block_id: impact_pct}
    worst_block: str | None
    best_block: str | None


# Preset shock vectors keyed by block_id.
# Values are total return shocks (e.g., -0.38 = -38%).
# Only blocks present in the portfolio matter — missing blocks ignored.
PRESET_SCENARIOS: dict[str, dict[str, float]] = {
    "gfc_2008": {
        "na_equity_large": -0.38,
        "na_equity_small": -0.45,
        "intl_equity_dm": -0.40,
        "intl_equity_em": -0.50,
        "fi_treasury": 0.06,
        "fi_credit_ig": -0.05,
        "fi_credit_hy": -0.26,
        "alt_gold": 0.05,
        "alt_reits": -0.38,
    },
    "covid_2020": {
        "na_equity_large": -0.34,
        "na_equity_small": -0.40,
        "intl_equity_dm": -0.30,
        "intl_equity_em": -0.32,
        "fi_treasury": 0.08,
        "fi_credit_ig": -0.06,
        "fi_credit_hy": -0.12,
        "alt_gold": 0.03,
        "alt_reits": -0.25,
    },
    "taper_2013": {
        "na_equity_large": -0.06,
        "na_equity_small": -0.08,
        "intl_equity_dm": -0.10,
        "intl_equity_em": -0.15,
        "fi_treasury": -0.05,
        "fi_credit_ig": -0.03,
        "fi_credit_hy": -0.04,
        "alt_gold": -0.28,
        "alt_reits": -0.04,
    },
    "rate_shock_200bps": {
        "na_equity_large": -0.10,
        "na_equity_small": -0.12,
        "intl_equity_dm": -0.08,
        "intl_equity_em": -0.10,
        "fi_treasury": -0.12,
        "fi_credit_ig": -0.08,
        "fi_credit_hy": -0.06,
        "alt_gold": 0.02,
        "alt_reits": -0.15,
    },
}


def run_stress_scenario(
    weights_by_block: dict[str, float],
    shocks: dict[str, float],
    historical_returns: np.ndarray | None,
    scenario_name: str,
) -> StressScenarioResult:
    """Run a parametric stress scenario against portfolio block weights.

    Parameters
    ----------
    weights_by_block : dict[str, float]
        {block_id: weight} — current portfolio allocation.
    shocks : dict[str, float]
        {block_id: shock_return} — negative = loss.
    historical_returns : np.ndarray | None
        (T,) portfolio historical daily returns for stressed CVaR.
        If None, CVaR is omitted.
    scenario_name : str
        Label for the scenario.

    Returns
    -------
    StressScenarioResult

    """
    block_impacts: dict[str, float] = {}
    nav_impact = 0.0

    for block_id, weight in weights_by_block.items():
        shock = shocks.get(block_id, 0.0)  # blocks without shock → 0 impact
        impact = weight * shock
        block_impacts[block_id] = round(impact, 6)
        nav_impact += impact

    # Identify worst and best blocks
    worst_block = None
    best_block = None
    if block_impacts:
        worst_block = min(block_impacts, key=block_impacts.get)  # type: ignore[arg-type]
        best_block = max(block_impacts, key=block_impacts.get)  # type: ignore[arg-type]

    # Stressed CVaR: shift historical returns by nav_impact and recompute
    cvar_stressed = None
    if historical_returns is not None and len(historical_returns) >= 30:
        from quant_engine.cvar_service import compute_cvar_from_returns

        # Apply shock as a one-time shift to the return distribution
        shifted = historical_returns + nav_impact / len(historical_returns)
        cvar_stressed, _ = compute_cvar_from_returns(shifted, confidence=0.95)
        cvar_stressed = round(cvar_stressed, 6)

    return StressScenarioResult(
        scenario_name=scenario_name,
        nav_impact_pct=round(nav_impact, 6),
        cvar_stressed=cvar_stressed,
        block_impacts=block_impacts,
        worst_block=worst_block,
        best_block=best_block,
    )

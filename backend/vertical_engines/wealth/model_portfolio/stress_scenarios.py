"""Stress scenario definitions for model portfolio testing.

Each scenario defines a historical crisis window. The track_record module
fetches the full returns matrix once and slices in memory per scenario
to avoid redundant DB round-trips.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
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

"""Cash/MMF analytics -- yield spread, NAV stability, liquidity, maturity.

Sync-pure module: zero I/O, zero imports from app.* or vertical_engines.*.
Config is injected as parameter -- never reads YAML, never uses @lru_cache.

All metrics are derived from SEC N-MFP filings (sec_money_market_funds,
sec_mmf_metrics) and FRED DFF (macro_data).  The worker pre-fetches data
and passes it to these pure functions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CashAnalyticsResult:
    """Result of cash/MMF fund analytics."""

    seven_day_net_yield: float | None
    fed_funds_rate: float | None
    nav_per_share: float | None
    pct_weekly_liquid: float | None
    weighted_avg_maturity: int | None

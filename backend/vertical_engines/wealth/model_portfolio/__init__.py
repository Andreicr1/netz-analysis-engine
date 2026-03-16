"""Model Portfolio — construction, track-record, and stress testing.

Provides portfolio construction from universe assets, backtesting via
quant_engine walk-forward CV, live NAV computation, and stress scenario replay.
"""

from vertical_engines.wealth.model_portfolio.models import (
    BacktestResult,
    LiveNAV,
    PortfolioComposition,
    StressResult,
)
from vertical_engines.wealth.model_portfolio.portfolio_builder import construct
from vertical_engines.wealth.model_portfolio.stress_scenarios import SCENARIOS
from vertical_engines.wealth.model_portfolio.track_record import (
    compute_backtest,
    compute_live_nav,
    compute_stress,
)

__all__ = [
    "BacktestResult",
    "LiveNAV",
    "PortfolioComposition",
    "SCENARIOS",
    "StressResult",
    "compute_backtest",
    "compute_live_nav",
    "compute_stress",
    "construct",
]

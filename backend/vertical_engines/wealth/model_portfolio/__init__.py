"""Model Portfolio — construction, track-record, stress testing, and advisor.

Provides portfolio construction from universe assets, backtesting via
quant_engine walk-forward CV, live NAV computation, stress scenario replay,
and construction advisor (gap analysis + candidate screening + CVaR projection).
"""

from vertical_engines.wealth.model_portfolio.block_mapping import (
    blocks_for_strategy_label,
    strategy_labels_for_block,
)
from vertical_engines.wealth.model_portfolio.construction_advisor import (
    build_advice,
)
from vertical_engines.wealth.model_portfolio.models import (
    AlternativeProfile,
    BacktestResult,
    BlockGap,
    BlockInfo,
    CandidateFund,
    ConstructionAdvice,
    CoverageAnalysis,
    FundCandidate,
    LiveNAV,
    MinimumViableSet,
    OptimizationMeta,
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
    "AlternativeProfile",
    "BlockGap",
    "BlockInfo",
    "CandidateFund",
    "ConstructionAdvice",
    "CoverageAnalysis",
    "FundCandidate",
    "MinimumViableSet",
    "SCENARIOS",
    "BacktestResult",
    "LiveNAV",
    "OptimizationMeta",
    "PortfolioComposition",
    "StressResult",
    "blocks_for_strategy_label",
    "build_advice",
    "compute_backtest",
    "compute_live_nav",
    "compute_stress",
    "construct",
    "strategy_labels_for_block",
]

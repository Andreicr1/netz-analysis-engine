"""IC Quant Engine — deterministic quantitative profile for deal analysis.

Public API:
    compute_quant_profile()       — compute full quant profile (orchestrator)
    QuantProfile                  — result dataclass with manual to_dict()
    CVStrategy                    — cross-validation strategy enum
    BacktestInput                 — backtest input dataclass
    CreditBacktestResult          — backtest result dataclass
    backtest_pd_model()           — run cross-validated PD/LGD backtest
    build_deterministic_scenarios() — Base/Downside/Severe scenarios
    build_sensitivity_2d()        — 2D default_rate x recovery_rate grid
    build_sensitivity_3d_summary() — 3D summary with rate shocks

Error contract: raises-on-failure (pure computation — math errors should propagate).
"""
from vertical_engines.credit.quant.backtest import backtest_pd_model
from vertical_engines.credit.quant.models import (
    BacktestInput,
    CreditBacktestResult,
    CVStrategy,
    QuantProfile,
)
from vertical_engines.credit.quant.scenarios import build_deterministic_scenarios
from vertical_engines.credit.quant.sensitivity import (
    build_sensitivity_2d,
    build_sensitivity_3d_summary,
)
from vertical_engines.credit.quant.service import compute_quant_profile

__all__ = [
    "BacktestInput",
    "CVStrategy",
    "CreditBacktestResult",
    "QuantProfile",
    "backtest_pd_model",
    "build_deterministic_scenarios",
    "build_sensitivity_2d",
    "build_sensitivity_3d_summary",
    "compute_quant_profile",
]

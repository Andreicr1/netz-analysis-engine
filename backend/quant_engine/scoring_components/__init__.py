"""Scoring-component building blocks composed by `quant_engine.scoring_service`.

Each module here exposes a pure function producing one component signal (or a
small bundle of related signals). No DB access, no async — stateless math.
"""

from quant_engine.scoring_components.robust_sharpe import (
    RobustSharpeResult,
    robust_sharpe,
)

__all__ = ["RobustSharpeResult", "robust_sharpe"]

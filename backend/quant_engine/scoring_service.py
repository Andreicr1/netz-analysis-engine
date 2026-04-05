"""Fund scoring service.

Scores funds using externalized weights. Each fund gets a composite
manager_score (0-100) based on risk-adjusted metrics.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "scoring").
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

import structlog

logger = structlog.get_logger()


class RiskMetrics(Protocol):
    """Protocol for risk metrics — satisfied by FundRiskMetrics ORM model."""

    return_1y: Decimal | float | None
    sharpe_1y: Decimal | float | None
    max_drawdown_1y: Decimal | float | None
    information_ratio_1y: Decimal | float | None


# Hardcoded fallback — used only if config parameter is not provided.
# fee_efficiency replaces Lipper rating (provider never contracted).
# insider_sentiment is opt-in (add weight > 0 in config to activate).
_DEFAULT_SCORING_WEIGHTS: dict[str, float] = {
    "return_consistency": 0.20,
    "risk_adjusted_return": 0.25,
    "drawdown_control": 0.20,
    "information_ratio": 0.15,
    "flows_momentum": 0.10,
    "fee_efficiency": 0.10,
}


def resolve_scoring_weights(config: dict[str, Any] | None = None) -> dict[str, float]:
    """Extract scoring weights from config dict.

    Falls back to hardcoded defaults if config is None or malformed.
    """
    if config is None:
        return _DEFAULT_SCORING_WEIGHTS

    try:
        weights = config.get("scoring_weights", config)
        if isinstance(weights, dict) and weights:
            return {k: float(v) for k, v in weights.items()}
        return _DEFAULT_SCORING_WEIGHTS
    except (TypeError, ValueError) as e:
        logger.error("Malformed scoring config, using defaults", error=str(e))
        return _DEFAULT_SCORING_WEIGHTS


def _normalize(value: float | None, min_val: float, max_val: float) -> float:
    """Normalize a value to 0-100 scale."""
    if value is None:
        return 50.0
    if max_val == min_val:
        return 50.0
    return max(0.0, min(100.0, (value - min_val) / (max_val - min_val) * 100))


def compute_fund_score(
    metrics: RiskMetrics,
    flows_momentum_score: float = 50.0,
    config: dict[str, Any] | None = None,
    expense_ratio_pct: float | None = None,
    insider_sentiment_score: float | None = None,
) -> tuple[float, dict[str, float]]:
    """Compute composite score from risk metrics. Returns (score, components).

    Args:
        config: Scoring config dict from ConfigService.get("liquid_funds", "scoring").
               Falls back to hardcoded defaults if None.
        expense_ratio_pct: XBRL expense ratio (%). Used for fee_efficiency
               component (default weight 0.10). Falls back to 50.0 (neutral)
               when None — no penalty for missing data.
        insider_sentiment_score: Insider buy/sell sentiment (0-100). Opt-in:
               only used when config includes "insider_sentiment" weight > 0.

    """
    components: dict[str, float] = {}

    ret_1y = float(metrics.return_1y) if metrics.return_1y else None
    components["return_consistency"] = _normalize(ret_1y, -0.20, 0.40)

    sharpe = float(metrics.sharpe_1y) if metrics.sharpe_1y else None
    components["risk_adjusted_return"] = _normalize(sharpe, -1.0, 3.0)

    dd = float(metrics.max_drawdown_1y) if metrics.max_drawdown_1y else None
    components["drawdown_control"] = _normalize(dd, -0.50, 0.0)

    ir = float(metrics.information_ratio_1y) if metrics.information_ratio_1y else None
    components["information_ratio"] = _normalize(ir, -1.0, 2.0)

    components["flows_momentum"] = flows_momentum_score

    # Fee efficiency — default component (replaces Lipper rating).
    # 0% ER → 100 (best), 2% ER → 0 (worst). Neutral 50.0 when no data.
    if expense_ratio_pct is not None:
        # expense_ratio_pct is a pure decimal fraction (0.015 = 1.5%)
        er_human_pct = float(expense_ratio_pct) * 100.0
        components["fee_efficiency"] = max(0.0, 100.0 - er_human_pct * 50.0)
    else:
        components["fee_efficiency"] = 50.0

    weights = resolve_scoring_weights(config)

    # Opt-in insider sentiment (activated when config includes "insider_sentiment" weight > 0)
    if insider_sentiment_score is not None and weights.get("insider_sentiment", 0) > 0:
        components["insider_sentiment"] = insider_sentiment_score

    score = sum(
        components.get(k, 50.0) * w
        for k, w in weights.items()
    )

    return round(score, 2), {k: round(v, 2) for k, v in components.items()}

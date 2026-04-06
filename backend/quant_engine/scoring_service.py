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
# flows_momentum reduced from 10% to 5%: AUM-minus-NAV proxy is noisy
# (dividends, splits, merges distort flow signal). Weight redistributed
# to risk_adjusted_return (most analytically robust component).
_DEFAULT_SCORING_WEIGHTS: dict[str, float] = {
    "return_consistency": 0.20,
    "risk_adjusted_return": 0.30,
    "drawdown_control": 0.20,
    "information_ratio": 0.15,
    "flows_momentum": 0.05,
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


def _normalize(
    value: float | None,
    min_val: float,
    max_val: float,
    peer_median: float | None = None,
) -> float:
    """Normalize a value to 0-100 scale.

    When value is None (missing data):
      - If peer_median is provided, uses (peer_median - 5) to penalize
        opaque/short-history funds vs. transparent peers with mediocre scores.
      - If no peer_median, falls back to 45.0 (below midpoint, slight penalty).
    """
    if value is None:
        if peer_median is not None:
            return max(0.0, min(100.0, peer_median - 5.0))
        return 45.0
    if max_val == min_val:
        return 50.0
    return max(0.0, min(100.0, (value - min_val) / (max_val - min_val) * 100))


def compute_fund_score(
    metrics: RiskMetrics,
    flows_momentum_score: float = 50.0,
    config: dict[str, Any] | None = None,
    expense_ratio_pct: float | None = None,
    insider_sentiment_score: float | None = None,
    peer_medians: dict[str, float] | None = None,
) -> tuple[float, dict[str, float]]:
    """Compute composite score from risk metrics. Returns (score, components).

    Args:
        config: Scoring config dict from ConfigService.get("liquid_funds", "scoring").
               Falls back to hardcoded defaults if None.
        expense_ratio_pct: XBRL expense ratio (%). Used for fee_efficiency
               component (default weight 0.10). Missing data gets peer_median - 5
               penalty instead of blind neutral.
        insider_sentiment_score: Insider buy/sell sentiment (0-100). Opt-in:
               only used when config includes "insider_sentiment" weight > 0.
        peer_medians: Dict of component_name → median score from strategy peers.
               Used as fallback for missing data (with -5pt penalty) instead of
               blind neutral 50. Penalizes opaque/short-history funds.

    """
    pm = peer_medians or {}
    components: dict[str, float] = {}

    ret_1y = float(metrics.return_1y) if metrics.return_1y else None
    components["return_consistency"] = _normalize(ret_1y, -0.20, 0.40, pm.get("return_consistency"))

    sharpe = float(metrics.sharpe_1y) if metrics.sharpe_1y else None
    components["risk_adjusted_return"] = _normalize(sharpe, -1.0, 3.0, pm.get("risk_adjusted_return"))

    dd = float(metrics.max_drawdown_1y) if metrics.max_drawdown_1y else None
    components["drawdown_control"] = _normalize(dd, -0.50, 0.0, pm.get("drawdown_control"))

    ir = float(metrics.information_ratio_1y) if metrics.information_ratio_1y else None
    components["information_ratio"] = _normalize(ir, -1.0, 2.0, pm.get("information_ratio"))

    components["flows_momentum"] = flows_momentum_score

    # Fee efficiency — default component (replaces Lipper rating).
    # 0% ER → 100 (best), 2% ER → 0 (worst).
    # Missing ER → peer_median - 5 (penalizes opacity).
    if expense_ratio_pct is not None:
        # expense_ratio_pct is a pure decimal fraction (0.015 = 1.5%)
        er_human_pct = float(expense_ratio_pct) * 100.0
        components["fee_efficiency"] = max(0.0, 100.0 - er_human_pct * 50.0)
    else:
        fee_pm = pm.get("fee_efficiency")
        components["fee_efficiency"] = max(0.0, fee_pm - 5.0) if fee_pm is not None else 45.0

    weights = resolve_scoring_weights(config)

    # Opt-in insider sentiment (activated when config includes "insider_sentiment" weight > 0)
    if insider_sentiment_score is not None and weights.get("insider_sentiment", 0) > 0:
        components["insider_sentiment"] = insider_sentiment_score

    score = sum(
        components.get(k, 50.0) * w
        for k, w in weights.items()
    )

    return round(score, 2), {k: round(v, 2) for k, v in components.items()}

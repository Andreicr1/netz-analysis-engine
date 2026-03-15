"""Fund scoring service.

Scores funds using externalized weights. Each fund gets a composite
manager_score (0-100) based on risk-adjusted metrics.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "scoring").

Note: imports FundRiskMetrics from app.domains.wealth — wealth-vertical-specific dependency.
"""

import structlog

from app.domains.wealth.models.risk import FundRiskMetrics

logger = structlog.get_logger()


# Hardcoded fallback — used only if config parameter is not provided.
_DEFAULT_SCORING_WEIGHTS: dict[str, float] = {
    "return_consistency": 0.20,
    "risk_adjusted_return": 0.25,
    "drawdown_control": 0.20,
    "information_ratio": 0.15,
    "flows_momentum": 0.10,
    "lipper_rating": 0.10,
}


def resolve_scoring_weights(config: dict | None = None) -> dict[str, float]:
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
    metrics: FundRiskMetrics,
    lipper_score: float = 50.0,
    flows_momentum_score: float = 50.0,
    config: dict | None = None,
) -> tuple[float, dict[str, float]]:
    """Compute composite score from risk metrics. Returns (score, components).

    Args:
        config: Scoring config dict from ConfigService.get("liquid_funds", "scoring").
               Falls back to hardcoded defaults if None.
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
    components["lipper_rating"] = lipper_score

    weights = resolve_scoring_weights(config)
    score = sum(
        components.get(k, 50.0) * w
        for k, w in weights.items()
    )

    return round(score, 2), {k: round(v, 2) for k, v in components.items()}

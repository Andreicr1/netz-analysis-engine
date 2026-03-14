"""Fund scoring service.

Scores funds using externalized weights from calibration/config/scoring.yaml.
Each fund gets a composite manager_score (0-100) based on risk-adjusted metrics.
"""

from functools import lru_cache

import structlog
import yaml

from app.core.config.settings import get_calibration_path
from app.domains.wealth.models.risk import FundRiskMetrics

logger = structlog.get_logger()


@lru_cache(maxsize=1)
def get_scoring_weights() -> dict[str, float]:
    """Load scoring weights from YAML config on first access, then cache."""
    try:
        config_path = get_calibration_path() / "scoring.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        return config["scoring_weights"]
    except FileNotFoundError:
        logger.warning("scoring.yaml not found, using defaults")
        return {
            "return_consistency": 0.20,
            "risk_adjusted_return": 0.25,
            "drawdown_control": 0.20,
            "information_ratio": 0.15,
            "flows_momentum": 0.10,
            "lipper_rating": 0.10,
        }
    except (KeyError, TypeError) as e:
        logger.error("scoring.yaml malformed", error=str(e))
        return {
            "return_consistency": 0.20,
            "risk_adjusted_return": 0.25,
            "drawdown_control": 0.20,
            "information_ratio": 0.15,
            "flows_momentum": 0.10,
            "lipper_rating": 0.10,
        }


def _normalize(value: float | None, min_val: float, max_val: float) -> float:
    """Normalize a value to 0-100 scale."""
    if value is None:
        return 50.0  # neutral score for missing data
    if max_val == min_val:
        return 50.0
    return max(0.0, min(100.0, (value - min_val) / (max_val - min_val) * 100))


def compute_fund_score(
    metrics: FundRiskMetrics,
    lipper_score: float = 50.0,
    flows_momentum_score: float = 50.0,
) -> tuple[float, dict[str, float]]:
    """Compute composite score from risk metrics. Returns (score, components).

    Pure function — no I/O, no async calls inside.

    Args:
        metrics: Fund risk metrics from fund_risk_metrics table.
        lipper_score: Pre-fetched Lipper score (0-100). Defaults to 50.0
            (neutral) when FEATURE_LIPPER_ENABLED=false or no Lipper data.
            Caller fetches via lipper_service.get_fund_lipper_score().
        flows_momentum_score: Pre-fetched momentum score (0-100). Defaults to 50.0
            (neutral). When FEATURE_MOMENTUM_SIGNALS=true, caller computes via
            talib_momentum_service.compute_momentum_signals_talib() from NAV data.
            Caller is responsible for fetching — keeps this function pure.
    """
    components: dict[str, float] = {}

    # Return consistency: based on 1Y return relative to typical range
    ret_1y = float(metrics.return_1y) if metrics.return_1y else None
    components["return_consistency"] = _normalize(ret_1y, -0.20, 0.40)

    # Risk-adjusted return: Sharpe ratio
    sharpe = float(metrics.sharpe_1y) if metrics.sharpe_1y else None
    components["risk_adjusted_return"] = _normalize(sharpe, -1.0, 3.0)

    # Drawdown control: lower (less negative) drawdown is better
    dd = float(metrics.max_drawdown_1y) if metrics.max_drawdown_1y else None
    components["drawdown_control"] = _normalize(dd, -0.50, 0.0)

    # Information ratio
    ir = float(metrics.information_ratio_1y) if metrics.information_ratio_1y else None
    components["information_ratio"] = _normalize(ir, -1.0, 2.0)

    # Flows momentum: pre-fetched by caller (TA-Lib RSI/BBANDS when flag enabled)
    components["flows_momentum"] = flows_momentum_score

    # Lipper rating: pre-fetched score from lipper_service
    components["lipper_rating"] = lipper_score

    # Weighted composite
    score = sum(
        components.get(k, 50.0) * w
        for k, w in get_scoring_weights().items()
    )

    return round(score, 2), {k: round(v, 2) for k, v in components.items()}

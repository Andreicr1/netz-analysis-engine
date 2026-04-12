"""Fund scoring service.

Scores funds using externalized weights. Each fund gets a composite
manager_score (0-100) based on risk-adjusted metrics.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "scoring").
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Protocol

import structlog

from quant_engine.expense_ratio_validator import to_decimal_fraction

logger = structlog.get_logger()


class RiskMetrics(Protocol):
    """Protocol for risk metrics — satisfied by FundRiskMetrics ORM model."""

    return_1y: Decimal | float | None
    sharpe_1y: Decimal | float | None
    max_drawdown_1y: Decimal | float | None
    information_ratio_1y: Decimal | float | None


class FIMetrics(Protocol):
    """Protocol for fixed income metrics — satisfied by FundRiskMetrics ORM or adapter."""

    empirical_duration: Decimal | float | None
    credit_beta: Decimal | float | None
    yield_proxy_12m: Decimal | float | None
    duration_adj_drawdown_1y: Decimal | float | None


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

# FI scoring weights — calibrated for fixed income fund evaluation.
# yield_consistency: carry stability (income return).
# duration_management: adherence to mandate duration target.
# spread_capture: skill in credit sector rotation/selection.
# duration_adjusted_drawdown: drawdown per unit of duration risk.
# fee_efficiency: same as equity (transparency universal).
_DEFAULT_FI_SCORING_WEIGHTS: dict[str, float] = {
    "yield_consistency": 0.20,
    "duration_management": 0.25,
    "spread_capture": 0.20,
    "duration_adjusted_drawdown": 0.25,
    "fee_efficiency": 0.10,
}


def resolve_scoring_weights(
    config: dict[str, Any] | None = None,
    asset_class: str = "equity",
) -> dict[str, float]:
    """Extract scoring weights from config dict.

    Falls back to asset-class-appropriate defaults if config is None or malformed.
    """
    default = _DEFAULT_FI_SCORING_WEIGHTS if asset_class == "fixed_income" else _DEFAULT_SCORING_WEIGHTS
    if config is None:
        return default

    try:
        weights = config.get("scoring_weights", config)
        if isinstance(weights, dict) and weights:
            return {k: float(v) for k, v in weights.items()}
        return default
    except (TypeError, ValueError) as e:
        logger.error("Malformed scoring config, using defaults", error=str(e))
        return default


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


def _compute_fee_efficiency(
    expense_ratio_pct: float | None,
    peer_medians: dict[str, float] | None = None,
) -> float:
    """Compute fee efficiency component (shared between equity and FI paths)."""
    pm = peer_medians or {}
    er_fraction = to_decimal_fraction(expense_ratio_pct)
    if er_fraction is not None:
        er_human_pct = er_fraction * 100.0  # decimal -> percent for scoring
        return max(0.0, 100.0 - er_human_pct * 50.0)
    fee_pm = pm.get("fee_efficiency")
    return max(0.0, fee_pm - 5.0) if fee_pm is not None else 45.0


def _compute_fi_score(
    fi: FIMetrics,
    config: dict[str, Any] | None,
    expense_ratio_pct: float | None,
    peer_medians: dict[str, float] | None,
) -> tuple[float, dict[str, float]]:
    """Compute FI-specific composite score. Returns (score, components).

    Five components: yield_consistency, duration_management, spread_capture,
    duration_adjusted_drawdown, fee_efficiency.
    """
    pm = peer_medians or {}
    components: dict[str, float] = {}

    # yield_consistency: trailing 12m income return proxy
    # Range: 0% yield (worst) to 8% yield (best for IG).
    yp = float(fi.yield_proxy_12m) if fi.yield_proxy_12m is not None else None
    components["yield_consistency"] = _normalize(yp, 0.0, 0.08, pm.get("yield_consistency"))

    # duration_management: empirical duration vs target center.
    # Config-driven: duration_center and duration_half_range.
    # Default: core IG (center=5.0, half_range=3.0).
    dur = float(fi.empirical_duration) if fi.empirical_duration is not None else None
    dur_center = 5.0
    dur_half_range = 3.0
    if config:
        dur_center = float(config.get("duration_center", dur_center))
        dur_half_range = float(config.get("duration_half_range", dur_half_range))
    if dur is not None:
        deviation = abs(dur - dur_center) / max(dur_half_range, 0.1)
        components["duration_management"] = max(0.0, min(100.0, (1 - deviation) * 100))
    else:
        components["duration_management"] = pm.get("duration_management", 45.0) - 5.0

    # spread_capture: credit beta as proxy for spread capture skill.
    # Moderate exposure (0.5-1.5) is ideal. Range: -1.0 to 3.0.
    cb = float(fi.credit_beta) if fi.credit_beta is not None else None
    components["spread_capture"] = _normalize(cb, -1.0, 3.0, pm.get("spread_capture"))

    # duration_adjusted_drawdown: drawdown per unit of duration.
    # Range: -5.0 (terrible) to 0.0 (no drawdown). Higher is better.
    dad = float(fi.duration_adj_drawdown_1y) if fi.duration_adj_drawdown_1y is not None else None
    components["duration_adjusted_drawdown"] = _normalize(
        dad, -5.0, 0.0, pm.get("duration_adjusted_drawdown"),
    )

    # fee_efficiency: same logic as equity
    components["fee_efficiency"] = _compute_fee_efficiency(expense_ratio_pct, pm)

    weights = resolve_scoring_weights(config, asset_class="fixed_income")

    score = sum(components.get(k, 50.0) * w for k, w in weights.items())
    return round(score, 2), {k: round(v, 2) for k, v in components.items()}


def compute_fund_score(
    metrics: RiskMetrics,
    flows_momentum_score: float = 50.0,
    config: dict[str, Any] | None = None,
    expense_ratio_pct: float | None = None,
    insider_sentiment_score: float | None = None,
    peer_medians: dict[str, float] | None = None,
    asset_class: str = "equity",
    fi_metrics: FIMetrics | None = None,
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
        asset_class: "equity" (default) or "fixed_income". Determines scoring model.
        fi_metrics: Fixed income metrics. Required when asset_class="fixed_income".
               Falls back to equity scoring if None.

    """
    # Dispatch to FI scoring when asset_class is fixed_income AND fi_metrics provided
    if asset_class == "fixed_income" and fi_metrics is not None:
        return _compute_fi_score(fi_metrics, config, expense_ratio_pct, peer_medians)

    pm = peer_medians or {}
    components: dict[str, float] = {}

    # S4-QW1: use ``is not None`` instead of truthy checks.
    # ``Decimal("0.0")`` and ``float(0.0)`` are both falsy in Python, so the
    # historical ``if metrics.return_1y:`` idiom treated a fund that
    # **legitimately** returned exactly 0 % as "missing data" and assigned
    # the peer-median minus 5 opacity penalty. The fund then fell several
    # ranks below peers for a non-existent data gap. Strict ``is not None``
    # distinguishes "value available and equal to zero" from "value
    # unavailable".
    ret_1y = float(metrics.return_1y) if metrics.return_1y is not None else None
    components["return_consistency"] = _normalize(ret_1y, -0.20, 0.40, pm.get("return_consistency"))

    sharpe = float(metrics.sharpe_1y) if metrics.sharpe_1y is not None else None
    components["risk_adjusted_return"] = _normalize(sharpe, -1.0, 3.0, pm.get("risk_adjusted_return"))

    dd = float(metrics.max_drawdown_1y) if metrics.max_drawdown_1y is not None else None
    components["drawdown_control"] = _normalize(dd, -0.50, 0.0, pm.get("drawdown_control"))

    ir = float(metrics.information_ratio_1y) if metrics.information_ratio_1y is not None else None
    components["information_ratio"] = _normalize(ir, -1.0, 2.0, pm.get("information_ratio"))

    components["flows_momentum"] = flows_momentum_score

    # Fee efficiency — shared with FI path
    components["fee_efficiency"] = _compute_fee_efficiency(expense_ratio_pct, pm)

    weights = resolve_scoring_weights(config)

    # Opt-in insider sentiment (activated when config includes "insider_sentiment" weight > 0)
    if insider_sentiment_score is not None and weights.get("insider_sentiment", 0) > 0:
        components["insider_sentiment"] = insider_sentiment_score

    score = sum(
        components.get(k, 50.0) * w
        for k, w in weights.items()
    )

    return round(score, 2), {k: round(v, 2) for k, v in components.items()}

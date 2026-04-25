"""Fund scoring service.

Scores funds using externalized weights. Each fund gets a composite
manager_score (0-100) based on risk-adjusted metrics.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "scoring").
"""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Protocol

import structlog

from quant_engine.expense_ratio_validator import to_decimal_fraction

logger = structlog.get_logger()


class RiskMetrics(Protocol):
    """Protocol for risk metrics — satisfied by FundRiskMetrics ORM model."""

    return_1y: Decimal | float | None
    sharpe_1y: Decimal | float | None
    sharpe_cf: Decimal | float | None
    max_drawdown_1y: Decimal | float | None
    information_ratio_1y: Decimal | float | None


class FIMetrics(Protocol):
    """Protocol for fixed income metrics — satisfied by FundRiskMetrics ORM or adapter."""

    empirical_duration: Decimal | float | None
    credit_beta: Decimal | float | None
    yield_proxy_12m: Decimal | float | None
    duration_adj_drawdown_1y: Decimal | float | None


class CashMetrics(Protocol):
    """Protocol for cash/MMF metrics — satisfied by FundRiskMetrics ORM or adapter."""

    seven_day_net_yield: Decimal | float | None
    fed_funds_rate_at_calc: Decimal | float | None
    nav_per_share_mmf: Decimal | float | None
    pct_weekly_liquid: Decimal | float | None
    weighted_avg_maturity_days: int | float | None


class AltMetrics(Protocol):
    """Protocol for alternatives metrics — satisfied by FundRiskMetrics ORM or adapter."""

    equity_correlation_252d: Decimal | float | None
    downside_capture_1y: Decimal | float | None
    upside_capture_1y: Decimal | float | None
    crisis_alpha_score: Decimal | float | None
    calmar_ratio_3y: Decimal | float | None
    max_drawdown_3y: Decimal | float | None
    sortino_1y: Decimal | float | None
    inflation_beta: Decimal | float | None
    yield_proxy_12m: Decimal | float | None  # Reused from FI (for REIT income)
    tracking_error_1y: Decimal | float | None  # For gold tracking efficiency


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

# Cash/MMF scoring weights — calibrated for money market fund evaluation.
# yield_vs_risk_free: relative yield advantage over fed funds rate.
# nav_stability: deviation from $1.00 par (break-the-buck risk).
# liquidity_quality: weekly liquid assets % (SEC Rule 2a-7 minimum 30%).
# maturity_discipline: lower WAM = less interest rate risk.
# fee_efficiency: same as equity/FI (critical at cash yields).
_DEFAULT_CASH_SCORING_WEIGHTS: dict[str, float] = {
    "yield_vs_risk_free": 0.30,
    "nav_stability": 0.25,
    "liquidity_quality": 0.20,
    "maturity_discipline": 0.15,
    "fee_efficiency": 0.10,
}

# ── Alternatives scoring weights per profile ──────────────────────────
# All profiles share 5 components (sum = 1.0) but with different weights
# reflecting what matters most for each alternative strategy.

_DEFAULT_ALT_REIT_WEIGHTS: dict[str, float] = {
    "income_generation": 0.25,
    "diversification_value": 0.25,
    "downside_protection": 0.20,
    "inflation_hedge": 0.20,
    "fee_efficiency": 0.10,
}

_DEFAULT_ALT_COMMODITY_WEIGHTS: dict[str, float] = {
    "inflation_hedge": 0.30,
    "diversification_value": 0.25,
    "crisis_alpha": 0.20,
    "drawdown_control": 0.15,
    "fee_efficiency": 0.10,
}

_DEFAULT_ALT_GOLD_WEIGHTS: dict[str, float] = {
    "crisis_alpha": 0.30,
    "diversification_value": 0.30,
    "inflation_hedge": 0.20,
    "tracking_efficiency": 0.10,
    "fee_efficiency": 0.10,
}

_DEFAULT_ALT_HEDGE_WEIGHTS: dict[str, float] = {
    "alpha_generation": 0.30,
    "downside_protection": 0.25,
    "diversification_value": 0.20,
    "crisis_alpha": 0.15,
    "fee_efficiency": 0.10,
}

_DEFAULT_ALT_CTA_WEIGHTS: dict[str, float] = {
    "crisis_alpha": 0.40,
    "diversification_value": 0.25,
    "risk_adjusted_return": 0.25,
    "fee_efficiency": 0.10,
}

_DEFAULT_ALT_GENERIC_WEIGHTS: dict[str, float] = {
    "diversification_value": 0.30,
    "downside_protection": 0.25,
    "risk_adjusted_return": 0.20,
    "crisis_alpha": 0.15,
    "fee_efficiency": 0.10,
}

# Profile name → default weight dict
_ALT_PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "reit": _DEFAULT_ALT_REIT_WEIGHTS,
    "commodity": _DEFAULT_ALT_COMMODITY_WEIGHTS,
    "gold": _DEFAULT_ALT_GOLD_WEIGHTS,
    "hedge": _DEFAULT_ALT_HEDGE_WEIGHTS,
    "cta": _DEFAULT_ALT_CTA_WEIGHTS,
    "generic_alt": _DEFAULT_ALT_GENERIC_WEIGHTS,
}


def _validate_weights(weights: dict[str, float], context: str) -> None:
    """Validate that weights are finite, non-negative, and sum to 1.0 ± 1e-3."""
    for k, w in weights.items():
        if not math.isfinite(w):
            raise ValueError(f"{context}: weight for {k!r} is non-finite ({w})")
        if w < 0:
            raise ValueError(f"{context}: weight for {k!r} is negative ({w})")
    total = sum(weights.values())
    if not math.isclose(total, 1.0, abs_tol=1e-3):
        raise ValueError(
            f"{context}: weights sum to {total:.4f}, expected 1.0 ± 0.001. "
            f"Weights: {weights}"
        )


def resolve_alt_profile_weights(
    profile: str,
    config: dict[str, Any] | None = None,
) -> dict[str, float]:
    """Resolve alternatives scoring weights for a specific profile.

    Falls back to generic_alt if profile is unknown. Config override
    takes precedence when provided.
    """
    if config is not None:
        try:
            weights = config.get("scoring_weights")
            if isinstance(weights, dict) and weights:
                result = {k: float(v) for k, v in weights.items()}
                _validate_weights(result, "resolve_alt_profile_weights")
                return result
        except (TypeError, ValueError):
            pass
    return _ALT_PROFILE_WEIGHTS.get(profile, _DEFAULT_ALT_GENERIC_WEIGHTS)


def resolve_scoring_weights(
    config: dict[str, Any] | None = None,
    asset_class: str = "equity",
) -> dict[str, float]:
    """Extract scoring weights from config dict.

    Falls back to asset-class-appropriate defaults if config is None or malformed.
    For alternatives, use resolve_alt_profile_weights() instead (profile-specific).
    """
    _defaults_by_class = {
        "fixed_income": _DEFAULT_FI_SCORING_WEIGHTS,
        "cash": _DEFAULT_CASH_SCORING_WEIGHTS,
        "alternatives": _DEFAULT_ALT_GENERIC_WEIGHTS,
    }
    default = _defaults_by_class.get(asset_class, _DEFAULT_SCORING_WEIGHTS)
    if config is None:
        return default

    try:
        weights = config.get("scoring_weights")
        if isinstance(weights, dict) and weights:
            result = {k: float(v) for k, v in weights.items()}
            _validate_weights(result, "resolve_scoring_weights")
            return result
        return default
    except (TypeError, ValueError) as e:
        logger.error("Malformed scoring config, using defaults", error=str(e))
        return default


def _clamp_component_score(value: float, name: str) -> float:
    """Clamp external component scores to [0, 100], rejecting non-finite."""
    if not math.isfinite(value):
        raise ValueError(f"{name}_score is non-finite ({value})")
    return max(0.0, min(100.0, float(value)))


def _peaked_score(value: float | None, target: float, half_range: float) -> float:
    """Score = 100 at value=target, decays linearly to 0 at |value - target| >= half_range."""
    if value is None or not math.isfinite(value):
        return 45.0
    distance = abs(value - target)
    return max(0.0, 100.0 * (1.0 - distance / half_range))


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
    if value is None or not math.isfinite(value):
        if peer_median is not None:
            return max(0.0, min(100.0, peer_median - 5.0))
        return 45.0
    if max_val == min_val:
        return 50.0
    return max(0.0, min(100.0, (value - min_val) / (max_val - min_val) * 100))


def _resolve_sharpe_input(
    metrics: RiskMetrics,
    config: dict[str, Any] | None,
) -> float | None:
    """Return the Sharpe value used by ``risk_adjusted_return``.

    Flag OFF (default): reads ``sharpe_1y`` — bit-for-bit identical to pre-G1
    behavior. Flag ON: reads ``sharpe_cf``; falls back to ``sharpe_1y`` with
    a warning when the robust value has not yet been backfilled.
    """
    use_robust = False
    if config is not None:
        try:
            raw = config.get("use_robust_sharpe", False)
            use_robust = bool(raw)
        except (AttributeError, TypeError):
            use_robust = False

    if use_robust:
        sharpe_cf = getattr(metrics, "sharpe_cf", None)
        if sharpe_cf is not None:
            return float(sharpe_cf)
        logger.warning(
            "risk_adjusted_return.sharpe_cf_missing_fallback_to_sharpe_1y",
            flag="use_robust_sharpe",
        )

    return float(metrics.sharpe_1y) if metrics.sharpe_1y is not None else None


def _compute_fee_efficiency(
    expense_ratio_pct: float | None,
    peer_medians: dict[str, float] | None = None,
) -> float:
    """Compute fee efficiency component (shared between equity and FI paths)."""
    pm = peer_medians or {}
    er_fraction = to_decimal_fraction(expense_ratio_pct)
    if er_fraction is not None and math.isfinite(float(er_fraction)):
        er_human_pct = float(er_fraction) * 100.0  # decimal -> percent for scoring
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
        components["duration_management"] = pm.get("duration_management", 45.0)

    # spread_capture: credit beta as proxy for spread capture skill.
    # Peaked at credit_beta = 1.0; symmetric ±1.0 half-range.
    # Higher and lower betas penalized equally — moderate exposure is the institutional ideal.
    cb = float(fi.credit_beta) if fi.credit_beta is not None else None
    components["spread_capture"] = _peaked_score(cb, target=1.0, half_range=1.0)

    # duration_adjusted_drawdown: drawdown per unit of duration.
    # Range: -5.0 (terrible) to 0.0 (no drawdown). Higher is better.
    dad = float(fi.duration_adj_drawdown_1y) if fi.duration_adj_drawdown_1y is not None else None
    components["duration_adjusted_drawdown"] = _normalize(
        dad, -5.0, 0.0, pm.get("duration_adjusted_drawdown"),
    )

    # fee_efficiency: same logic as equity
    components["fee_efficiency"] = _compute_fee_efficiency(expense_ratio_pct, pm)

    weights = resolve_scoring_weights(config, asset_class="fixed_income")

    missing = set(weights.keys()) - components.keys()
    if missing:
        raise ValueError(
            f"_compute_fi_score: weights reference components not provided: "
            f"{sorted(missing)}. All weighted components must be computed."
        )

    score = sum(components[k] * w for k, w in weights.items())
    return round(score, 2), {k: round(v, 2) for k, v in components.items()}


def _compute_cash_score(
    cash: CashMetrics,
    config: dict[str, Any] | None,
    expense_ratio_pct: float | None,
    peer_medians: dict[str, float] | None,
) -> tuple[float, dict[str, float]]:
    """Compute Cash/MMF-specific composite score. Returns (score, components).

    Five components: yield_vs_risk_free, nav_stability, liquidity_quality,
    maturity_discipline, fee_efficiency.
    """
    pm = peer_medians or {}
    components: dict[str, float] = {}

    # yield_vs_risk_free: absolute spread over policy rate (handles negative rates).
    # 0 pp → 50, 5 pp → 100, -5 pp → 0. Continuous across the zero boundary.
    yld = float(cash.seven_day_net_yield) if cash.seven_day_net_yield is not None else None
    ffr = float(cash.fed_funds_rate_at_calc) if cash.fed_funds_rate_at_calc is not None else None
    if yld is not None and ffr is not None and math.isfinite(ffr):
        spread_pp = (yld - ffr) * 100.0  # percentage points
        components["yield_vs_risk_free"] = _normalize(
            spread_pp, -5.0, 5.0, pm.get("yield_vs_risk_free"),
        )
    else:
        components["yield_vs_risk_free"] = pm.get("yield_vs_risk_free", 45.0)

    # nav_stability: deviation from $1.00 par value
    nav = float(cash.nav_per_share_mmf) if cash.nav_per_share_mmf is not None else None
    if nav is not None:
        deviation = abs(nav - 1.0)
        stability = max(0.0, 1.0 - deviation * 1000)  # 0.001 deviation = 0 score
        components["nav_stability"] = stability * 100
    else:
        components["nav_stability"] = pm.get("nav_stability", 45.0)

    # liquidity_quality: weekly liquid assets %
    wl = float(cash.pct_weekly_liquid) if cash.pct_weekly_liquid is not None else None
    if wl is not None:
        # Range 30% (SEC 2a-7 regulatory min) to 100%
        components["liquidity_quality"] = _normalize(
            wl, 30.0, 100.0, pm.get("liquidity_quality"),
        )
    else:
        components["liquidity_quality"] = pm.get("liquidity_quality", 45.0)

    # maturity_discipline: lower WAM = less interest rate risk = better
    wam = float(cash.weighted_avg_maturity_days) if cash.weighted_avg_maturity_days is not None else None
    if wam is not None:
        # 0 days = 100 (all overnight), 60 days = 0 (regulatory max). Inverted scale.
        wam_score = max(0.0, (1.0 - wam / 60.0)) * 100
        components["maturity_discipline"] = wam_score
    else:
        components["maturity_discipline"] = pm.get("maturity_discipline", 45.0)

    # fee_efficiency: same logic as equity/FI
    components["fee_efficiency"] = _compute_fee_efficiency(expense_ratio_pct, pm)

    weights = resolve_scoring_weights(config, asset_class="cash")

    missing = set(weights.keys()) - components.keys()
    if missing:
        raise ValueError(
            f"_compute_cash_score: weights reference components not provided: "
            f"{sorted(missing)}. All weighted components must be computed."
        )

    score = sum(components[k] * w for k, w in weights.items())
    return round(score, 2), {k: round(v, 2) for k, v in components.items()}


def _compute_alternatives_score(
    alt: AltMetrics,
    profile: str,
    config: dict[str, Any] | None,
    expense_ratio_pct: float | None,
    peer_medians: dict[str, float] | None,
) -> tuple[float, dict[str, float]]:
    """Compute Alternatives composite score. Returns (score, components).

    Profile-specific weights determine which components matter most.
    All components are computed for all alt funds; weights select relevance.
    """
    pm = peer_medians or {}
    components: dict[str, float] = {}

    # diversification_value: 1 - abs(equity_correlation_252d)
    # Empirical p50 div_value = 0.23 (median alt corr = 0.77).
    # Range [0.0, 0.50] so p50 → score ~47, truly uncorrelated funds hit 100.
    eq_corr = float(alt.equity_correlation_252d) if alt.equity_correlation_252d is not None else None
    if eq_corr is not None:
        div_value = 1.0 - abs(eq_corr)
        components["diversification_value"] = _normalize(div_value, 0.0, 0.50, pm.get("diversification_value"))
    else:
        components["diversification_value"] = pm.get("diversification_value", 45.0)

    # downside_protection: 1 - downside_capture_1y
    # Score 100 at capture=0, score 50 at capture=1.0, score 0 at capture >= 2.0.
    dc = float(alt.downside_capture_1y) if alt.downside_capture_1y is not None else None
    if dc is not None:
        protection = 1.0 - dc
        components["downside_protection"] = _normalize(protection, -1.0, 1.0, pm.get("downside_protection"))
    else:
        components["downside_protection"] = pm.get("downside_protection", 45.0)

    # crisis_alpha: excess return vs benchmark during drawdown periods.
    # Empirical p10=-0.034, p50=+0.009, p90=+0.050.
    # Range [-0.06, 0.08] so p50 → score ~49.
    ca = float(alt.crisis_alpha_score) if alt.crisis_alpha_score is not None else None
    components["crisis_alpha"] = _normalize(ca, -0.06, 0.08, pm.get("crisis_alpha"))

    # inflation_hedge: inflation beta (regression of returns vs CPI changes).
    # Empirical p10=-11.03, p50=-5.84, p90=-1.82 (all negative).
    # Range [-12.0, 0.0] so p50 → score ~51.
    ib = float(alt.inflation_beta) if alt.inflation_beta is not None else None
    components["inflation_hedge"] = _normalize(ib, -12.0, 0.0, pm.get("inflation_hedge"))

    # income_generation: yield_proxy_12m (reused from FI for REITs)
    # Range: 0% to 10%.
    yp = float(alt.yield_proxy_12m) if alt.yield_proxy_12m is not None else None
    components["income_generation"] = _normalize(yp, 0.0, 0.10, pm.get("income_generation"))

    # alpha_generation: sortino_1y (not Sharpe -- Sharpe penalizes upside vol).
    # Empirical p10=0.34, p50=2.53, p90=3.48.
    # Range [0.0, 5.0] so p50 → score ~51.
    sortino = float(alt.sortino_1y) if alt.sortino_1y is not None else None
    components["alpha_generation"] = _normalize(sortino, 0.0, 5.0, pm.get("alpha_generation"))

    # risk_adjusted_return: calmar_ratio_3y (return / max drawdown).
    # Empirical p10=0.32, p50=0.75, p90=1.35.
    # Range [0.0, 1.5] so p50 → score 50.
    calmar = float(alt.calmar_ratio_3y) if alt.calmar_ratio_3y is not None else None
    components["risk_adjusted_return"] = _normalize(calmar, 0.0, 1.5, pm.get("risk_adjusted_return"))

    # drawdown_control: based on max_drawdown_3y directly (lower max DD → higher score).
    # Score 100 at max DD = 0%, score 0 at max DD = -50%.
    max_dd = float(alt.max_drawdown_3y) if alt.max_drawdown_3y is not None else None
    if max_dd is not None and math.isfinite(max_dd):
        drawdown_pct = abs(max_dd) * 100.0
        components["drawdown_control"] = _normalize(-drawdown_pct, -50.0, 0.0, pm.get("drawdown_control"))
    else:
        components["drawdown_control"] = 45.0

    # tracking_efficiency: lower tracking error = better (for gold passive exposure)
    # Range: 0 to 5% TE. Score 100 at TE=0, score 0 at TE >= 5%.
    te = float(alt.tracking_error_1y) if alt.tracking_error_1y is not None else None
    if te is not None:
        # Inverted: lower TE is better
        te_score = max(0.0, min(100.0, (1.0 - te / 0.05) * 100))
        components["tracking_efficiency"] = te_score
    else:
        components["tracking_efficiency"] = pm.get("tracking_efficiency", 45.0)

    # fee_efficiency: shared formula
    components["fee_efficiency"] = _compute_fee_efficiency(expense_ratio_pct, pm)

    weights = resolve_alt_profile_weights(profile, config)

    missing = set(weights.keys()) - components.keys()
    if missing:
        raise ValueError(
            f"_compute_alternatives_score: weights reference components not provided: "
            f"{sorted(missing)}. All weighted components must be computed."
        )

    score = sum(components[k] * w for k, w in weights.items())
    # Only return components that carry weight in this profile.
    # Prevents nonsensical display (e.g., "Income Generation: 38" on a CTA fund).
    active_components = {k: round(v, 2) for k, v in components.items() if weights.get(k, 0) > 0}
    return round(score, 2), active_components


def compute_fund_score(
    metrics: RiskMetrics,
    flows_momentum_score: float | None = None,
    config: dict[str, Any] | None = None,
    expense_ratio_pct: float | None = None,
    insider_sentiment_score: float | None = None,
    peer_medians: dict[str, float] | None = None,
    asset_class: str = "equity",
    fi_metrics: FIMetrics | None = None,
    cash_metrics: CashMetrics | None = None,
    alt_metrics: AltMetrics | None = None,
    alt_profile: str | None = None,
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
        asset_class: "equity" (default), "fixed_income", "cash", or "alternatives".
               Determines scoring model.
        fi_metrics: Fixed income metrics. Required when asset_class="fixed_income".
               Falls back to equity scoring if None.
        cash_metrics: Cash/MMF metrics. Required when asset_class="cash".
               Falls back to equity scoring if None.
        alt_metrics: Alternatives metrics. Required when asset_class="alternatives".
               Falls back to equity scoring if None.
        alt_profile: Alternatives profile name (reit, commodity, gold, hedge, cta,
               generic_alt). Determines weight distribution across components.

    """
    # Dispatch to Alternatives scoring when asset_class is alternatives AND alt_metrics provided
    if asset_class == "alternatives" and alt_metrics is not None:
        return _compute_alternatives_score(
            alt_metrics, alt_profile or "generic_alt", config, expense_ratio_pct, peer_medians,
        )

    # Dispatch to Cash scoring when asset_class is cash AND cash_metrics provided
    if asset_class == "cash" and cash_metrics is not None:
        return _compute_cash_score(cash_metrics, config, expense_ratio_pct, peer_medians)

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

    sharpe = _resolve_sharpe_input(metrics, config)
    components["risk_adjusted_return"] = _normalize(sharpe, -1.0, 3.0, pm.get("risk_adjusted_return"))

    dd = float(metrics.max_drawdown_1y) if metrics.max_drawdown_1y is not None else None
    components["drawdown_control"] = _normalize(dd, -0.50, 0.0, pm.get("drawdown_control"))

    ir = float(metrics.information_ratio_1y) if metrics.information_ratio_1y is not None else None
    components["information_ratio"] = _normalize(ir, -1.0, 2.0, pm.get("information_ratio"))

    components["flows_momentum"] = (
        _clamp_component_score(flows_momentum_score, "flows_momentum")
        if flows_momentum_score is not None
        else 45.0
    )

    # Fee efficiency — shared with FI path
    components["fee_efficiency"] = _compute_fee_efficiency(expense_ratio_pct, pm)

    weights = resolve_scoring_weights(config)

    # Opt-in insider sentiment (activated when config includes "insider_sentiment" weight > 0)
    if weights.get("insider_sentiment", 0) > 0:
        if insider_sentiment_score is not None:
            components["insider_sentiment"] = _clamp_component_score(
                insider_sentiment_score, "insider_sentiment",
            )
        else:
            components["insider_sentiment"] = 45.0  # missing-data fallback

    missing = set(weights.keys()) - components.keys()
    if missing:
        raise ValueError(
            f"compute_fund_score: weights reference components not provided: "
            f"{sorted(missing)}. Caller must pass {{key}}_score kwargs for each."
        )

    score = sum(components[k] * w for k, w in weights.items())

    return round(score, 2), {k: round(v, 2) for k, v in components.items()}

"""Cash/MMF analytics -- yield spread, NAV stability, liquidity, maturity.

Sync-pure module: zero I/O, zero imports from app.* or vertical_engines.*.
Config is injected as parameter -- never reads YAML, never uses @lru_cache.

All metrics are derived from SEC N-MFP filings (sec_money_market_funds,
sec_mmf_metrics) and FRED DFF (macro_data).  The worker pre-fetches data
and passes it to these pure functions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CashAnalyticsResult:
    """Result of cash/MMF fund analytics."""

    seven_day_net_yield: float | None
    fed_funds_rate: float | None
    nav_per_share: float | None
    pct_weekly_liquid: float | None
    weighted_avg_maturity: int | None


@dataclass(frozen=True, slots=True)
class CashScoreResult:
    """Result of cash scoring computation."""

    score: float
    components: dict[str, float]


_DEFAULT_CASH_SCORING_WEIGHTS: dict[str, float] = {
    "yield_vs_risk_free": 0.30,
    "nav_stability": 0.25,
    "liquidity_quality": 0.20,
    "maturity_discipline": 0.15,
    "fee_efficiency": 0.10,
}


def _normalize(
    value: float | None,
    min_val: float,
    max_val: float,
    peer_median: float | None = None,
) -> float:
    """Normalize a value to 0-100 scale (mirrors scoring_service._normalize)."""
    if value is None:
        if peer_median is not None:
            return max(0.0, min(100.0, peer_median - 5.0))
        return 45.0
    if max_val == min_val:
        return 50.0
    return max(0.0, min(100.0, (value - min_val) / (max_val - min_val) * 100))


def compute_cash_score(
    analytics: CashAnalyticsResult,
    expense_ratio_pct: float | None = None,
    peer_medians: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
) -> CashScoreResult:
    """Compute Cash/MMF composite score from pre-fetched analytics.

    Five components: yield_vs_risk_free, nav_stability, liquidity_quality,
    maturity_discipline, fee_efficiency.

    Args:
        analytics: Pre-fetched cash metrics from SEC N-MFP + FRED DFF.
        expense_ratio_pct: XBRL expense ratio in percent (e.g. 0.35).
        peer_medians: Component medians from cash peer group.
        weights: Custom weights (defaults to _DEFAULT_CASH_SCORING_WEIGHTS).

    Returns:
        CashScoreResult with score (0-100) and component breakdown.
    """
    pm = peer_medians or {}
    components: dict[str, float] = {}
    w = weights or _DEFAULT_CASH_SCORING_WEIGHTS

    # yield_vs_risk_free: relative yield advantage over fed funds rate
    if analytics.seven_day_net_yield is not None and analytics.fed_funds_rate is not None:
        ffr = analytics.fed_funds_rate
        if ffr > 0:
            relative_yield = (analytics.seven_day_net_yield - ffr) / ffr
        else:
            relative_yield = 0.10 if analytics.seven_day_net_yield > 0 else 0.0
        components["yield_vs_risk_free"] = _normalize(
            relative_yield, -0.20, 0.20, pm.get("yield_vs_risk_free"),
        )
    else:
        components["yield_vs_risk_free"] = pm.get("yield_vs_risk_free", 45.0) - 5.0

    # nav_stability: deviation from $1.00 par value
    if analytics.nav_per_share is not None:
        deviation = abs(analytics.nav_per_share - 1.0)
        stability = max(0.0, 1.0 - deviation * 1000)  # 0.001 deviation = 0 score
        components["nav_stability"] = stability * 100
    else:
        components["nav_stability"] = pm.get("nav_stability", 45.0) - 5.0

    # liquidity_quality: weekly liquid assets %
    if analytics.pct_weekly_liquid is not None:
        # Range 30% (SEC 2a-7 regulatory min) to 100%
        components["liquidity_quality"] = _normalize(
            analytics.pct_weekly_liquid, 30.0, 100.0, pm.get("liquidity_quality"),
        )
    else:
        components["liquidity_quality"] = pm.get("liquidity_quality", 45.0) - 5.0

    # maturity_discipline: lower WAM = less interest rate risk = better
    if analytics.weighted_avg_maturity is not None:
        # 0 days = 100 (all overnight), 60 days = 0 (regulatory max). Inverted scale.
        wam_score = max(0.0, (1.0 - analytics.weighted_avg_maturity / 60.0)) * 100
        components["maturity_discipline"] = wam_score
    else:
        components["maturity_discipline"] = pm.get("maturity_discipline", 45.0) - 5.0

    # fee_efficiency: same formula as equity/FI
    if expense_ratio_pct is not None:
        # expense_ratio_pct might be in decimal fraction (0.0035) or percent (0.35)
        # Normalize: if < 0.05, treat as decimal fraction and convert to percent
        er_pct = expense_ratio_pct
        if er_pct is not None and 0 < er_pct < 0.05:
            er_pct = er_pct * 100.0
        components["fee_efficiency"] = max(0.0, 100.0 - er_pct * 50.0)
    else:
        fee_pm = pm.get("fee_efficiency")
        components["fee_efficiency"] = max(0.0, fee_pm - 5.0) if fee_pm is not None else 45.0

    score = sum(components.get(k, 50.0) * w.get(k, 0.0) for k in w)
    return CashScoreResult(
        score=round(score, 2),
        components={k: round(v, 2) for k, v in components.items()},
    )

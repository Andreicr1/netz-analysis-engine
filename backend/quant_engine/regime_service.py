"""Market regime detection service.

Classifies market regime using multi-signal approach:
- VIX (from FRED VIXCLS) for volatility stress
- Yield curve (DGS10-DGS2 spread) for recession risk
- CPI YoY for inflation
- Falls back to caller-provided fallback_regime when FRED data unavailable

Priority hierarchy: CRISIS > INFLATION > RISK_OFF > RISK_ON

classify_regime_multi_signal is a pure function. Hysteresis (regime
stickiness across consecutive evaluations) lives in callers — see
apply_regime_hysteresis() below. Wealth applies it via
risk_calc::_compute_and_persist_taa_state by reading the prior
MacroRegimeSnapshot.raw_regime; portfolio_eval applies it via
PortfolioSnapshot.regime. Credit can opt in by reading its prior
stress_severity record before calling this function.

Sync/async boundary: Pure classification functions are sync.
get_latest_macro_values() and get_current_regime() are async (DB access).
Callers dispatch sync functions via asyncio.to_thread() if needed.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "calibration").
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypedDict

import numpy as np
import structlog
from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import MacroData
from app.shared.schemas import RegimeRead

logger = structlog.get_logger()

# ── Signal metadata for structured breakdown ──────────────────────────────

SIGNAL_METADATA: dict[str, dict[str, str]] = {
    "vix":            {"label": "VIX",              "unit": "",     "category": "financial",    "fred_series": "VIXCLS"},
    "hy_oas":         {"label": "Credit Spread",    "unit": "%",    "category": "financial",    "fred_series": "BAMLH0A0HYM2"},
    "energy_shock":   {"label": "Energy Shock",     "unit": "/100", "category": "financial",    "fred_series": "DCOILWTICO"},
    "dxy":            {"label": "USD Strength",     "unit": "\u03c3",    "category": "financial",    "fred_series": "DTWEXBGS"},
    "yield_curve":    {"label": "Yield Curve",      "unit": "%",    "category": "financial",    "fred_series": "DGS10"},
    "baa_spread":     {"label": "Corp. Stress",     "unit": "%",    "category": "financial",    "fred_series": "BAA10Y"},
    "cfnai":          {"label": "Activity Index",   "unit": "",     "category": "real_economy", "fred_series": "CFNAI"},
    "sahm":           {"label": "Employment",       "unit": "",     "category": "real_economy", "fred_series": "SAHMREALTIME"},
    "ff_roc":         {"label": "Fed Policy",       "unit": "%",    "category": "real_economy", "fred_series": "DFF"},
    "icsa":           {"label": "Jobless Claims",   "unit": "\u03c3",    "category": "real_economy", "fred_series": "ICSA"},
    "credit_impulse": {"label": "Credit Impulse",   "unit": "%",    "category": "real_economy", "fred_series": "TOTBKCR"},
    "permits":        {"label": "Building Permits", "unit": "%",    "category": "real_economy", "fred_series": "PERMIT"},
}

_RAW_VALUE_RE = re.compile(r"[-+]?\d+\.?\d*")


def _extract_raw_value(reason_str: str) -> float | None:
    """Parse the raw value from reason strings like 'VIX=19.5 (stress=...)'."""
    # Extract the value portion: split on '(' to drop stress suffix, then on '=' to get RHS
    prefix = reason_str.split("(")[0] if "(" in reason_str else reason_str
    if "=" in prefix:
        prefix = prefix.split("=", 1)[1]
    m = _RAW_VALUE_RE.search(prefix)
    if m:
        try:
            return float(m.group())
        except ValueError:
            return None
    return None


class RegimeThresholds(TypedDict):
    """Typed regime detection thresholds."""

    vix_risk_off: float
    vix_extreme: float
    yield_curve_inversion: float
    cpi_yoy_high: float
    cpi_yoy_normal: float
    sahm_rule_recession: float
    default: str


class RegimeDefinition(TypedDict):
    """Typed definition for a single market regime."""

    description: str


# Hardcoded fallback — used only if config parameter is not provided.
_DEFAULT_THRESHOLDS: RegimeThresholds = {
    "vix_risk_off": 25,
    "vix_extreme": 35,
    "yield_curve_inversion": -0.10,
    "cpi_yoy_high": 4.0,
    "cpi_yoy_normal": 2.5,
    "sahm_rule_recession": 0.50,
    "default": "RISK_OFF",  # was "RISK_ON" — see BUG-R5
}

REGIME_DEFINITIONS: dict[str, RegimeDefinition] = {
    "RISK_ON": {"description": "Normal market conditions, risk appetite high"},
    "RISK_OFF": {"description": "Elevated volatility, defensive positioning"},
    "INFLATION": {"description": "Above-target inflation, favor real assets"},
    "CRISIS": {"description": "Extreme stress, maximize capital preservation"},
}

# Staleness thresholds (business days)
STALENESS_DAILY = 5  # Accommodates weekends + US holidays (FRED publishes Mon-Fri only)
STALENESS_MONTHLY = 45

# Plausibility bounds for input validation
_PLAUSIBILITY = {
    "vix": (0.0, 200.0),
    "cpi_yoy": (-10.0, 30.0),
    "yield_curve": (-10.0, 10.0),
    "sahm_rule": (-1.0, 5.0),
    "hy_oas": (0.0, 50.0),
    "baa_spread": (-2.0, 20.0),
    "fed_funds_delta_6m": (-15.0, 15.0),
    "dxy_zscore": (-10.0, 10.0),
    "energy_shock": (0.0, 100.0),
    "cfnai": (-10.0, 10.0),
    "icsa_zscore": (-10.0, 10.0),
    "credit_impulse": (-100.0, 100.0),
    "permits_roc": (-100.0, 200.0),
}


def resolve_regime_thresholds(config: dict[str, Any] | None = None) -> RegimeThresholds:
    """Extract regime thresholds from calibration config dict.

    Falls back to hardcoded defaults if config is None or malformed.
    """
    if config is None:
        return _DEFAULT_THRESHOLDS

    try:
        raw = config.get("regime_thresholds", {})
        if not raw:
            return _DEFAULT_THRESHOLDS
        return RegimeThresholds(
            vix_risk_off=float(raw["vix_risk_off"]),
            vix_extreme=float(raw["vix_extreme"]),
            yield_curve_inversion=float(raw.get("yield_curve_inversion", -0.10)),
            cpi_yoy_high=float(raw.get("cpi_yoy_high", 4.0)),
            cpi_yoy_normal=float(raw.get("cpi_yoy_normal", 2.5)),
            sahm_rule_recession=float(raw.get("sahm_rule_recession", 0.50)),
            default=raw.get("default", "RISK_OFF"),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Malformed regime config, using defaults", error=str(e))
        return _DEFAULT_THRESHOLDS


def _validate_plausibility(
    name: str,
    value: float | None,
) -> float | None:
    """Reject None, NaN, Inf, and out-of-bounds values."""
    if value is None:
        return None
    if not math.isfinite(value):
        logger.warning(
            "Non-finite macro value rejected",
            signal=name,
            value=value,
        )
        return None
    lo, hi = _PLAUSIBILITY.get(name, (float("-inf"), float("inf")))
    if value < lo or value > hi:
        logger.warning(
            "Implausible macro value rejected",
            signal=name,
            value=value,
            bounds=(lo, hi),
        )
        return None
    return value


def _amplify_weights(
    signals: list[tuple[str, float, float, str]],
    alpha: float = 2.0,
    gamma: float = 2.0,
    w_max: float = 0.35,
) -> list[tuple[str, float, float, str]]:
    """Compute dynamic weights based on signal amplitude.

    Extreme signals get amplified weights via convex scaling.
    Calm signals are nearly transparent to the amplification.

    Formula: w_eff_i = w_base_i * (1 + alpha * (s_i / 100)^gamma)
    Then renormalize to unit sum, cap at w_max with redistribution.

    Args:
        signals: List of (label, score, weight, reason) tuples.
        alpha: Max amplification multiplier. 2.0 means a maxed signal
               gets 3x its base weight before renormalization.
        gamma: Convexity exponent. 2.0 (quadratic) means score=50 gets
               25% of max amplification, score=80 gets 64%.
        w_max: Hard cap on any single signal's final weight. Prevents
               single-factor tyranny.

    Returns:
        New signals list with adjusted weights summing to ~1.0.
    """
    if not signals:
        return signals

    # Step 1: amplify
    amplified: list[tuple[str, float, float, str]] = []
    for label, score, weight, reason in signals:
        amp = weight * (1.0 + alpha * (score / 100.0) ** gamma)
        amplified.append((label, score, amp, reason))

    # Step 2: normalize to unit sum
    total = sum(w for _, _, w, _ in amplified)
    if total <= 0:
        return signals

    normalized = [
        (label, score, w / total, reason)
        for label, score, w, reason in amplified
    ]

    # Step 3: enforce w_max cap with redistribution
    n = len(normalized)
    # If the cap is infeasible (n * w_max < 1.0), uniform weights are the only
    # stable answer. Detect this up front to avoid pointless iteration.
    if n * w_max < 1.0 - 1e-9:
        return [(label, score, 1.0 / n, reason) for label, score, _, reason in normalized]

    for _ in range(5):  # Max 5 iterations to converge
        excess = 0.0
        uncapped_total = 0.0
        has_capped = False
        result: list[tuple[str, float, float, str]] = []

        for label, score, w, reason in normalized:
            if w > w_max:
                excess += w - w_max
                result.append((label, score, w_max, reason))
                has_capped = True
            else:
                uncapped_total += w
                result.append((label, score, w, reason))

        if not has_capped or excess <= 0:
            normalized = result
            break

        if uncapped_total <= 0:
            # All non-capped signals are at zero (or all signals capped).
            # Distribute the residual equally to all signals.
            residual = excess / n
            normalized = [
                (label, score, w_max + residual, reason)
                for label, score, _, reason in result
            ]
            logger.warning(
                "regime_amplify_cap_infeasible",
                n_signals=n,
                w_max=w_max,
                residual=residual,
            )
            break

        # Redistribute excess proportionally among uncapped signals
        normalized = [
            (
                label, score,
                w + (excess * w / uncapped_total) if w < w_max else w,
                reason,
            )
            for label, score, w, reason in result
        ]

    return normalized


@dataclass
class RegimeResult:
    regime: str
    description: str | None = None
    reasons: dict[str, str] = field(default_factory=dict)


# Asymmetric severity ranking for hysteresis.
# Higher = more severe. CRISIS entry should be immediate;
# de-escalation back to RISK_ON should require a real shift, not
# a one-day blip below threshold.
_REGIME_SEVERITY: dict[str, int] = {
    "RISK_ON":   0,
    "INFLATION": 1,
    "RISK_OFF":  2,
    "CRISIS":    3,
}


def apply_regime_hysteresis(
    prev_regime: str | None,
    new_regime: str,
    severity_jump_threshold: int = 1,
) -> str:
    """Asymmetric regime stickiness — immediate escalation, slow de-escalation.

    Caller-side helper. classify_regime_multi_signal does NOT call this.

    Behavior:
      * Escalation (new severity > prev): always honor immediately. CRISIS
        entry never blocked.
      * De-escalation (new severity < prev): only honor if the severity drop
        meets `severity_jump_threshold`. Default 1 = drop one notch per
        evaluation.
      * Same severity: pass through.

    Args:
        prev_regime: prior regime label (None on cold start → no hysteresis).
        new_regime: regime returned by classify_regime_multi_signal.
        severity_jump_threshold: minimum severity decrease to honor a
            de-escalation. 1 = honor any drop; 2 = require dropping two
            severity ranks in a single step (rare).

    Returns:
        Effective regime label after applying hysteresis.

    """
    if prev_regime is None or prev_regime == new_regime:
        return new_regime
    prev_sev = _REGIME_SEVERITY.get(prev_regime, 0)
    new_sev = _REGIME_SEVERITY.get(new_regime, 0)
    if new_sev >= prev_sev:
        return new_regime  # escalation or same severity → honor immediately
    # De-escalation: only honor if drop is large enough.
    if (prev_sev - new_sev) >= severity_jump_threshold:
        return new_regime
    return prev_regime


def classify_regime_multi_signal(
    vix: float | None,
    yield_curve_spread: float | None,
    cpi_yoy: float | None,
    sahm_rule: float | None = None,
    thresholds: RegimeThresholds | None = None,
    config: dict[str, Any] | None = None,
    *,
    hy_oas: float | None = None,
    baa_spread: float | None = None,
    fed_funds_delta_6m: float | None = None,
    dxy_zscore: float | None = None,
    energy_shock: float | None = None,
    cfnai: float | None = None,
    icsa_zscore: float | None = None,
    credit_impulse: float | None = None,
    permits_roc: float | None = None,
) -> tuple[str, dict[str, str], list[dict[str, Any]]]:
    """Classify regime using multi-factor stress scoring.

    Combines financial market signals with real-economy indicators to avoid
    monetary bias. Supply shocks (oil, commodities) and production contractions
    are leading indicators that precede VIX/credit spread reactions by weeks.

    Regime classification from composite stress score:
        score < 25  → RISK_ON   (benign conditions)
        score < 50  → RISK_OFF  (elevated caution, defensive tilt)
        score ≥ 50  → CRISIS    (multiple stress signals, capital preservation)

    CPI override: inflation above threshold triggers INFLATION regime
    regardless of stress score.

    Profile A base weights (40% financial / 60% real-economy).
    Dynamic amplification via _amplify_weights() boosts extreme signals.

    === FINANCIAL SIGNALS (40%) — react within days ===
        VIX (10%):              Implied vol. LT avg ~19, ramp 18→35.
        HY OAS (12%):           US HY credit spread. Normal ~3.0, stress >5.0.
        Energy Shock (12%):     Composite of WTI Z-score (1Y) and WTI RoC (3m),
                                fused via max(z_score, roc_score). Single signal
                                avoids multicollinearity — both spike together
                                during supply shocks but capture different tails.
        DXY Z-score (8%):       Dollar strength surprise → global liquidity crunch.
        BAA spread (5%):        Corporate credit risk → real economy stress.

    === REAL-ECONOMY SIGNALS (60%) — structural, weeks-to-months lag ===
        CFNAI (18%):            Chicago Fed National Activity Index. Composite
                                of 85 indicators (production, employment,
                                consumption, sales). 0 = trend growth, below
                                -0.70 = high probability of recession.
        Sahm Rule (8%):         Labor market recession onset at 0.50.
        ICSA Z-score (8%):      Initial Jobless Claims 4wk MA Z-score.
                                Weekly frequency, leads Sahm by 4-8 weeks.
        Yield curve (5%):       10Y-2Y. Inverted = recession signal.
        FF Rate-of-Change (5%): 6-month Fed Funds delta. Rapid hikes = stress.
        Credit Impulse (5%):    6-month RoC of total bank credit (TOTBKCR).
                                Negative = credit contraction = stress.
        Building Permits (4%):  6-month RoC of building permits (PERMIT).
                                Longest-lead recession indicator (9-12 months).

    """
    if thresholds is None:
        thresholds = resolve_regime_thresholds(config)

    # Validate plausibility
    vix = _validate_plausibility("vix", vix)
    yield_curve_spread = _validate_plausibility("yield_curve", yield_curve_spread)
    cpi_yoy = _validate_plausibility("cpi_yoy", cpi_yoy)
    sahm_rule = _validate_plausibility("sahm_rule", sahm_rule)
    hy_oas = _validate_plausibility("hy_oas", hy_oas)
    baa_spread = _validate_plausibility("baa_spread", baa_spread)
    fed_funds_delta_6m = _validate_plausibility("fed_funds_delta_6m", fed_funds_delta_6m)
    dxy_zscore = _validate_plausibility("dxy_zscore", dxy_zscore)
    energy_shock = _validate_plausibility("energy_shock", energy_shock)
    cfnai = _validate_plausibility("cfnai", cfnai)
    icsa_zscore = _validate_plausibility("icsa_zscore", icsa_zscore)
    credit_impulse = _validate_plausibility("credit_impulse", credit_impulse)
    permits_roc = _validate_plausibility("permits_roc", permits_roc)

    reasons: dict[str, str] = {}

    # ── Multi-factor stress scoring ──
    # Each signal produces a sub-score 0-100 via _ramp().
    # Weighted sum → composite stress score (0-100).
    # Two layers: financial (55%) + real economy (45%).
    signals: list[tuple[str, float, float, str]] = []  # (label, sub_score, weight, reason)

    # ═══ FINANCIAL SIGNALS (55%) ═══

    # VIX (10%): implied vol. LT avg ~19, ramp 18→35
    if vix is not None:
        s = _ramp(vix, calm=18.0, panic=35.0)
        signals.append(("vix", s, 0.10, f"VIX={vix:.1f} (stress={s:.0f}/100)"))

    # US HY OAS (12%): credit stress. Normal ~3.0%, stress >5.0%
    if hy_oas is not None:
        s = _ramp(hy_oas, calm=2.5, panic=6.0)
        signals.append(("hy_oas", s, 0.12, f"US_HY_OAS={hy_oas:.2f}% (stress={s:.0f}/100)"))

    # DXY Z-score (8%): sharp dollar rally = global liquidity crunch
    if dxy_zscore is not None:
        s = _ramp(dxy_zscore, calm=0.0, panic=2.0)
        signals.append(("dxy", s, 0.08, f"DXY_z={dxy_zscore:+.2f}σ (stress={s:.0f}/100)"))

    # ═══ SLOW SIGNALS (45%) — structural, weeks-to-months lag ═══

    # Energy Shock Composite (10%): fuses WTI symmetric Z-score (1Y) and WTI
    # RoC (3m) into a single signal via max(). The Z-score is symmetric so a
    # negative-WTI demand-crash (April 2020) and an OPEC+ supply cut both
    # register as macro stress. RoC captures any sharp move regardless of
    # direction. Avoids multicollinearity since both spike together during
    # real shocks.
    if energy_shock is not None:
        s = _ramp(energy_shock, calm=0.0, panic=100.0)
        signals.append(("energy_shock", s, 0.12, f"Energy_shock={energy_shock:.0f}/100 (stress={s:.0f}/100)"))

    # CFNAI (15%): Chicago Fed National Activity Index.
    # Composite of 85 indicators. 0 = trend growth, negative = below trend.
    # Below -0.70 = high probability of recession (NBER-calibrated).
    # Monthly, minimal revisions. Much more robust than INDPRO alone.
    if cfnai is not None:
        # Inverted: positive = calm (above-trend growth), negative = stress
        s = _ramp(-cfnai, calm=0.20, panic=0.70)
        signals.append(("cfnai", s, 0.18, f"CFNAI={cfnai:+.2f} (stress={s:.0f}/100)"))

    # Yield curve (5%): +1.0=calm, -0.5=full stress (inverted)
    if yield_curve_spread is not None:
        yc_s = _ramp(-yield_curve_spread, calm=-1.0, panic=0.5)
        # Move to slow block (recession signal takes months to materialize)
        signals.append(("yield_curve", yc_s, 0.05, f"10Y-2Y={yield_curve_spread:+.2f}% (stress={yc_s:.0f}/100)"))

    # BAA-10Y spread (5%): corporate credit → real economy stress
    if baa_spread is not None:
        s = _ramp(baa_spread, calm=1.2, panic=2.5)
        signals.append(("baa_spread", s, 0.05, f"BAA-10Y={baa_spread:.2f}% (stress={s:.0f}/100)"))


    # Fed Funds rate-of-change (5%): surprise tightening
    if fed_funds_delta_6m is not None:
        s = _ramp(fed_funds_delta_6m, calm=-0.50, panic=1.50)
        signals.append(("ff_roc", s, 0.05, f"FF_Δ6m={fed_funds_delta_6m:+.2f}% (stress={s:.0f}/100)"))

    # Sahm Rule (8%): labor market recession onset at 0.50
    if sahm_rule is not None:
        s = _ramp(sahm_rule, calm=0.0, panic=0.50)
        signals.append(("sahm", s, 0.08, f"Sahm={sahm_rule:.2f} (stress={s:.0f}/100)"))

    # Initial Jobless Claims Z-score (8%): weekly frequency, leads Sahm by 4-8 weeks
    if icsa_zscore is not None:
        s = _ramp(icsa_zscore, calm=0.5, panic=2.5)
        signals.append(("icsa", s, 0.08, f"ICSA_z={icsa_zscore:+.2f}\u03c3 (stress={s:.0f}/100)"))

    # Credit Impulse (5%): 6m RoC of bank credit. Negative = contraction = stress.
    # Inverted: we ramp on the negative side.
    if credit_impulse is not None:
        s = _ramp(-credit_impulse, calm=-0.5, panic=2.0)
        signals.append(("credit_impulse", s, 0.05, f"CreditImpulse={credit_impulse:+.1f}% (stress={s:.0f}/100)"))

    # Building Permits 6m RoC (4%): longest-lead recession indicator (9-12 months).
    # Falling permits = stress. Inverted.
    if permits_roc is not None:
        s = _ramp(-permits_roc, calm=-5.0, panic=20.0)
        signals.append(("permits", s, 0.04, f"Permits_\u03946m={permits_roc:+.1f}% (stress={s:.0f}/100)"))

    # Single-signal path: classify directly from sub-score with degraded confidence
    if len(signals) == 1:
        label, sub_score, _, reason_str = signals[0]
        reasons[label] = reason_str
        reasons["composite_stress"] = f"{sub_score:.1f}/100 (1 signal — degraded confidence)"
        if sub_score >= 75:
            regime = "CRISIS"
            reasons["decision"] = (
                f"CRISIS: single-signal {label}={sub_score:.0f}/100 "
                "(degraded confidence — only 1 signal available)"
            )
        elif sub_score >= 50:
            regime = "RISK_OFF"
            reasons["decision"] = (
                f"RISK_OFF: single-signal {label}={sub_score:.0f}/100 "
                "(degraded confidence — only 1 signal available)"
            )
        else:
            regime = "RISK_ON"
            reasons["decision"] = (
                f"RISK_ON: single-signal {label}={sub_score:.0f}/100 "
                "(degraded confidence — only 1 signal available)"
            )
        return regime, reasons, []

    if len(signals) == 0:
        reasons["decision"] = "RISK_OFF: no signals available — defensive default"
        return "RISK_OFF", reasons, []

    # Step 1: renormalize base weights for available signals
    weight_sum = sum(w for _, _, w, _ in signals)
    if weight_sum > 0 and abs(weight_sum - 1.0) > 0.001:
        signals = [(l, s, w / weight_sum, r) for l, s, w, r in signals]

    # Step 2: resolve amplification config
    amp_config: dict[str, Any] = {}
    if config:
        amp_config = config.get("regime_amplification", {})
    amp_alpha = float(amp_config.get("alpha", 2.0))
    amp_gamma = float(amp_config.get("gamma", 2.0))
    amp_w_max = float(amp_config.get("w_max", 0.35))

    # Step 3: apply dynamic weight amplification
    base_signals = list(signals)  # snapshot before amplification
    signals = _amplify_weights(signals, alpha=amp_alpha, gamma=amp_gamma, w_max=amp_w_max)

    # Step 4: log weight changes for audit trail
    for (label, _, w_final, _), (_, _, w_base, _) in zip(signals, base_signals, strict=True):
        if abs(w_final - w_base) > 0.005:
            reasons[f"w_dyn_{label}"] = f"{w_base:.3f}\u2192{w_final:.3f}"

    reasons["amplification"] = f"alpha={amp_alpha}, gamma={amp_gamma}, w_max={amp_w_max}"

    # Step 5: compute composite
    stress_score = sum(s * w for _, s, w, _ in signals)

    for label, _, _, reason_str in signals:
        reasons[label] = reason_str

    stress_score = round(min(100.0, max(0.0, stress_score)), 1)
    reasons["composite_stress"] = f"{stress_score}/100 ({len(signals)} signals)"

    # ── Classify from composite score ──
    if stress_score >= 75:
        regime = "CRISIS"
        reasons["decision"] = f"CRISIS: composite stress {stress_score}/100 — extreme multi-signal stress"
    elif stress_score >= 50:
        regime = "CRISIS"
        reasons["decision"] = f"CRISIS: composite stress {stress_score}/100 — multiple elevated signals"
    elif cpi_yoy is not None and cpi_yoy >= thresholds["cpi_yoy_high"]:
        # Inflation override: structural regime, but only when stress isn't already CRISIS.
        # Priority hierarchy: CRISIS > INFLATION > RISK_OFF > RISK_ON.
        regime = "INFLATION"
        reasons["cpi"] = f"CPI_YoY={cpi_yoy:.1f}% >= {thresholds['cpi_yoy_high']}% (INFLATION)"
        reasons["decision"] = (
            f"INFLATION: CPI above threshold (stress {stress_score}/100 below CRISIS floor)"
        )
    elif stress_score >= 25:
        regime = "RISK_OFF"
        reasons["decision"] = f"RISK_OFF: composite stress {stress_score}/100 — caution warranted"
    else:
        regime = "RISK_ON"
        reasons["decision"] = f"RISK_ON: composite stress {stress_score}/100 — benign conditions"

    # ── Build structured signal breakdown ──
    base_weight_map = {label: w for label, _, w, _ in base_signals}
    structured_signals: list[dict[str, Any]] = []
    for label, sub_score, weight, reason_str in signals:
        meta = SIGNAL_METADATA.get(label, {})
        structured_signals.append({
            "key": label,
            "label": meta.get("label", label),
            "raw_value": _extract_raw_value(reason_str),
            "unit": meta.get("unit", ""),
            "stress_score": round(sub_score, 1),
            "weight_base": round(base_weight_map.get(label, weight), 4),
            "weight_effective": round(weight, 4),
            "category": meta.get("category", "financial"),
            "fred_series": meta.get("fred_series"),
        })

    return regime, reasons, structured_signals


def _ramp(value: float, calm: float, panic: float) -> float:
    """Linear ramp from 0 (at calm) to 100 (at panic). Clamped to [0, 100].

    Returns 0 for non-finite inputs (defensive — _validate_plausibility
    should have stripped them already).
    """
    if not math.isfinite(value):
        return 0.0
    if panic == calm:
        return 50.0
    return max(0.0, min(100.0, (value - calm) / (panic - calm) * 100))


def classify_regime_from_volatility(
    annualized_vol: float,
    vix_risk_off: float = 25.0,
    vix_extreme: float = 35.0,
) -> str:
    """Fallback: classify regime from portfolio volatility proxy.

    Returns "RISK_OFF" defensively if input is non-finite.
    """
    if not math.isfinite(annualized_vol):
        return "RISK_OFF"
    vol_pct = annualized_vol * 100
    if vol_pct >= vix_extreme:
        return "CRISIS"
    if vol_pct >= vix_risk_off:
        return "RISK_OFF"
    return "RISK_ON"


def detect_regime(
    returns: np.ndarray,
    trading_days_per_year: int = 252,
    config: dict[str, Any] | None = None,
) -> RegimeResult:
    """Detect market regime from a returns series (volatility proxy fallback).

    Args:
        config: Raw calibration config dict from ConfigService.

    """
    thresholds = resolve_regime_thresholds(config)

    if len(returns) < 10:
        default = thresholds["default"]
        defn = REGIME_DEFINITIONS.get(default)
        logger.warning(
            "regime_default_fallback",
            site="detect_regime.insufficient_data",
            default_regime=default,
            n_returns=int(len(returns)),
            message=(
                "detect_regime received < 10 returns and is returning the default "
                f"regime ({default}). Callers should provide a last-known-good "
                "regime via PortfolioSnapshot lookup before falling through here."
            ),
        )
        return RegimeResult(
            regime=default,
            description=defn["description"] if defn is not None else None,
            reasons={"decision": "insufficient data, using default"},
        )

    clean = returns[np.isfinite(returns)] if returns.size else returns
    if len(clean) < 10:
        default = thresholds["default"]
        defn = REGIME_DEFINITIONS.get(default)
        logger.warning(
            "regime_default_fallback",
            site="detect_regime.insufficient_clean_data",
            default_regime=default,
            n_returns=int(len(clean)),
            message=(
                "detect_regime received < 10 clean returns after non-finite filter and is "
                f"returning the default regime ({default}). Callers should provide a "
                "last-known-good regime via PortfolioSnapshot lookup before falling through here."
            ),
        )
        return RegimeResult(
            regime=default,
            description=defn["description"] if defn is not None else None,
            reasons={"decision": "insufficient data after non-finite filter, using default"},
        )

    vol = float(np.std(clean) * np.sqrt(trading_days_per_year))
    if not math.isfinite(vol):
        default = thresholds["default"]
        defn = REGIME_DEFINITIONS.get(default)
        return RegimeResult(
            regime=default,
            description=defn["description"] if defn is not None else None,
            reasons={"decision": "non-finite volatility computed, using default"},
        )

    regime = classify_regime_from_volatility(
        vol,
        vix_risk_off=thresholds["vix_risk_off"],
        vix_extreme=thresholds["vix_extreme"],
    )

    defn = REGIME_DEFINITIONS.get(regime)
    return RegimeResult(
        regime=regime,
        description=defn["description"] if defn is not None else None,
        reasons={"volatility_proxy": f"annualized_vol={vol:.4f}"},
    )


async def get_latest_macro_values(
    db: AsyncSession,
) -> dict[str, tuple[float | None, date | None]]:
    """Query latest VIX, yield curve spread, CPI YoY, Fed Funds from macro_data."""
    series_staleness = {
        "VIXCLS": STALENESS_DAILY,
        "YIELD_CURVE_10Y2Y": STALENESS_DAILY,
        "CPI_YOY": STALENESS_MONTHLY,
        "DFF": STALENESS_DAILY,
        "SAHMREALTIME": STALENESS_MONTHLY,
        "CFNAI": 75,                             # Chicago Fed National Activity Index (published ~1mo lag)
        "BAA10Y": STALENESS_DAILY,              # BAA corporate spread
        # Regional credit spread signals (Phase 2 — hierarchical regime)
        "BAMLH0A0HYM2": STALENESS_DAILY,       # US HY OAS
        "BAMLHE00EHYIOAS": STALENESS_DAILY,     # Euro HY OAS
        "BAMLEMRACRPIASIAOAS": STALENESS_DAILY,  # Asia EM Corp OAS
        "BAMLEMCBPIOAS": STALENESS_DAILY,        # EM Corp OAS
    }

    result: dict[str, tuple[float | None, date | None]] = {}
    today = date.today()

    stmt = (
        select(MacroData.series_id, MacroData.value, MacroData.obs_date)
        .where(MacroData.series_id.in_(series_staleness.keys()))
        .distinct(MacroData.series_id)
        .order_by(MacroData.series_id, MacroData.obs_date.desc())
    )
    rows = (await db.execute(stmt)).all()

    found_series = set()
    for series_id, value, obs_date in rows:
        found_series.add(series_id)
        max_stale = series_staleness.get(series_id, STALENESS_DAILY)
        days_stale = (today - obs_date).days

        if days_stale > max_stale:
            logger.warning(
                "FRED data stale",
                series=series_id,
                last_date=str(obs_date),
                days_stale=days_stale,
                threshold=max_stale,
            )
            result[series_id] = (None, obs_date)
        else:
            result[series_id] = (float(value), obs_date)

    for series_id in series_staleness:
        if series_id not in found_series:
            result[series_id] = (None, None)

    return result


async def _compute_ff_delta_6m(
    db: AsyncSession, *, as_of_date: date | None = None,
) -> float | None:
    """Compute 6-month change in Fed Funds Rate from macro_data.

    Returns positive delta for tightening (stress), negative for easing (calm).
    None if insufficient data.
    """
    try:
        from datetime import timedelta

        stmt = (
            select(MacroData.value, MacroData.obs_date)
            .where(MacroData.series_id == "DFF")
        )
        if as_of_date is not None:
            stmt = stmt.where(MacroData.obs_date <= as_of_date)
        stmt = stmt.order_by(MacroData.obs_date.desc()).limit(1)

        result = await db.execute(stmt)
        latest = result.first()
        if not latest:
            return None

        target_date = latest.obs_date - timedelta(days=180)
        result_6m = await db.execute(
            select(MacroData.value)
            .where(
                MacroData.series_id == "DFF",
                MacroData.obs_date <= target_date,
            )
            .order_by(MacroData.obs_date.desc())
            .limit(1),
        )
        past_val = result_6m.scalar_one_or_none()
        if past_val is None:
            return None
        past_f = float(past_val)
        latest_f = float(latest.value)
        if not math.isfinite(past_f) or not math.isfinite(latest_f):
            return None
        result_val = latest_f - past_f
        if not math.isfinite(result_val):
            return None
        return round(result_val, 4)
    except Exception:
        logger.exception("ff_delta_6m_failed")
        return None


async def _compute_series_zscore(
    db: AsyncSession, series_id: str, lookback_days: int = 252,
    *, as_of_date: date | None = None,
) -> float | None:
    """Compute Z-score of any macro series vs its rolling mean.

    Positive z = above-average (stress for supply shocks like oil).
    """
    try:
        stmt = (
            select(MacroData.value)
            .where(MacroData.series_id == series_id)
        )
        if as_of_date is not None:
            stmt = stmt.where(MacroData.obs_date <= as_of_date)
        stmt = stmt.order_by(MacroData.obs_date.desc()).limit(lookback_days)

        result = await db.execute(stmt)
        values = [float(r[0]) for r in result.all()]
        if len(values) < 60:
            return None

        latest = values[0]
        mean = float(np.mean(values))
        std = float(np.std(values))
        if std < 0.001:
            return 0.0

        return round((latest - mean) / std, 2)
    except Exception:
        logger.exception("series_zscore_failed", series_id=series_id)
        return None


async def _compute_series_roc(
    db: AsyncSession, series_id: str, months: int = 3,
    *, as_of_date: date | None = None,
) -> float | None:
    """Compute rate-of-change (%) for any macro series over N months.

    Returns percentage change: (latest - past) / past * 100.
    Positive = increase (stress for commodities, calm for INDPRO).
    """
    try:
        from datetime import timedelta

        stmt = (
            select(MacroData.value, MacroData.obs_date)
            .where(MacroData.series_id == series_id)
        )
        if as_of_date is not None:
            stmt = stmt.where(MacroData.obs_date <= as_of_date)
        stmt = stmt.order_by(MacroData.obs_date.desc()).limit(1)

        result = await db.execute(stmt)
        latest = result.first()
        if not latest:
            return None

        target_date = latest.obs_date - timedelta(days=months * 30)
        result_past = await db.execute(
            select(MacroData.value)
            .where(
                MacroData.series_id == series_id,
                MacroData.obs_date <= target_date,
            )
            .order_by(MacroData.obs_date.desc())
            .limit(1),
        )
        past_val = result_past.scalar_one_or_none()
        if past_val is None:
            return None
        past_f = float(past_val)
        latest_f = float(latest.value)
        if not math.isfinite(past_f) or not math.isfinite(latest_f):
            return None
        if abs(past_f) < 1e-6:
            return None
        result_val = (latest_f - past_f) / past_f * 100
        if not math.isfinite(result_val):
            return None
        return round(result_val, 2)
    except Exception:
        logger.exception("series_roc_failed", series_id=series_id)
        return None


async def _compute_dxy_zscore(
    db: AsyncSession, *, as_of_date: date | None = None,
) -> float | None:
    """Compute Z-score of Trade-Weighted Dollar Index vs 1Y rolling mean."""
    return await _compute_series_zscore(
        db, "DTWEXBGS", lookback_days=252, as_of_date=as_of_date,
    )


async def _compute_icsa_zscore(
    db: AsyncSession,
    *,
    as_of_date: date | None = None,
) -> float | None:
    """Z-score of 4-week MA of initial claims vs 52-week rolling stats.

    ICSA is weekly. Compute:
    1. 4-week moving average of ICSA (smooth weekly noise)
    2. Mean and stddev of the 4wk MA over the trailing 52 weeks
    3. Z-score = (current_4wk_ma - mean_52wk) / std_52wk
    """
    from datetime import timedelta

    effective_date = as_of_date or date.today()

    stmt = (
        select(MacroData.obs_date, MacroData.value)
        .where(
            MacroData.series_id == "ICSA",
            MacroData.obs_date > effective_date - timedelta(days=400),
            MacroData.obs_date <= effective_date,
        )
        .order_by(MacroData.obs_date.asc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    if len(rows) < 8:  # Need at least 8 weeks for meaningful z-score
        return None

    values = [float(r.value) for r in rows]

    # 4-week moving average
    ma4: list[float] = []
    for i in range(3, len(values)):
        ma4.append(sum(values[i - 3 : i + 1]) / 4.0)

    if len(ma4) < 26:  # Need at least 26 weeks of MA for stats
        return None

    current_ma = ma4[-1]
    # Use trailing 52 4wk-MA values (or all available if less)
    lookback = ma4[-52:] if len(ma4) >= 52 else ma4
    mean_val = sum(lookback) / len(lookback)
    variance = sum((x - mean_val) ** 2 for x in lookback) / len(lookback)
    std_val = variance**0.5

    if std_val < 1.0:  # Avoid division by near-zero
        return None

    return float((current_ma - mean_val) / std_val)


async def _compute_credit_impulse(
    db: AsyncSession,
    *,
    as_of_date: date | None = None,
) -> float | None:
    """Credit impulse: 6-month rate-of-change of total bank credit.

    Falling credit impulse (negative RoC) = credit contraction = stress.
    Uses TOTBKCR (Total Bank Credit, All Commercial Banks, Weekly).

    Returns percentage change over 6 months. Negative = contraction.
    """
    from datetime import timedelta

    effective_date = as_of_date or date.today()

    # Get latest value
    stmt_latest = (
        select(MacroData.value)
        .where(
            MacroData.series_id == "TOTBKCR",
            MacroData.obs_date <= effective_date,
        )
        .order_by(MacroData.obs_date.desc())
        .limit(1)
    )
    result_latest = await db.execute(stmt_latest)
    latest = result_latest.scalar_one_or_none()
    if latest is None:
        return None

    # Get value ~6 months ago
    target_date = effective_date - timedelta(days=180)
    stmt_old = (
        select(MacroData.value)
        .where(
            MacroData.series_id == "TOTBKCR",
            MacroData.obs_date <= target_date,
        )
        .order_by(MacroData.obs_date.desc())
        .limit(1)
    )
    result_old = await db.execute(stmt_old)
    old = result_old.scalar_one_or_none()
    if old is None:
        return None
    old_f = float(old)
    latest_f = float(latest)
    if not math.isfinite(old_f) or not math.isfinite(latest_f):
        return None
    if abs(old_f) < 1e-6:
        return None
    result_val = ((latest_f - old_f) / old_f) * 100.0
    if not math.isfinite(result_val):
        return None
    return result_val


async def _compute_permits_roc(
    db: AsyncSession,
    *,
    months: int = 6,
    as_of_date: date | None = None,
) -> float | None:
    """6-month rate-of-change of building permits (PERMIT).

    Falling permits = leading recession indicator (9-12 month lead).
    Returns percentage change. Negative = declining permits.
    """
    return await _compute_series_roc(
        db, "PERMIT", months=months, as_of_date=as_of_date,
    )


REGIME_SERIES_STALENESS: dict[str, int] = {
    "VIXCLS": STALENESS_DAILY,
    "DGS10": STALENESS_DAILY,
    "DGS2": STALENESS_DAILY,
    "CPIAUCSL": STALENESS_MONTHLY,
    "SAHMREALTIME": STALENESS_MONTHLY,
    "BAMLH0A0HYM2": STALENESS_DAILY,
    "BAA10Y": STALENESS_DAILY,
    "DFF": STALENESS_DAILY,
    "DTWEXBGS": STALENESS_DAILY,
    "DCOILWTICO": STALENESS_DAILY,
    "CFNAI": 75,
    "ICSA": 14,        # Weekly — stale after 2 weeks
    "TOTBKCR": 14,     # Weekly — stale after 2 weeks
    "PERMIT": 45,      # Monthly — stale after 45 days
}


async def build_regime_inputs(
    db: AsyncSession, as_of_date: date | None = None,
) -> dict[str, float | None]:
    """Build the full 10-signal input dict for classify_regime_multi_signal.

    Single authoritative signal builder. Both get_current_regime() and
    risk_calc TAA use this — no duplicated logic.
    """
    effective_date = as_of_date if as_of_date is not None else date.today()

    # ── Bulk-fetch latest values for all raw series ──
    stmt = (
        select(MacroData.series_id, MacroData.value, MacroData.obs_date)
        .where(MacroData.series_id.in_(REGIME_SERIES_STALENESS.keys()))
        .where(MacroData.obs_date <= effective_date)
        .where(MacroData.value.is_not(None))
        .distinct(MacroData.series_id)
        .order_by(MacroData.series_id, MacroData.obs_date.desc())
    )
    rows = (await db.execute(stmt)).all()

    latest: dict[str, float] = {}
    for series_id, value, obs_date in rows:
        max_stale = REGIME_SERIES_STALENESS.get(series_id, STALENESS_DAILY)
        days_stale = (effective_date - obs_date).days
        if days_stale > max_stale:
            logger.warning(
                "regime_signal_stale",
                series=series_id,
                last_date=str(obs_date),
                days_stale=days_stale,
                threshold=max_stale,
                effective_date=str(effective_date),
            )
        else:
            latest[series_id] = float(value)

    # ── Yield curve spread = DGS10 - DGS2 ──
    dgs10 = latest.get("DGS10")
    dgs2 = latest.get("DGS2")
    yield_spread = (dgs10 - dgs2) if dgs10 is not None and dgs2 is not None else None

    # ── CPI YoY ──
    cpi_yoy: float | None = None
    cpi_current = latest.get("CPIAUCSL")
    if cpi_current is not None and math.isfinite(cpi_current):
        cpi_12m_stmt = (
            select(MacroData.value)
            .where(MacroData.series_id == "CPIAUCSL")
            .where(MacroData.obs_date <= effective_date - relativedelta(months=12))
            .where(MacroData.value.is_not(None))
            .order_by(MacroData.obs_date.desc())
            .limit(1)
        )
        cpi_12m_raw = (await db.execute(cpi_12m_stmt)).scalar_one_or_none()
        if cpi_12m_raw is not None:
            cpi_12m = float(cpi_12m_raw)
            if math.isfinite(cpi_12m) and abs(cpi_12m) > 1e-6:
                cpi_yoy = ((cpi_current / cpi_12m) - 1.0) * 100.0
                if not math.isfinite(cpi_yoy):
                    cpi_yoy = None

    # ── Fed Funds delta 6m ──
    fed_delta = await _compute_ff_delta_6m(db, as_of_date=effective_date)

    # ── DXY Z-score ──
    dxy_z = await _compute_dxy_zscore(db, as_of_date=effective_date)

    # ── Energy Shock Composite ──
    crude_z = await _compute_series_zscore(
        db, "DCOILWTICO", lookback_days=252, as_of_date=effective_date,
    )
    crude_roc = await _compute_series_roc(
        db, "DCOILWTICO", months=3, as_of_date=effective_date,
    )
    energy_shock: float | None = None
    if crude_z is not None or crude_roc is not None:
        # Symmetric z-score: oil supply shocks (z >> 0) AND demand-crash shocks
        # (z << 0, e.g. April 2020 negative WTI) both indicate macro stress.
        z_score = (
            max(_ramp(crude_z, calm=0.5, panic=3.0), _ramp(-crude_z, calm=0.5, panic=3.0))
            if crude_z is not None
            else 0.0
        )
        roc_score = _ramp(crude_roc, calm=0.0, panic=50.0) if crude_roc is not None else 0.0
        energy_shock = max(z_score, roc_score)

    # ── CFNAI ──
    cfnai_val = latest.get("CFNAI")

    # ── Initial Jobless Claims Z-score ──
    icsa_zscore = await _compute_icsa_zscore(db, as_of_date=effective_date)

    # ── Credit Impulse ──
    credit_impulse = await _compute_credit_impulse(db, as_of_date=effective_date)

    # ── Building Permits 6m RoC ──
    permits_roc = await _compute_permits_roc(db, as_of_date=effective_date)

    return {
        "vix": latest.get("VIXCLS"),
        "yield_curve_spread": yield_spread,
        "cpi_yoy": cpi_yoy,
        "sahm_rule": latest.get("SAHMREALTIME"),
        "hy_oas": latest.get("BAMLH0A0HYM2"),
        "baa_spread": latest.get("BAA10Y"),
        "fed_funds_delta_6m": fed_delta,
        "dxy_zscore": dxy_z,
        "energy_shock": energy_shock,
        "cfnai": cfnai_val,
        "icsa_zscore": icsa_zscore,
        "credit_impulse": credit_impulse,
        "permits_roc": permits_roc,
    }


async def get_current_regime(
    db: AsyncSession,
    config: dict[str, Any] | None = None,
    *,
    as_of_date: date | None = None,
    fallback_regime: str = "RISK_OFF",  # was "RISK_ON" — see BUG-R5
) -> RegimeRead:
    """Get current market regime from FRED macro data.

    Fallback chain (applied in order):
        1. Caller-supplied fallback_regime (if explicitly passed).
        2. The hardcoded RISK_OFF default if no fallback was supplied.

    Callers SHOULD pre-fetch their own last-known-good regime
    (Wealth: PortfolioSnapshot.regime; Credit: stress_severity level)
    and pass it as fallback_regime. Falling through to the RISK_OFF
    default emits a deprecation warning so misuse can be audited.

    Args:
        config: Raw calibration config dict from ConfigService.
        as_of_date: Historical evaluation date for backtests. Forwarded
            to build_regime_inputs.
        fallback_regime: Regime to use when no FRED data is available.

    """
    inputs = await build_regime_inputs(db, as_of_date=as_of_date)

    if inputs.get("vix") is not None or inputs.get("hy_oas") is not None or inputs.get("energy_shock") is not None:
        regime, reasons, _ = classify_regime_multi_signal(
            vix=inputs.get("vix"),
            yield_curve_spread=inputs.get("yield_curve_spread"),
            cpi_yoy=inputs.get("cpi_yoy"),
            sahm_rule=inputs.get("sahm_rule"),
            config=config,
            hy_oas=inputs.get("hy_oas"),
            baa_spread=inputs.get("baa_spread"),
            fed_funds_delta_6m=inputs.get("fed_funds_delta_6m"),
            dxy_zscore=inputs.get("dxy_zscore"),
            energy_shock=inputs.get("energy_shock"),
            cfnai=inputs.get("cfnai"),
            icsa_zscore=inputs.get("icsa_zscore"),
            credit_impulse=inputs.get("credit_impulse"),
            permits_roc=inputs.get("permits_roc"),
        )
        stmt = (
            select(MacroData.obs_date)
            .where(MacroData.series_id.in_(REGIME_SERIES_STALENESS.keys()))
            .order_by(MacroData.obs_date.desc())
            .limit(1)
        )
        as_of_row = (await db.execute(stmt)).scalar_one_or_none()
        return RegimeRead(regime=regime, as_of_date=as_of_row, reasons=reasons)

    logger.warning(
        "regime_default_fallback",
        site="get_current_regime.no_signals",
        fallback_regime=fallback_regime,
        message=(
            f"No FRED macro data available — returning caller-supplied "
            f"fallback_regime={fallback_regime}. Callers should pre-fetch "
            "last-known-good from PortfolioSnapshot/stress_severity."
        ),
    )
    return RegimeRead(
        regime=fallback_regime,
        reasons={"source": "caller_fallback", "fallback": fallback_regime},
    )

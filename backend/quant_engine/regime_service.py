"""Market regime detection service.

Classifies market regime using multi-signal approach:
- VIX (from FRED VIXCLS) for volatility stress
- Yield curve (DGS10-DGS2 spread) for recession risk
- CPI YoY for inflation
- Falls back to caller-provided fallback_regime when FRED data unavailable

Priority hierarchy: CRISIS > INFLATION > RISK_OFF > RISK_ON

Phase 2 additions:
- Per-region regime classification using ICE BofA credit spread signals
- Asymmetric hysteresis (immediate CRISIS entry, slow RISK_ON recovery)
- GDP-weighted global composition with pessimistic override

Sync/async boundary: Pure classification functions are sync.
get_latest_macro_values() and get_current_regime() are async (DB access).
Callers dispatch sync functions via asyncio.to_thread() if needed.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "calibration").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, TypedDict

import numpy as np
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.models import MacroData
from app.shared.schemas import RegimeRead

logger = structlog.get_logger()


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
    "default": "RISK_ON",
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
            default=raw.get("default", "RISK_ON"),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Malformed regime config, using defaults", error=str(e))
        return _DEFAULT_THRESHOLDS


def _validate_plausibility(
    name: str,
    value: float | None,
) -> float | None:
    """Reject physically impossible values with warning log."""
    if value is None:
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


@dataclass
class RegimeResult:
    regime: str
    description: str | None = None
    reasons: dict[str, str] = field(default_factory=dict)


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
    fed_funds: float | None = None,
) -> tuple[str, dict[str, str]]:
    """Classify regime using multi-factor stress scoring.

    Instead of binary VIX thresholds, accumulates a stress score (0-100)
    from multiple independent signals. Each signal contributes proportionally
    to its severity, with diminishing-returns capping.

    Regime classification from composite stress score:
        score < 25  → RISK_ON   (benign conditions)
        score < 50  → RISK_OFF  (elevated caution, defensive tilt)
        score < 75  → CRISIS    (multiple stress signals, capital preservation)
        score >= 75 → CRISIS    (extreme — panic territory)

    CPI override: inflation above threshold triggers INFLATION regime
    regardless of stress score.

    Signals and weights:
        VIX (30%):        Long-term avg ~19. Score ramps linearly 18→35.
        HY OAS (25%):     US HY credit spread. Normal ~3.0, stress >5.0.
        Yield curve (15%): 10Y-2Y. Inverted = recession signal.
        BAA spread (10%):  Corporate credit risk. Normal ~1.2, stress >2.0.
        Fed Funds (10%):   Monetary tightness. Neutral 2-3%, restrictive >4%.
        Sahm Rule (10%):   Labor market recession indicator. Trigger at 0.50.

    """
    if thresholds is None:
        thresholds = resolve_regime_thresholds(config)

    # Validate plausibility
    vix = _validate_plausibility("vix", vix)
    yield_curve_spread = _validate_plausibility("yield_curve", yield_curve_spread)
    cpi_yoy = _validate_plausibility("cpi_yoy", cpi_yoy)
    sahm_rule = _validate_plausibility("sahm_rule", sahm_rule)

    reasons: dict[str, str] = {}

    # ── Inflation override (structural regime, not stress-driven) ──
    if cpi_yoy is not None and cpi_yoy >= thresholds["cpi_yoy_high"]:
        reasons["cpi"] = f"CPI_YoY={cpi_yoy:.1f}% >= {thresholds['cpi_yoy_high']}% (INFLATION)"
        reasons["decision"] = "INFLATION: CPI above threshold overrides stress score"
        return "INFLATION", reasons

    # ── Multi-factor stress scoring ──
    stress_score = 0.0
    signal_count = 0

    # VIX (weight 30): ramp 18→35, where 18=0 and 35=100
    if vix is not None:
        vix_score = _ramp(vix, calm=18.0, panic=35.0)
        stress_score += vix_score * 0.30
        signal_count += 1
        reasons["vix"] = f"VIX={vix:.1f} (stress={vix_score:.0f}/100)"

    # HY OAS (weight 25): ramp 2.5→6.0
    if hy_oas is not None:
        hy_score = _ramp(hy_oas, calm=2.5, panic=6.0)
        stress_score += hy_score * 0.25
        signal_count += 1
        reasons["hy_oas"] = f"US_HY_OAS={hy_oas:.2f}% (stress={hy_score:.0f}/100)"

    # Yield curve (weight 15): positive=calm, inverted=stress
    if yield_curve_spread is not None:
        # +1.0 = calm (0), 0.0 = neutral (50), -0.5 = full stress (100)
        yc_score = _ramp(-yield_curve_spread, calm=-1.0, panic=0.5)
        stress_score += yc_score * 0.15
        signal_count += 1
        reasons["yield_curve"] = f"10Y-2Y={yield_curve_spread:+.2f}% (stress={yc_score:.0f}/100)"

    # BAA spread (weight 10): ramp 1.2→2.5
    if baa_spread is not None:
        baa_score = _ramp(baa_spread, calm=1.2, panic=2.5)
        stress_score += baa_score * 0.10
        signal_count += 1
        reasons["baa_spread"] = f"BAA-10Y={baa_spread:.2f}% (stress={baa_score:.0f}/100)"

    # Fed Funds (weight 10): ramp 2.0→5.0 (higher = more restrictive)
    if fed_funds is not None:
        ff_score = _ramp(fed_funds, calm=2.0, panic=5.0)
        stress_score += ff_score * 0.10
        signal_count += 1
        reasons["fed_funds"] = f"FF={fed_funds:.2f}% (stress={ff_score:.0f}/100)"

    # Sahm Rule (weight 10): ramp 0.0→0.50
    if sahm_rule is not None:
        sahm_score = _ramp(sahm_rule, calm=0.0, panic=0.50)
        stress_score += sahm_score * 0.10
        signal_count += 1
        reasons["sahm"] = f"Sahm={sahm_rule:.2f} (stress={sahm_score:.0f}/100)"

    # If too few signals, be conservative
    if signal_count < 2:
        reasons["decision"] = "RISK_OFF: insufficient signals for confident classification"
        return "RISK_OFF", reasons

    # Normalize: if not all 6 signals present, scale up proportionally
    # so that available signals fill the full 0-100 range
    if signal_count > 0:
        max_possible_weight = sum(w for w, present in [
            (0.30, vix is not None),
            (0.25, hy_oas is not None),
            (0.15, yield_curve_spread is not None),
            (0.10, baa_spread is not None),
            (0.10, fed_funds is not None),
            (0.10, sahm_rule is not None),
        ] if present)
        if max_possible_weight > 0 and max_possible_weight < 1.0:
            stress_score = stress_score / max_possible_weight
        # stress_score is already on a 0-100 scale (weighted sum of 0-100 components)

    stress_score = round(min(100.0, max(0.0, stress_score)), 1)
    reasons["composite_stress"] = f"{stress_score}/100 ({signal_count} signals)"

    # ── Classify from composite score ──
    if stress_score >= 75:
        regime = "CRISIS"
        reasons["decision"] = f"CRISIS: composite stress {stress_score}/100 — extreme multi-signal stress"
    elif stress_score >= 50:
        regime = "CRISIS"
        reasons["decision"] = f"CRISIS: composite stress {stress_score}/100 — multiple elevated signals"
    elif stress_score >= 25:
        regime = "RISK_OFF"
        reasons["decision"] = f"RISK_OFF: composite stress {stress_score}/100 — caution warranted"
    else:
        regime = "RISK_ON"
        reasons["decision"] = f"RISK_ON: composite stress {stress_score}/100 — benign conditions"

    return regime, reasons


def _ramp(value: float, calm: float, panic: float) -> float:
    """Linear ramp from 0 (at calm) to 100 (at panic). Clamped to [0, 100]."""
    if panic == calm:
        return 50.0
    return max(0.0, min(100.0, (value - calm) / (panic - calm) * 100))


def classify_regime_from_volatility(
    annualized_vol: float,
    vix_risk_off: float = 25.0,
    vix_extreme: float = 35.0,
) -> str:
    """Fallback: classify regime from portfolio volatility proxy."""
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
        return RegimeResult(
            regime=default,
            description=defn["description"] if defn is not None else None,
            reasons={"decision": "insufficient data, using default"},
        )

    vol = float(np.std(returns) * np.sqrt(trading_days_per_year))
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


# ---------------------------------------------------------------------------
#  Regional regime detection (Phase 2)
# ---------------------------------------------------------------------------

# Primary signals: ICE BofA credit spreads — daily, never discontinued.
# OAS (Option-Adjusted Spread) measures credit stress relative to Treasuries.
REGIONAL_REGIME_SIGNALS: dict[str, list[str]] = {
    "US": ["VIXCLS", "BAMLH0A0HYM2"],       # VIX + US HY OAS
    "EUROPE": ["BAMLHE00EHYIOAS"],            # Euro HY OAS
    "ASIA": ["BAMLEMRACRPIASIAOAS"],           # Asia EM Corp OAS
    "EM": ["BAMLEMCBPIOAS"],                   # EM Corp OAS
}

# OAS thresholds calibrated from ICE BofA indices (basis points → percentage).
# HY OAS historical: median ~400bp, 75th ~550bp, 95th ~800bp.
_OAS_RISK_OFF_BP = 550   # 75th percentile → RISK_OFF
_OAS_CRISIS_BP = 800     # 95th percentile → CRISIS

# Regime ordering for comparison (higher = more severe)
_REGIME_SEVERITY: dict[str, int] = {
    "RISK_ON": 0,
    "RISK_OFF": 1,
    "INFLATION": 2,
    "CRISIS": 3,
}

# GDP weights for global regime composition.
_DEFAULT_GDP_WEIGHTS: dict[str, float] = {
    "US": 0.25,
    "EUROPE": 0.22,
    "ASIA": 0.28,
    "EM": 0.25,
}


class RegionalRegimeConfig(TypedDict, total=False):
    """Config for regional regime detection from ConfigService."""

    oas_risk_off_bp: int
    oas_crisis_bp: int
    gdp_weights: dict[str, float]


def resolve_regional_regime_config(
    config: dict[str, Any] | None = None,
) -> RegionalRegimeConfig:
    """Extract regional regime config from macro_intelligence config dict."""
    if config is None:
        return RegionalRegimeConfig(
            oas_risk_off_bp=_OAS_RISK_OFF_BP,
            oas_crisis_bp=_OAS_CRISIS_BP,
            gdp_weights=_DEFAULT_GDP_WEIGHTS,
        )
    raw = config.get("regional_regime", {})
    if not raw:
        return resolve_regional_regime_config(None)
    try:
        return RegionalRegimeConfig(
            oas_risk_off_bp=int(raw.get("oas_risk_off_bp", _OAS_RISK_OFF_BP)),
            oas_crisis_bp=int(raw.get("oas_crisis_bp", _OAS_CRISIS_BP)),
            gdp_weights=raw.get("gdp_weights", _DEFAULT_GDP_WEIGHTS),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Malformed regional regime config, using defaults", error=str(e))
        return resolve_regional_regime_config(None)


@dataclass(frozen=True)
class RegionalRegimeResult:
    """Regime classification result for a single region."""

    region: str
    regime: str
    signal_values: dict[str, float]  # FRED series_id → latest value
    reasons: dict[str, str]


@dataclass(frozen=True)
class HierarchicalRegimeResult:
    """Global + per-region regime classification."""

    global_regime: str
    regional_regimes: dict[str, str]   # region → regime
    regional_details: dict[str, RegionalRegimeResult]
    composition_reasons: dict[str, str]
    as_of_date: date


def classify_regional_regime(
    region: str,
    signal_values: dict[str, float | None],
    *,
    vix: float | None = None,
    cpi_yoy: float | None = None,
    config: RegionalRegimeConfig | None = None,
) -> RegionalRegimeResult:
    """Classify regime for a single region using credit spread signals.

    US region uses VIX + OAS. Other regions use OAS only.
    CPI inflation override applies to all regions.

    Args:
        region: Region key (US, EUROPE, ASIA, EM).
        signal_values: Mapping FRED series_id → latest value (OAS in bps).
        vix: VIX value (used for US region only).
        cpi_yoy: CPI YoY for inflation detection.
        config: Regional regime config.

    """
    if config is None:
        config = resolve_regional_regime_config(None)

    oas_risk_off = config.get("oas_risk_off_bp", _OAS_RISK_OFF_BP)
    oas_crisis = config.get("oas_crisis_bp", _OAS_CRISIS_BP)

    # Use same VIX/CPI thresholds as classify_regime_multi_signal for consistency
    vix_extreme = _DEFAULT_THRESHOLDS["vix_extreme"]      # 35
    vix_risk_off_thresh = _DEFAULT_THRESHOLDS["vix_risk_off"]  # 25
    cpi_high = _DEFAULT_THRESHOLDS["cpi_yoy_high"]         # 4.0

    reasons: dict[str, str] = {}
    valid_signals: dict[str, float] = {
        k: v for k, v in signal_values.items() if v is not None
    }

    # US: use VIX as primary, OAS as secondary
    if region == "US" and vix is not None:
        vix = _validate_plausibility("vix", vix)
        if vix is not None and vix >= vix_extreme:
            reasons["vix"] = f"VIX={vix:.1f} >= {vix_extreme} (CRISIS)"
            return RegionalRegimeResult(
                region=region, regime="CRISIS",
                signal_values=valid_signals, reasons=reasons,
            )

    # Check OAS signals for all regions
    oas_values = list(valid_signals.values())
    if oas_values:
        max_oas = max(oas_values)
        if max_oas >= oas_crisis:
            reasons["oas"] = f"OAS={max_oas:.0f}bp >= {oas_crisis}bp (CRISIS)"
            return RegionalRegimeResult(
                region=region, regime="CRISIS",
                signal_values=valid_signals, reasons=reasons,
            )

    # CPI inflation override (applies to all regions)
    if cpi_yoy is not None:
        cpi_yoy = _validate_plausibility("cpi_yoy", cpi_yoy)
        if cpi_yoy is not None and cpi_yoy >= cpi_high:
            reasons["cpi"] = f"CPI_YoY={cpi_yoy:.1f}% >= {cpi_high}% (INFLATION)"
            return RegionalRegimeResult(
                region=region, regime="INFLATION",
                signal_values=valid_signals, reasons=reasons,
            )

    # US: VIX RISK_OFF check
    if region == "US" and vix is not None and vix >= vix_risk_off_thresh:
        reasons["vix"] = f"VIX={vix:.1f} >= {vix_risk_off_thresh} (RISK_OFF)"
        return RegionalRegimeResult(
            region=region, regime="RISK_OFF",
            signal_values=valid_signals, reasons=reasons,
        )

    # OAS RISK_OFF check
    if oas_values and max(oas_values) >= oas_risk_off:
        max_oas = max(oas_values)
        reasons["oas"] = f"OAS={max_oas:.0f}bp >= {oas_risk_off}bp (RISK_OFF)"
        return RegionalRegimeResult(
            region=region, regime="RISK_OFF",
            signal_values=valid_signals, reasons=reasons,
        )

    reasons["decision"] = "RISK_ON: no stress signals triggered"
    return RegionalRegimeResult(
        region=region, regime="RISK_ON",
        signal_values=valid_signals, reasons=reasons,
    )


def compose_global_regime(
    regional_regimes: dict[str, str],
    *,
    config: RegionalRegimeConfig | None = None,
) -> tuple[str, dict[str, str]]:
    """Compose global regime from regional regimes using GDP-weighted aggregation.

    Pessimistic override rules:
    - Any region with weight >= 0.20 in CRISIS → global at minimum RISK_OFF
    - 2+ regions in CRISIS → global CRISIS regardless of weights

    Args:
        regional_regimes: Mapping region → regime string.
        config: Regional regime config with GDP weights.

    Returns:
        Tuple of (global_regime, composition_reasons).

    """
    if config is None:
        config = resolve_regional_regime_config(None)

    gdp_weights = config.get("gdp_weights", _DEFAULT_GDP_WEIGHTS)
    reasons: dict[str, str] = {}

    # Pessimistic override: 2+ regions in CRISIS → global CRISIS
    crisis_regions = [r for r, regime in regional_regimes.items() if regime == "CRISIS"]
    if len(crisis_regions) >= 2:
        reasons["override"] = (
            f"2+ regions in CRISIS ({', '.join(crisis_regions)}) → global CRISIS"
        )
        return "CRISIS", reasons

    # Pessimistic override: any significant region in CRISIS → minimum RISK_OFF
    min_regime = "RISK_ON"
    for region, regime in regional_regimes.items():
        weight = gdp_weights.get(region, 0)
        if regime == "CRISIS" and weight >= 0.20:
            min_regime = "RISK_OFF"
            reasons["pessimistic"] = (
                f"{region} (weight={weight:.2f}) in CRISIS → global minimum RISK_OFF"
            )
            break

    # GDP-weighted severity score
    severity_sum = 0.0
    weight_sum = 0.0
    for region, regime in regional_regimes.items():
        weight = gdp_weights.get(region, 0)
        severity = _REGIME_SEVERITY.get(regime, 0)
        severity_sum += severity * weight
        weight_sum += weight
        reasons[f"region_{region.lower()}"] = f"{region}={regime} (weight={weight:.2f})"

    if weight_sum > 0:
        avg_severity = severity_sum / weight_sum
    else:
        avg_severity = 0.0

    # Map average severity to regime
    if avg_severity >= 2.5:
        weighted_regime = "CRISIS"
    elif avg_severity >= 1.5:
        weighted_regime = "INFLATION"
    elif avg_severity >= 0.5:
        weighted_regime = "RISK_OFF"
    else:
        weighted_regime = "RISK_ON"

    # Apply pessimistic floor
    if _REGIME_SEVERITY.get(min_regime, 0) > _REGIME_SEVERITY.get(weighted_regime, 0):
        weighted_regime = min_regime

    reasons["decision"] = (
        f"GDP-weighted severity={avg_severity:.2f} → {weighted_regime}"
    )
    return weighted_regime, reasons


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


async def get_current_regime(
    db: AsyncSession,
    config: dict[str, Any] | None = None,
    *,
    fallback_regime: str = "RISK_ON",
) -> RegimeRead:
    """Get current market regime from FRED macro data.

    Args:
        config: Raw calibration config dict from ConfigService.
        fallback_regime: Regime label to use when FRED data is unavailable.
            Callers provide their own fallback strategy:
            - Wealth: pre-fetches from PortfolioSnapshot.regime
            - Credit: uses stress_severity level or defaults to "RISK_ON"

    """
    macro = await get_latest_macro_values(db)

    vix_val = macro.get("VIXCLS", (None, None))[0]
    yield_val = macro.get("YIELD_CURVE_10Y2Y", (None, None))[0]
    cpi_val = macro.get("CPI_YOY", (None, None))[0]
    sahm_val = macro.get("SAHMREALTIME", (None, None))[0]
    hy_oas_val = macro.get("BAMLH0A0HYM2", (None, None))[0]
    baa_val = macro.get("BAA10Y", (None, None))[0]
    dff_val = macro.get("DFF", (None, None))[0]

    # Need at least VIX or HY OAS to classify
    if vix_val is not None or hy_oas_val is not None:
        regime, reasons = classify_regime_multi_signal(
            vix_val, yield_val, cpi_val,
            sahm_rule=sahm_val, config=config,
            hy_oas=hy_oas_val, baa_spread=baa_val, fed_funds=dff_val,
        )

        as_of = None
        for _, obs_date in macro.values():
            if obs_date is not None and (as_of is None or obs_date > as_of):
                as_of = obs_date

        return RegimeRead(
            regime=regime,
            as_of_date=as_of,
            reasons=reasons,
        )

    # Fallback: caller-provided regime (no DB query for PortfolioSnapshot)
    logger.info(
        "No FRED macro data available, using caller-provided fallback",
        fallback_regime=fallback_regime,
    )
    return RegimeRead(
        regime=fallback_regime,
        reasons={"source": "caller_fallback", "fallback": fallback_regime},
    )

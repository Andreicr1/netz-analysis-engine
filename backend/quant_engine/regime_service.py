"""Market regime detection service.

Classifies market regime using multi-signal approach:
- VIX (from FRED VIXCLS) for volatility stress
- Yield curve (DGS10-DGS2 spread) for recession risk
- CPI YoY for inflation
- Falls back to caller-provided fallback_regime when FRED data unavailable

Priority hierarchy: CRISIS > INFLATION > RISK_OFF > RISK_ON

Sync/async boundary: Pure classification functions are sync.
get_latest_macro_values() and get_current_regime() are async (DB access).
Callers dispatch sync functions via asyncio.to_thread() if needed.

Config is injected as parameter by callers via ConfigService.get("liquid_funds", "calibration").
"""

from dataclasses import dataclass, field
from datetime import date
from typing import TypedDict

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
STALENESS_DAILY = 3
STALENESS_MONTHLY = 45

# Plausibility bounds for input validation
_PLAUSIBILITY = {
    "vix": (0.0, 200.0),
    "cpi_yoy": (-10.0, 30.0),
    "yield_curve": (-10.0, 10.0),
    "sahm_rule": (-1.0, 5.0),
}


def resolve_regime_thresholds(config: dict | None = None) -> RegimeThresholds:
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
    config: dict | None = None,
) -> tuple[str, dict[str, str]]:
    """Classify regime using priority hierarchy.

    Args:
        thresholds: Pre-resolved thresholds (takes precedence).
        config: Raw calibration config dict from ConfigService (resolved if thresholds is None).
    """
    if thresholds is None:
        thresholds = resolve_regime_thresholds(config)

    # Validate plausibility
    vix = _validate_plausibility("vix", vix)
    yield_curve_spread = _validate_plausibility("yield_curve", yield_curve_spread)
    cpi_yoy = _validate_plausibility("cpi_yoy", cpi_yoy)
    sahm_rule = _validate_plausibility("sahm_rule", sahm_rule)

    reasons: dict[str, str] = {}

    if vix is not None and vix >= thresholds["vix_extreme"]:
        reasons["vix"] = f"VIX={vix:.1f} >= {thresholds['vix_extreme']} (CRISIS)"
        reasons["decision"] = "CRISIS: extreme VIX overrides all other signals"
        return "CRISIS", reasons

    if cpi_yoy is not None and cpi_yoy >= thresholds["cpi_yoy_high"]:
        reasons["cpi"] = f"CPI_YoY={cpi_yoy:.1f}% >= {thresholds['cpi_yoy_high']}% (INFLATION)"
        reasons["decision"] = "INFLATION: CPI above threshold"
        return "INFLATION", reasons

    if vix is not None and vix >= thresholds["vix_risk_off"]:
        reasons["vix"] = f"VIX={vix:.1f} >= {thresholds['vix_risk_off']} (RISK_OFF)"
        reasons["decision"] = "RISK_OFF: elevated volatility"
        return "RISK_OFF", reasons

    # Informational signals — IC awareness only
    if yield_curve_spread is not None and yield_curve_spread < thresholds["yield_curve_inversion"]:
        reasons["yield_curve"] = (
            f"10Y-2Y={yield_curve_spread:.2f}% inverted "
            f"(threshold: {thresholds['yield_curve_inversion']}%) — IC awareness"
        )

    if sahm_rule is not None and sahm_rule >= thresholds["sahm_rule_recession"]:
        reasons["sahm_rule"] = (
            f"Sahm={sahm_rule:.2f} >= {thresholds['sahm_rule_recession']} "
            f"(recession onset signal — IC awareness)"
        )

    if vix is not None:
        reasons["vix"] = f"VIX={vix:.1f} < {thresholds['vix_risk_off']} (RISK_ON)"
    reasons["decision"] = "RISK_ON: no stress signals triggered"
    return "RISK_ON", reasons


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
    config: dict | None = None,
) -> RegimeResult:
    """Detect market regime from a returns series (volatility proxy fallback).

    Args:
        config: Raw calibration config dict from ConfigService.
    """
    thresholds = resolve_regime_thresholds(config)

    if len(returns) < 10:
        default = thresholds["default"]
        return RegimeResult(
            regime=default,
            description=REGIME_DEFINITIONS.get(default, {}).get("description"),
            reasons={"decision": "insufficient data, using default"},
        )

    vol = float(np.std(returns) * np.sqrt(trading_days_per_year))
    regime = classify_regime_from_volatility(
        vol,
        vix_risk_off=thresholds["vix_risk_off"],
        vix_extreme=thresholds["vix_extreme"],
    )

    return RegimeResult(
        regime=regime,
        description=REGIME_DEFINITIONS.get(regime, {}).get("description"),
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
    config: dict | None = None,
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

    if vix_val is not None:
        regime, reasons = classify_regime_multi_signal(
            vix_val, yield_val, cpi_val, sahm_rule=sahm_val, config=config
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
